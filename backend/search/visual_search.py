"""Reverse image search providers.

Supports OpenWeb Ninja (Google Lens data), SerpAPI, and TinEye. Each provider
reads its key from the environment (``.env``); providers with no configured
key are skipped automatically.
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


def _with_retry(fn, retries: int = 3, base_delay: float = 1.0):
    """Execute fn with exponential backoff retry logic on network errors."""
    import time
    for attempt in range(retries):
        try:
            return fn()
        except (requests.RequestException, TimeoutError) as exc:
            if attempt == retries - 1:
                raise exc
            time.sleep(base_delay * (2 ** attempt))


def _max_search_results(default: int = 10) -> int:
    """Configurable ceiling on results kept per provider.

    Controlled by ``MAX_SEARCH_RESULTS`` (default 10): only the top N
    results from a reverse search provider are used for face matching.
    """
    raw = _env("MAX_SEARCH_RESULTS")
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return default


MAX_SEARCH_RESULTS = _max_search_results()


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


class SerpApiProvider(_Provider):
    """SerpAPI reverse image search."""

    endpoint = "https://serpapi.com/search.json"

    def search(self, image_path: str) -> SearchResponse:
        key = _env("SERPAPI_API_KEY")
        try:
            params = {"engine": "google_lens", "type": "all", "api_key": key}
            if image_path.startswith(("http://", "https://")):
                params["url"] = image_path
            else:
                image_url = host_image(image_path)
                if not image_url:
                    return SearchResponse(
                        provider=self.name,
                        error="Could not publish image to a public URL",
                    )
                params["url"] = image_url
            def _do_get():
                r = requests.get(
                    "https://serpapi.com/search.json",
                    params=params,
                    timeout=30,
                )
                r.raise_for_status()
                return r
            resp = _with_retry(_do_get)
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
        return SearchResponse(
            results=results[:MAX_SEARCH_RESULTS],
            provider=self.name,
        )


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
        for match in data.get("results", [])[:MAX_SEARCH_RESULTS]:
            sr = SearchResult(
                url=match.get("backlink", {}).get("backlink", ""),
                image_url="",
                title=match.get("domain", ""),
                source=self.name,
            )
            if sr.url:
                results.append(sr)
        return SearchResponse(
            results=results[:MAX_SEARCH_RESULTS],
            provider=self.name,
        )


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
                params={"url": image_url, "limit": MAX_SEARCH_RESULTS, "safe_search": "off"},
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
        return SearchResponse(
            results=results[:MAX_SEARCH_RESULTS],
            provider=self.name,
        )


PROVIDERS = [
    OpenWebNinjaProvider("openwebninja"),
    SerpApiProvider("serpapi"),
    TinEyeProvider("tineye"),
]


def _env_bool(name: str, default: bool = True) -> bool:
    value = _env(name)
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _crop_file(image_path: str) -> tuple[str, str | None]:
    """Produce a face-cropped copy of ``image_path`` for search.

    When ``CROP_TO_FACE`` is enabled (default) and a face is detectable,
    returns ``(cropped_path, cropped_path)`` so reverse-image providers
    search the face region rather than the whole photo. Falls back to
    ``(original_path, None)`` when disabled, or when no face is found /
    cropping fails. The second element is the temp file the caller should
    delete, or ``None`` when no temp file was created.
    """
    if not _env_bool("CROP_TO_FACE", default=True):
        return image_path, None

    try:
        import tempfile

        from backend.face.crop import crop_to_primary_face

        cropped = crop_to_primary_face(image_path)
        if cropped is None:
            return image_path, None
        ext = ".png" if image_path.lower().endswith(".png") else ".jpg"
        fd, tmp = tempfile.mkstemp(prefix="face_crop_", suffix=ext)
        with os.fdopen(fd, "wb") as fh:
            import cv2

            ok, buf = cv2.imencode(ext, cropped)
            if ok:
                fh.write(buf.tobytes())
        return tmp, tmp
    except Exception:  # noqa: BLE001
        return image_path, None


def search_web(
    image_path: str,
    provider: str = "auto",
    precropped: str | None = None,
) -> SearchResponse:
    """Search the web for matching posts using configured provider(s).

    When ``provider`` is ``auto`` and multiple providers are configured,
    runs all providers in parallel and aggregates/deduplicates results.
    With a single provider, runs that provider only.

    Unless ``CROP_TO_FACE`` is disabled (or no face is detected), the image is
    first cropped to the primary face region so providers search the subject
    rather than the whole photo. Callers that already cropped (e.g. the
    pipeline runner) may pass the result via ``precropped`` to skip the crop.
    """
    temp_path: str | None = None
    if precropped:
        image_path = precropped
    else:
        image_path, temp_path = _crop_file(image_path)
    try:
        return _search_payload(image_path, provider)
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def _search_payload(image_path: str, provider: str) -> SearchResponse:
    from backend.evidence.consensus import search_all_providers, to_search_results

    if provider != "auto":
        named = next((p for p in PROVIDERS if p.name == provider), None)
        candidates = [named, *_other(named)] if named else PROVIDERS
        for prov in candidates:
            if not prov.available():
                continue
            resp = prov.search(image_path)
            if resp.has_results:
                resp.results = resp.results[:MAX_SEARCH_RESULTS]
                return resp
        errors = [p.name for p in candidates if p.configured]
        return SearchResponse(
            provider=",".join(errors),
            error="No configured provider returned results",
        )

    aggregated = search_all_providers(image_path, limit=MAX_SEARCH_RESULTS)
    if not aggregated.has_results:
        return SearchResponse(
            provider=aggregated.provider,
            error=aggregated.error or "No search results returned.",
            providers_used=aggregated.providers_used,
            providers_available=aggregated.providers_available,
            provider_errors=aggregated.provider_errors,
        )

    return SearchResponse(
        results=to_search_results(aggregated),
        provider=aggregated.provider,
        providers_used=aggregated.providers_used,
        providers_available=aggregated.providers_available,
        provider_errors=aggregated.provider_errors,
    )


def _other(named: _Provider) -> list[_Provider]:
    return [p for p in PROVIDERS if p is not named]


def keyless_visual_search(image_path: str, limit: int = 10) -> SearchResponse:
    """Keyless Yandex CBIR reverse-image search (no API key needed).

    Used as a fallback when no keyed provider is configured (or all keyed
    providers return nothing). ``image_path`` may be a local file (published
    to a temporary public host) or an already-public HTTP(S) URL. Seeded by
    the image itself, so it does *not* require a textual ``hint`` — unlike
    the text-based social fallback.

    Returns a shaped :class:`SearchResponse`; never raises.
    """
    try:
        from backend.search.yandex import YandexCbirError, yandex_reverse_search

        public_url = ""
        if image_path.startswith(("http://", "https://")):
            public_url = image_path
        else:
            public_url = host_image(image_path)
        if not public_url:
            return SearchResponse(
                provider="yandex_cbir",
                error="Could not publish image to a public URL for Yandex CBIR",
            )
        results = yandex_reverse_search(public_url)
        if not results:
            return SearchResponse(
                provider="yandex_cbir",
                error="Yandex CBIR returned no matches",
            )
        return SearchResponse(
            results=results[:limit],
            provider="yandex_cbir",
            providers_used=["yandex_cbir"],
            providers_available=1,
        )
    except YandexCbirError as exc:
        return SearchResponse(provider="yandex_cbir", error=str(exc))
    except Exception as exc:  # noqa: BLE001
        return SearchResponse(provider="yandex_cbir", error=str(exc))