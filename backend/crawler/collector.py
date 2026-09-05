"""Candidate collection: fetch pages, download images, extract metadata."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

from backend.crawler.parser import ParsedPage, parse_html

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

#: Maximum redirects to follow within a single fetch.
MAX_REDIRECTS = 5
#: Maximum size of any single resource we will download.
MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
#: Content types we are willing to treat as an HTML page.
_HTML_TYPES = ("text/html", "application/xhtml+xml")
_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")
_IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif", "image/avif")


def validate_url(url: str) -> bool:
    """Validate a URL before fetching (scheme + host sanity)."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    if not parsed.netloc:
        return False
    if " " in parsed.netloc or any(ch in parsed.netloc for ch in "<>\"{}|\\^`"):
        return False
    return True


@dataclass
class CandidateContent:
    """Material from a collected candidate page."""

    source_url: str
    image_url: str = ""
    caption: str = ""
    title: str = ""
    platform: str = ""
    page_text: str = ""
    local_image_path: str = ""
    keywords: list[str] = field(default_factory=list)
    fetched_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class Collector:
    """Fetches candidate pages and downloads images to a temp dir.

    Redirections are followed only within the same origin and up to a bounded
    number of hops, then the resolved page is parsed.
    """

    def __init__(self, session: requests.Session | None = None, timeout: int = 15) -> None:
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._tmpdir: str | None = None
        self._lock = threading.Lock()

    def _storage(self) -> str:
        with self._lock:
            if self._tmpdir is None:
                self._tmpdir = tempfile.mkdtemp(prefix="hhgoa_")
            return self._tmpdir

    def cleanup(self) -> None:
        with self._lock:
            if self._tmpdir and os.path.isdir(self._tmpdir):
                shutil.rmtree(self._tmpdir, ignore_errors=True)
                self._tmpdir = None

    def __enter__(self) -> "Collector":
        return self

    def __exit__(self, *exc: object) -> None:
        self.cleanup()

    # ---------------------------------------------------------------- fetch
    def fetch_page(self, url: str) -> ParsedPage | None:
        """GET a page, following safe redirects, and parse it as HTML.

        Returns None when the resource is not an HTML page, when the fetch
        fails, or when redirected to a different origin.
        """
        if not validate_url(url):
            return None

        current = url
        for _ in range(MAX_REDIRECTS + 1):
            try:
                resp = self.session.get(
                    current, timeout=self.timeout, allow_redirects=False, stream=True
                )
            except requests.RequestException:
                return None

            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location")
                resp.close()
                if not location:
                    return None
                next_url = (
                    location
                    if location.startswith(("http://", "https://"))
                    else urljoin_abs(current, location)
                )
                if not validate_url(next_url):
                    return None
                if urlparse(current).netloc != urlparse(next_url).netloc:
                    # Refuse to follow off-origin redirects.
                    return None
                current = next_url
                continue

            if resp.status_code != 200:
                resp.close()
                return None

            content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if not any(t in content_type for t in _HTML_TYPES):
                resp.close()
                return None

            html = resp.content.decode("utf-8", errors="replace")
            resp.close()
            parsed = parse_html(html, current)
            if parsed.title or parsed.images or parsed.text:
                return parsed
            return parsed

        return None

    # ------------------------------------------------------- image download
    def download_image(self, img_url: str, page: ParsedPage | None = None) -> str:
        """Download an image to local temp storage, returning the local path.

        Returns an empty string on any failure (non-image, too-large, timeout).
        """
        if not validate_url(img_url):
            return ""
        storage = self._storage()
        try:
            resp = self.session.get(img_url, timeout=self.timeout, stream=True)
            content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if resp.status_code != 200:
                resp.close()
                return ""
            if content_type and "text/html" in content_type:
                resp.close()
                return ""
            # Cap download size.
            length = resp.headers.get("Content-Length")
            try:
                if length is not None and int(length) > MAX_DOWNLOAD_BYTES:
                    resp.close()
                    return ""
            except ValueError:
                pass  # malformed Content-Length -> rely on the streaming cap below

            chunks = []
            total = 0
            for chunk in resp.iter_content(chunk_size=65536):
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    resp.close()
                    return ""
                chunks.append(chunk)
            resp.close()
            data = b"".join(chunks)
            if not data:
                return ""

            ext = _guess_ext(content_type, img_url)
            digest = hashlib.sha256(data).hexdigest()[:16]
            local_path = os.path.join(storage, f"{digest}{ext}")
            # Write atomically so concurrent threads never observe a
            # partially-written image (digest names are content-addressed, so
            # two threads downloading the same bytes produce the same file).
            if not os.path.exists(local_path):
                tmp = os.path.join(storage, f".{digest}{ext}.part")
                with open(tmp, "wb") as fh:
                    fh.write(data)
                try:
                    os.replace(tmp, local_path)
                except FileNotFoundError:
                    # Another thread may have written the same content-addressed file.
                    if not os.path.exists(local_path):
                        raise
            return local_path
        except requests.RequestException:
            return ""

    # ------------------------------------------------------------ collect
    def collect(self, source_url: str, image_url: str = "") -> CandidateContent | None:
        """Collect a single candidate from a search result.

        Fetches the page, picks its best image, downloads it locally. If the
        page cannot be parsed, falls back to the search-engine-provided image
        URL directly.
        """
        page = self.fetch_page(source_url)
        if page is None:
            if image_url:
                local = self.download_image(image_url)
                return CandidateContent(
                    source_url=source_url,
                    image_url=image_url,
                    local_image_path=local,
                    platform="web",
                )
            return None

        target = image_url or page.primary_image or ""
        local = self.download_image(target) if target else ""
        return CandidateContent(
            source_url=page.url,
            image_url=target,
            caption=page.caption,
            title=page.title,
            platform=page.platform,
            page_text=page.text,
            keywords=page.keywords,
            local_image_path=local,
        )


def collect_candidate(search_result_url: str, image_url: str = "") -> CandidateContent | None:
    """Convenience wrapper using a shared default collector."""
    with Collector() as col:
        return col.collect(search_result_url, image_url)


def urljoin_abs(base: str, url: str) -> str:
    """Join a possibly-relative URL onto a base, returning an absolute URL."""
    from urllib.parse import urljoin as _u

    return _u(base, url)


def _guess_ext(content_type: str, url: str) -> str:
    if any(t in content_type for t in ("image/png",)):
        return ".png"
    if "image/webp" in content_type:
        return ".webp"
    if "image/gif" in content_type:
        return ".gif"
    if "image/avif" in content_type:
        return ".avif"
    low = url.lower()
    for ext in _IMAGE_EXT:
        if low.endswith(ext):
            return ext
    return ".jpg"