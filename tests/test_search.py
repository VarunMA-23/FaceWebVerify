"""Tests for reverse visual search (Module 3)."""

import os

import pytest

from backend.search.search_models import SearchResult
from backend.search.visual_search import (
    PROVIDERS,
    OpenWebNinjaProvider,
    search_web,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

_PROVIDER_NAMES = {"bing", "serpapi", "tineye", "openwebninja"}


def _query_image() -> str:
    for name in ("lena.jpg", "einstein.jpg", "marx.jpg"):
        p = os.path.join(FIXTURES, name)
        if os.path.exists(p):
            return p
    raise AssertionError("No query fixture found")


def test_providers_load_metadata():
    """All providers expose a name; none require a key to be listed."""
    assert any(p.name in _PROVIDER_NAMES for p in PROVIDERS)
    assert any(isinstance(p, OpenWebNinjaProvider) for p in PROVIDERS)


def test_search_result_construction():
    r = SearchResult(url="  ", image_url="", title="")
    assert r.url == ""
    assert r.image_url == ""
    assert r.title == ""


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_openwebninja_parses_results(monkeypatch):
    """OpenWebNinja response JSON must map to SearchResults correctly."""
    payload = {
        "status": "OK",
        "data": [
            {
                "title": "Einstein - Wikipedia",
                "link": "https://en.wikipedia.org/wiki/Albert_Einstein",
                "domain": "en.wikipedia.org",
                "image": "https://example.com/thumb.jpg",
            },
            {"title": "No Link Item", "domain": "example.com", "image": ""},
        ],
    }

    calls = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        calls["url"] = url
        calls["params"] = params
        calls["headers"] = headers
        return _FakeResponse(payload)

    monkeypatch.setattr("backend.search.visual_search.requests.get", fake_get)
    monkeypatch.setattr(
        "backend.search.visual_search.host_image",
        lambda path: "https://tmp.example/hosted.jpg",
    )

    provider = OpenWebNinjaProvider("openwebninja")
    resp = provider.search(os.path.join(FIXTURES, "lena.jpg"))

    assert resp.has_results
    assert len(resp.results) == 1  # second item lacks a link -> dropped
    assert resp.results[0].url == "https://en.wikipedia.org/wiki/Albert_Einstein"
    assert resp.results[0].image_url == "https://example.com/thumb.jpg"
    assert resp.results[0].source == "openwebninja"
    assert calls["headers"]["x-api-key"] == os.environ.get(
        provider._key_name(), ""
    ).strip()
    assert calls["params"]["url"] == "https://tmp.example/hosted.jpg"


def test_openwebninja_accepts_public_url(monkeypatch):
    """A URL input is passed through without hosting."""
    payload = {"data": []}
    calls = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        calls["url"] = params.get("url") if params else None
        return _FakeResponse(payload)

    monkeypatch.setattr("backend.search.visual_search.requests.get", fake_get)
    monkeypatch.setattr(
        "backend.search.visual_search.host_image",
        lambda path: "should-not-be-called.txt",
    )
    provider = OpenWebNinjaProvider("openwebninja")
    resp = provider.search("https://example.com/photo.jpg")
    assert not resp.has_results
    assert calls["url"] == "https://example.com/photo.jpg"


def test_openwebninja_routes_local_image_through_host(monkeypatch):
    """A local file path is published to a temporary public host."""
    payload = {"data": []}
    hosted = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        return _FakeResponse(payload)

    def fake_host(path):
        hosted["path"] = path
        return "https://tmp.example/hosted.jpg"

    monkeypatch.setattr("backend.search.visual_search.requests.get", fake_get)
    monkeypatch.setattr("backend.search.visual_search.host_image", fake_host)

    provider = OpenWebNinjaProvider("openwebninja")
    provider.search(os.path.join(FIXTURES, "lena.jpg"))
    assert hosted.get("path", "").endswith("lena.jpg")


def test_provider_results_capped_to_max(monkeypatch):
    """A provider returning > MAX_SEARCH_RESULTS keeps only the top N."""
    import backend.search.visual_search as vs

    monkeypatch.setattr(vs, "MAX_SEARCH_RESULTS", 10)
    payload = {
        "status": "OK",
        "data": [
            {
                "title": f"Item {i}",
                "link": f"https://example.com/item/{i}",
                "image": f"https://example.com/{i}.jpg",
            }
            for i in range(25)
        ],
    }

    def fake_get(url, params=None, headers=None, timeout=None):
        return _FakeResponse(payload)

    monkeypatch.setattr(vs.requests, "get", fake_get)
    monkeypatch.setattr(
        vs, "host_image", lambda path: "https://tmp.example/hosted.jpg"
    )

    provider = OpenWebNinjaProvider("openwebninja")
    resp = provider.search(os.path.join(FIXTURES, "lena.jpg"))

    assert len(resp.results) == 10
    assert resp.results[0].url == "https://example.com/item/0"


def test_aggregation_caps_to_limit(monkeypatch):
    """search_all_providers returns at most the top ``limit`` results."""
    from backend.evidence.consensus import search_all_providers
    from backend.search.search_models import SearchResult

    class _Bulk(OpenWebNinjaProvider):
        def available(self):
            return True

        def search(self, image_path):
            from backend.search.search_models import SearchResponse

            return SearchResponse(
                results=[
                    SearchResult(url=f"https://example.com/item/{i}")
                    for i in range(30)
                ],
                provider=self.name,
            )

    monkeypatch.setattr(
        "backend.evidence.consensus.PROVIDERS", [_Bulk("openwebninja")]
    )
    resp = search_all_providers(os.path.join(FIXTURES, "lena.jpg"), limit=10)

    assert resp.has_results
    assert len(resp.results) == 10
    assert resp.results[0].url == "https://example.com/item/0"


def test_no_key_returns_graceful_response(monkeypatch):
    """Without keys search_web returns an empty-but-shaped response."""
    for key in (
        "BING_SEARCH_API_KEY",
        "SERPAPI_API_KEY",
        "TINEYE_API_KEY",
        "OPENWEBNINJA_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    resp = search_web(_query_image())
    assert not resp.has_results
    assert resp.error


@pytest.mark.skipif(
    not any(p.configured for p in PROVIDERS),
    reason="No visual search API key configured in .env",
)
def test_search_web_returns_results():
    """With a key configured, the search must return parseable results."""
    resp = search_web(_query_image())
    assert resp.has_results
    assert len(resp.accessible_urls) >= 1


@pytest.mark.skipif(
    not any(p.configured for p in PROVIDERS),
    reason="No visual search API key configured in .env",
)
def test_search_returns_at_least_one_real_post():
    """A live search must discover at least one accessible public URL."""
    resp = search_web(_query_image())
    http_ok = 0
    for url in resp.accessible_urls[:5]:
        try:
            import requests

            r = requests.head(url, timeout=10, allow_redirects=False)
            if r.status_code < 400:
                http_ok += 1
        except Exception:  # noqa: BLE001
            pass
    assert http_ok >= 1