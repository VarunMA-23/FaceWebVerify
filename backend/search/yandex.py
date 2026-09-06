"""Keyless Yandex CBIR reverse-image search.

A genuine, on-demand visual search that needs no API key. It queries the
public Yandex reverse-image index by the image's public URL and parses the
live ``cbir_page=sites`` result set ("sites where this picture appears").

Fragile by nature (Yandex may reorganise its HTML), so every parser step
fails soft: any malformed segment is skipped, and a page that yields no
CBIR result set raises a descriptive :class:`YandexCbirError` that the
caller maps to an empty, shaped :class:`SearchResponse`.
"""

from __future__ import annotations

import html as _html
import json as _json
import re
import urllib.parse

import requests
from bs4 import BeautifulSoup  # noqa: F401  # kept for import parity / plugins

from backend.search.search_models import SearchResult

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_SOCIAL_DOMAINS = {
    "instagram.com", "facebook.com", "fb.watch", "twitter.com", "x.com",
    "tiktok.com", "youtube.com", "youtu.be", "linkedin.com", "pinterest.com",
    "threads.com", "threads.net", "reddit.com", "vimeo.com", "dailymotion.com",
    "twitch.tv", "snapchat.com", "vk.com", "ok.ru", "sotwe.com", "weibo.com",
    "bluesky", "mastodon", "tumblr.com", "flickr.com",
}


class YandexCbirError(RuntimeError):
    """Raised when Yandex does not return a usable CBIR result set."""


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://yandex.com/",
    })
    return s


def _yandex_search_page(s: requests.Session, image_url: str, timeout: int = 40) -> str:
    params = {"rpt": "imageview", "url": image_url}
    r = s.get("https://yandex.com/images/search", params=params, timeout=timeout)
    r.raise_for_status()
    return r.text


def _extract_sites_url(search_html: str) -> str | None:
    u = search_html.replace("&quot;", '"').replace("&amp;", "&")
    m = re.search(
        r'"url":"(/images/search\?rpt=imageview&url=https?[^"]+?&cbir_id=[^"]+?&cbir_page=sites)"',
        u,
    )
    if not m:
        m = re.search(
            r"(/images/search\?rpt=imageview&url=\S+?&cbir_id=\S+?&cbir_page=sites)",
            u,
        )
    if not m:
        return None
    return "https://yandex.com" + _html.unescape(m.group(1)).rstrip('"')


def _parse_sites(sites_html: str) -> list[dict]:
    u = sites_html.replace("&quot;", '"').replace("&amp;", "&")
    items: list[dict] = []
    for seg in u.split('{"title":"')[1:]:
        seg = seg[:4000]
        m = re.match(
            r'(?P<title>(?:[^"\\]|\\.)*)","description":"'
            r'(?P<desc>(?:[^"\\]|\\.)*)","url":"(?P<url>https?://[^"]+)",'
            r'"domain":"(?P<domain>[^"]+)"',
            seg,
        )
        if not m:
            continue
        domain = m.group("domain")
        if any(c in domain for c in (" ", "{", "}", "<", "\\")):
            continue
        try:
            title = _json.loads(f'"{m.group("title")}"')
        except Exception:  # noqa: BLE001
            title = m.group("title")
        title = _html.unescape(title or "")
        img = ""
        mi = re.search(r'"originalImage":\{"url":"([^"]+)"', seg[:2500])
        if mi:
            img = _html.unescape(mi.group(1))
        url = re.sub(r"[?&]utm_medium=.*$", "", m.group("url"))
        items.append(
            {
                "title": title,
                "page_url": _html.unescape(url),
                "domain": domain,
                "image_url": img,
            }
        )
    seen: set[str] = set()
    uniq: list[dict] = []
    for it in items:
        if it["page_url"] not in seen:
            seen.add(it["page_url"])
            uniq.append(it)
    return uniq


def _is_social(page_url: str) -> bool:
    host = (urllib.parse.urlparse(page_url).netloc or "").lower()
    return any(s in host for s in _SOCIAL_DOMAINS)


def yandex_reverse_search(
    image_url: str,
    timeout: int = 60,
) -> list[SearchResult]:
    """Run a live Yandex CBIR reverse search against ``image_url``.

    ``image_url`` must be a public HTTP(S) URL (Yandex fetches the bytes
    itself). Returns de-duplicated :class:`SearchResult` objects; raises
    :class:`YandexCbirError` when no CBIR result set is available.
    """
    s = _session()
    search_html = _yandex_search_page(s, image_url, timeout=timeout)
    sites_url = _extract_sites_url(search_html)
    if not sites_url:
        raise YandexCbirError(
            "yandex returned no CBIR result set "
            "(may be rate-limited; retry later)"
        )
    r = s.get(sites_url, timeout=timeout)
    r.raise_for_status()
    parsed = _parse_sites(r.text)
    results = [
        SearchResult(
            url=it["page_url"],
            image_url=it["image_url"],
            title=it["title"],
            source="yandex_cbir",
        )
        for it in parsed
    ]
    results.sort(key=lambda sr: (not _is_social(sr.url),))
    return results
