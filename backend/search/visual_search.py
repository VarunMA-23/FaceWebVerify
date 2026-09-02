"""Reverse image search providers.

Supports Microsoft Bing Visual Search, OpenWeb Ninja (Google Lens data),
SerpAPI, and TinEye. Each provider reads its key from the environment
(``.env``); providers with no configured key are skipped automatically.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import requests
from dotenv import load_dotenv

from backend.search.image_host import host_image
from backend.search.search_models import SearchResponse, SearchResult

load_dotenv()

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


@dataclass
class _Provider:
    name: str

    @property
    def configured(self) -> bool:
        return bool(_env(self._key_name()))

    def _key_name(self) -> str:
        return f"{self.name.upper()}_API_KEY"

    def available(self) -> bool:
        return self.configured

    def search(self, image_path: str) -> SearchResponse:
        raise NotImplementedError


class BingProvider(_Provider):
    """Microsoft Bing Visual Search API."""

    endpoint = "https://api.bing.microsoft.com/v7.0/images/visualsearch"

    def search(self, image_path: str) -> SearchResponse:
        key = _env("BING_SEARCH_API_KEY")
        try:
            with open(image_path, "rb") as fh:
                files = {"image": (os.path.basename(image_path), fh)}
                headers = {"Ocp-Apim-Subscription-Key": key}
                resp = requests.post(self.endpoint, headers=headers, files=files, timeout=30)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:  # noqa: BLE001
            return SearchResponse(provider=self.name, error=str(exc))

        results: list[SearchResult] = []
        for tag in data.get("tags", []):
            for action in tag.get("actions", []):
                if action.get("actionType") != "PagesIncluding":
                    continue
                for item in action.get("data", {}).get("value", []):
                    sr = SearchResult(
                        url=item.get("hostPageUrl", ""),
                        image_url=item.get("contentUrl", "") or item.get("thumbnailUrl", ""),
                        title=item.get("name", ""),
                        source=self.name,
                    )
                    if sr.url:
                        results.append(sr)
        return SearchResponse(results=results, provider=self.name)


class SerpApiProvider(_Provider):
    """SerpAPI reverse image search."""

    endpoint = "https://serpapi.com/search.json"

    def search(self, image_path: str) -> SearchResponse:
        key = _env("SERPAPI_API_KEY")
        try:
            params = {"engine": "google_lens", "api_key": key}
            if image_path.startswith(("http://", "https://")):
                image_url = image_path
            else:
                image_url = host_image(image_path)
                if not image_url:
                    return SearchResponse(
                        provider=self.name,
                        error="Could not publish image to a public URL",
                    )
                params["url"] = image_url
            resp = requests.get(
                "https://serpapi.com/search.json",
                params=params,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            return SearchResponse(provider=self.name, error=str(exc))

        results: list[SearchResult] = []
        for block in data.get("visual_matches", []):
            sr = SearchResult(
                url=block.get("link", ""),
                image_url=block.get("thumbnail", ""),
                title=block.get("title", ""),
                source=self.name,
            )
            if sr.url:
                results.append(sr)
        return SearchResponse(results=results, provider=self.name)


class TinEyeProvider(_Provider):
    """TinEye reverse image search API (limited free tier)."""

    endpoint = "https://api.tineye.com/rest/search/"

    def search(self, image_path: str) -> SearchResponse:
        key = _env("TINEYE_API_KEY")
        try:
            with open(image_path, "rb") as fh:
                files = {"image": fh}
                resp = requests.post(
                    self.endpoint,
                    params={"api_key": key},
                    files=files,
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:  # noqa: BLE001
            return SearchResponse(provider=self.name, error=str(exc))

        results: list[SearchResult] = []
        for match in data.get("results", [])[:20]:
            sr = SearchResult(
                url=match.get("backlink", {}).get("backlink", ""),
                image_url="",
                title=match.get("domain", ""),
                source=self.name,
            )
            if sr.url:
                results.append(sr)
        return SearchResponse(results=results, provider=self.name)


class OpenWebNinjaProvider(_Provider):
    """OpenWeb Ninja Reverse Image Search (Google Lens data via image URL).

    Requires the query image to be reachable at a public URL; local files are
    published to a temporary public host by :func:`host_image`.
    """

    endpoint = (
        "https://api.openwebninja.com/reverse-image-search/reverse-image-search"
    )

    def search(self, image_path: str) -> SearchResponse:
        key = _env("OPENWEBNINJA_API_KEY")
        try:
            if image_path.startswith(("http://", "https://")):
                image_url = image_path
            else:
                image_url = host_image(image_path)
                if not image_url:
                    return SearchResponse(
                        provider=self.name,
                        error="Could not publish image to a public URL",
                    )
            resp = requests.get(
                self.endpoint,
                params={"url": image_url, "limit": 100, "safe_search": "off"},
                headers={"x-api-key": key},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError, KeyError) as exc:
            return SearchResponse(provider=self.name, error=str(exc))

        results: list[SearchResult] = []
        for item in data.get("data", []):
            sr = SearchResult(
                url=item.get("link", ""),
                image_url=item.get("image", ""),
                title=item.get("title", ""),
                source=self.name,
            )
            if sr.url:
                results.append(sr)
        return SearchResponse(results=results, provider=self.name)


PROVIDERS = [
    BingProvider("bing"),
    OpenWebNinjaProvider("openwebninja"),
    SerpApiProvider("serpapi"),
    TinEyeProvider("tineye"),
]


def search_web(image_path: str, provider: str = "auto") -> SearchResponse:
    """Search the web for matching posts using the configured provider(s).

    Args:
        image_path: local path of the query image.
        provider: "auto" (first configured provider), "bing", "serpapi",
            "tineye". If the named provider is not configured, falls through
            to the next configured provider.

    Returns:
        SearchResponse with aggregated results and provider info.
    """
    if provider == "auto":
        candidates = PROVIDERS
    else:
        named = next((p for p in PROVIDERS if p.name == provider), None)
        candidates = [named, *_other(named)] if named else PROVIDERS

    for prov in candidates:
        if not prov.available():
            continue
        resp = prov.search(image_path)
        if resp.has_results:
            return resp
        # Try next provider on total failure.
    errors = [p.name for p in candidates if p.configured]
    return SearchResponse(
        provider=",".join(errors),
        error="No configured provider returned results",
    )


def _other(named: _Provider) -> list[_Provider]:
    return [p for p in PROVIDERS if p is not named]