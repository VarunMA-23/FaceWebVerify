"""Tests for the keyless Yandex CBIR provider and SerpApi type=all."""

import os

from backend.search.search_models import SearchResponse
from backend.search.visual_search import SerpApiProvider, keyless_visual_search
from backend.search.yandex import (
    YandexCbirError,
    _extract_sites_url,
    _parse_sites,
    yandex_reverse_search,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _query_image() -> str:
    for name in ("lena.jpg", "einstein.jpg", "marx.jpg"):
        p = os.path.join(FIXTURES, name)
        if os.path.exists(p):
            return p
    raise AssertionError("No query fixture found")


class _FakeResponse:
    def __init__(self, payload=None, code=200):
        self._payload = payload or ""
        self._code = code

    def raise_for_status(self):
        if self._code >= 400:
            import requests

            raise requests.HTTPError(str(self._code))

    @property
    def text(self):
        return self._payload


# ------------------------------------------------------------- SerpAPI type=all


def test_serpapi_requests_type_all(monkeypatch):
    """SerpAPI Google Lens must ask for type=all (exact + visual matches)."""
    import backend.search.visual_search as vs

    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["params"] = params
        return _FakeResponse()
    
    monkeypatch.setenv("SERPAPI_API_KEY", "k")
    monkeypatch.setattr(vs.requests, "get", fake_get)
    SerpApiProvider("serpapi").search("https://example.com/face.jpg")
    assert captured["params"].get("type") == "all"
    assert captured["params"].get("engine") == "google_lens"


# ------------------------------------------------------- Yandex CBIR parsing


def test_yandex_missing_sites_url_raises():
    html = "<html>no cbir_id here</html>"
    try:
        _extract_sites_url(html)
    except Exception:  # noqa: BLE001
        pass
    assert _extract_sites_url(html) is None


def test_yandex_extract_sites_url():
    html = (
        '<img alt="" src="/mock" data-bem=\'{"url":"/images/search?rpt=imageview'
        "&url=https%3A%2F%2Fx.com%2Fa.jpg&cbir_id=abc123&cbir_page=sites\","
        '"other":1}\'/>'
    )
    url = _extract_sites_url(html)
    assert url is not None and "cbir_page=sites" in url


def test_yandex_parse_sites_dedups():
    seg = (
        '["sites"]\n{"title":"First post","description":"desc one",'
        '"url":"https://x.com/a/1","domain":"x.com","originalImage":{"url":'
        '"https://pbs.twimg.com/m.jpg"}},{"title":"First post",'
        '"description":"desc one","url":"https://x.com/a/1","domain":"x.com"}'
    )
    items = _parse_sites(seg)
    assert len(items) == 1
    assert items[0]["page_url"] == "https://x.com/a/1"
    assert items[0]["image_url"] == "https://pbs.twimg.com/m.jpg"


def test_yandex_reverse_search_happy_path(monkeypatch):
    """yandex_reverse_search maps parsed sites to SearchResults."""
    sites_html = (
        '{"title":"A","description":"d","url":"https://x.com/p/1",'
        '"domain":"x.com"},{"title":"B","description":"d",'
        '"url":"https://example.com/x","domain":"example.com"}'
    )

    def fake_get(self, url, params=None, timeout=None):
        if params and params.get("rpt") == "imageview":
            return _FakeResponse(
                '<script>{"url":"/images/search?rpt=imageview'
                "&url=https%3A%2F%2Fx%2Fa.jpg&cbir_id=z&cbir_page=sites\"}</script>"
            )
        return _FakeResponse(sites_html)

    monkeypatch.setattr("backend.search.yandex.requests.Session.get", fake_get)
    results = yandex_reverse_search("https://example.com/a.jpg")
    assert any(r.url == "https://x.com/p/1" for r in results)


def test_yandex_reverse_search_no_result_set(monkeypatch):
    def fake_get(self, url, params=None, timeout=None):
        return _FakeResponse("<html>no result</html>")

    monkeypatch.setattr("backend.search.yandex.requests.Session.get", fake_get)
    try:
        yandex_reverse_search("https://example.com/a.jpg")
    except YandexCbirError:
        return
    raise AssertionError("expected YandexCbirError")


# --------------------------------------------------------- keyless_visual_search


def test_keyless_visual_search_shaped_response_no_error(monkeypatch):
    """A failure returns a shaped, empty SearchResponse (never raises)."""
    monkeypatch.setattr(
        "backend.search.visual_search.host_image",
        lambda p: "https://tmp.example/hosted.jpg",
    )
    monkeypatch.setattr(
        "backend.search.yandex.yandex_reverse_search",
        lambda url: [],
    )
    resp = keyless_visual_search(_query_image())
    assert isinstance(resp, SearchResponse)
    assert not resp.has_results
    assert resp.error
    assert resp.provider == "yandex_cbir"


def test_keyless_visual_search_happy_path(monkeypatch):
    from backend.search.search_models import SearchResult

    def fake_results(url):
        return [
            SearchResult(
                url="https://x.com/p/1",
                image_url="https://pbs.twimg.com/m.jpg",
                title="Post",
                source="yandex_cbir",
            )
        ]

    monkeypatch.setattr(
        "backend.search.visual_search.host_image",
        lambda p: "https://tmp.example/hosted.jpg",
    )
    monkeypatch.setattr(
        "backend.search.yandex.yandex_reverse_search",
        fake_results,
    )
    resp = keyless_visual_search(_query_image(), limit=5)
    assert resp.has_results
    assert resp.provider == "yandex_cbir"
    assert resp.results[0].url == "https://x.com/p/1"
    assert resp.results[0].source == "yandex_cbir"


def test_keyless_visual_search_passes_through_public_url(monkeypatch):
    from backend.search.search_models import SearchResult

    captured = {}

    def fake_results(url):
        captured["url"] = url
        return [SearchResult(url="https://x.com/p/1")]

    monkeypatch.setattr(
        "backend.search.yandex.yandex_reverse_search",
        fake_results,
    )
    keyless_visual_search("https://example.com/photo.jpg")
    assert captured["url"] == "https://example.com/photo.jpg"
