"""HTML parsing: extract title, images, text, caption and platform metadata.

Aim is best-effort extraction that works across modern social/blog pages:
OpenGraph + Twitter Card meta tags, schema.org, and sensible HTML fallbacks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

from bs4 import BeautifulSoup

# Common favicon / ornamental image patterns to filter out of content picks.
_ICON_HINTS = re.compile(
    r"(favicon|apple-touch|icon|logo|sprite|banner|avatar|profile|"
    r"placeholder|1x1|pixel|tracking|\.svg|\.ico|data:image)",
    re.IGNORECASE,
)
_TRACKING_EXT = re.compile(r"\.(svg|ico)$", re.IGNORECASE)
_SOCIAL_IMAGE_EXT = re.compile(r"\.(jpg|jpeg|png|webp|gif|avif)$", re.IGNORECASE)


@dataclass
class ParsedPage:
    """Structured content extracted from a candidate page."""

    url: str
    title: str = ""
    caption: str = ""
    images: list[str] = field(default_factory=list)
    #: URLs with score + dimensions, used to rank the best content image.
    ranked_images: list[tuple[str, float, int, int]] = field(default_factory=list)
    text: str = ""
    platform: str = ""
    keywords: list[str] = field(default_factory=list)

    @property
    def primary_image(self) -> str | None:
        """Best content image: og:image scored highest, ignoring icons."""
        for _url, _score, _w, _h in self.ranked_images:
            return _url
        # Fallback to first non-icon image.
        for img in self.images:
            if not _ICON_HINTS.search(img):
                return img
        return self.images[0] if self.images else None


_PLATFORMS = {
    "instagram.com": "instagram",
    "twitter.com": "twitter",
    "x.com": "twitter",
    "facebook.com": "facebook",
    "fb.watch": "facebook",
    "tiktok.com": "tiktok",
    "linkedin.com": "linkedin",
    "pinterest.com": "pinterest",
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "reddit.com": "reddit",
    "flickr.com": "flickr",
    "tumblr.com": "tumblr",
}


def infer_platform(url: str) -> str:
    low = url.lower()
    for domain, name in _PLATFORMS.items():
        if domain in low:
            return name
    return "web"


def _meta_content(soup: BeautifulSoup, *selectors: dict) -> str:
    """Return the first non-empty content of any given meta selector."""
    for sel in selectors:
        tag = soup.find("meta", attrs=sel)
        if tag is None:
            continue
        val = tag.get("content") or tag.get("value")
        if val and str(val).strip():
            return str(val).strip()
    return ""


def _extract_title(soup: BeautifulSoup) -> str:
    og = _meta_content(soup, {"property": "og:title"}, {"name": "twitter:title"})
    if og:
        return og
    if soup.title and soup.title.string:
        t = soup.title.string.strip()
        if t:
            return t
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)
    return ""


def _extract_caption(soup: BeautifulSoup) -> str:
    for meta in (
        {"property": "og:description"},
        {"name": "description"},
        {"name": "twitter:description"},
        {"property": "og:title"},
    ):
        val = _meta_content(soup, meta)
        if val:
            return val[:500]
    return ""


def _extract_keywords(soup: BeautifulSoup) -> list[str]:
    raw = _meta_content(
        soup, {"name": "keywords"}, {"name": "news_keywords"}, {"property": "article:tag"}
    )
    if not raw:
        return []
    parts = [p.strip() for p in re.split(r"[,\[\]]", raw) if p.strip()]
    return parts[:20]


def _looks_like_content_image(url: str, img_tag) -> bool:
    """Filter ornamental/technical images from content ranking."""
    if _TRACKING_EXT.search(url):
        return False
    if _ICON_HINTS.search(url):
        return False
    alt = (img_tag.get("alt") or "") if img_tag else ""
    cls = " ".join(img_tag.get("class", [])) if img_tag else ""
    for hint in ("avatar", "logo", "icon", "profile", "placeholder"):
        if hint in alt.lower() or hint in cls.lower():
            return False
    return True


def _img_dims(tag) -> tuple[int, int]:
    """Best-effort width/height from attributes."""
    w = tag.get("width") or tag.get("data-width")
    h = tag.get("height") or tag.get("data-height")
    try:
        w = int(w)
    except (TypeError, ValueError):
        w = 0
    try:
        h = int(h)
    except (TypeError, ValueError):
        h = 0
    return w, h


def parse_html(html: str, base_url: str) -> ParsedPage:
    """Parse raw HTML into a ParsedPage with normalized absolute image URLs."""
    soup = BeautifulSoup(html, "html.parser")

    title = _extract_title(soup)
    caption = _extract_caption(soup)
    keywords = _extract_keywords(soup)

    # Gather candidate image refs from meta + img tags in document order.
    candidates: list[tuple[str, dict, float]] = []  # (url, tag, base_score)
    seen_urls: set[str] = set()

    # OpenGraph and Twitter images are the strongest signal.
    og_image = _meta_content(soup, {"property": "og:image"})
    twitter_image = _meta_content(soup, {"name": "twitter:image"})

    for meta_url in (og_image, twitter_image):
        if not meta_url or meta_url.startswith("data:"):
            continue
        url = urljoin(base_url, meta_url)
        if url.startswith(("http://", "https://")) and url not in seen_urls:
            seen_urls.add(url)
            candidates.append((url, {}, 100.0))

    for tag in soup.find_all("img"):
        src = tag.get("src") or tag.get("data-src") or tag.get("data-original")
        if not src:
            continue
        url = urljoin(base_url, src)
        if not url.startswith(("http://", "https://")):
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        score = 50.0
        if _SOCIAL_IMAGE_EXT.search(url):
            score += 10.0
        candidates.append((url, tag, score))

    ranked: list[tuple[str, float, int, int]] = []
    for img_url, tag, base_score in candidates:
        if not _looks_like_content_image(img_url, tag):
            continue
        w, h = _img_dims(tag)
        score = base_score
        if w and h:
            score += min(100.0, (w * h) / 100_000.0)  # bigger images rank higher
        ranked.append((img_url, round(score, 2), w, h))

    # Sort by score descending; stable by original order.
    ranked.sort(key=lambda r: (-r[1],))

    images = [u for u, _s, _w, _h in ranked]
    if not images:
        # Ultra-fallback: any absolute image not obviously an icon.
        for img_url, _tag, _score in candidates:
            if img_url not in images:
                images.append(img_url)

    text = soup.get_text(" ", strip=True)
    text = " ".join(text.split())
    if len(text) > 10000:
        text = text[:10000]

    platform = infer_platform(base_url)
    return ParsedPage(
        url=base_url,
        title=title,
        caption=caption,
        images=images[:10],
        ranked_images=ranked[:10],
        text=text,
        platform=platform,
        keywords=keywords,
    )