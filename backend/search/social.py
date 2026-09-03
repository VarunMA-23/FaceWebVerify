"""Keyless live search across public social APIs.

Fallback provider for when no API keys are configured (or all keyed
providers fail).  Every request below hits a live public endpoint with
no auth; results are whatever those APIs return at run time.

A text ``hint`` seeds the query (a face alone carries no searchable text),
and the face-comparison stage is what actually decides whether a returned
post matches.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import requests

from backend.search.search_models import SearchResponse, SearchResult

# Bluesky public AppView — no auth required
_BSKY = "https://public.api.bsky.app/xrpc"

# Mastodon instances to try (public, no auth)
_MASTODON_INSTANCES = ("mastodon.social", "mastodon.online", "fosstodon.org")

# Domains recognised as social media
_SOCIAL_DOMAINS = {
    "instagram.com",
    "x.com",
    "twitter.com",
    "facebook.com",
    "linkedin.com",
    "bsky.app",
    "reddit.com",
    "threads.net",
    "tiktok.com",
    "youtube.com",
    "mastodon.social",
    "mastodon.online",
    "fosstodon.org",
    "warpcast.com",
    "farcaster.xyz",
    "t.me",
    "vk.com",
    "weibo.com",
    "pinterest.com",
    "flickr.com",
    "tumblr.com",
}


def _is_social(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return any(host == d or host.endswith("." + d) for d in _SOCIAL_DOMAINS)


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", " ", s or "").strip()


def _bsky_post_url(handle: str, uri: str) -> str:
    rkey = uri.rsplit("/", 1)[-1]
    return f"https://bsky.app/profile/{handle}/post/{rkey}"


def _bsky_images(post: dict) -> list[str]:
    embed = post.get("embed") or {}
    out: list[str] = []
    for imgs in (embed.get("images"), ((embed.get("media") or {}).get("images"))):
        for im in imgs or []:
            url = im.get("fullsize") or im.get("thumb")
            if url:
                out.append(url)
    return out


# -------------------------------------------------------------------
# Bluesky
# -------------------------------------------------------------------

def _search_bluesky(hint: str, limit: int) -> tuple[list[SearchResult], dict]:
    """Query Bluesky public AppView for actors + posts matching *hint*."""
    results: list[SearchResult] = []
    stats: dict = {"actors": 0, "posts": 0}

    # 1. Search actors by display name / handle
    try:
        resp = requests.get(
            f"{_BSKY}/app.bsky.actor.searchActors",
            params={"q": hint, "limit": 8},
            timeout=15,
        )
        resp.raise_for_status()
        actors = resp.json().get("actors", [])
    except Exception:  # noqa: BLE001
        actors = []
    stats["actors"] = len(actors)

    for actor in actors[:5]:
        handle = actor.get("handle", "")
        if not handle:
            continue
        # Profile page itself
        if actor.get("avatar"):
            results.append(
                SearchResult(
                    url=f"https://bsky.app/profile/{handle}",
                    image_url=actor["avatar"],
                    title=actor.get("displayName") or handle,
                    source="bluesky_public_api",
                )
            )
        # Their media posts
        try:
            feed_resp = requests.get(
                f"{_BSKY}/app.bsky.feed.getAuthorFeed",
                params={"actor": handle, "limit": 40, "filter": "posts_with_media"},
                timeout=15,
            )
            feed_resp.raise_for_status()
            feed = feed_resp.json().get("feed", [])
        except Exception:  # noqa: BLE001
            continue
        for item in feed:
            post = item.get("post") or {}
            imgs = _bsky_images(post)
            if not imgs:
                continue
            rec = post.get("record") or {}
            results.append(
                SearchResult(
                    url=_bsky_post_url(handle, post.get("uri", "")),
                    image_url=imgs[0],
                    title=(rec.get("text") or "")[:200],
                    source="bluesky_public_api",
                )
            )

    # 2. Direct post search
    try:
        posts_resp = requests.get(
            f"{_BSKY}/app.bsky.feed.searchPosts",
            params={"q": hint, "limit": 40},
            timeout=15,
        )
        posts_resp.raise_for_status()
        posts = posts_resp.json().get("posts", [])
    except Exception:  # noqa: BLE001
        posts = []
    stats["posts"] = len(posts)

    for post in posts:
        imgs = _bsky_images(post)
        if not imgs:
            continue
        handle = (post.get("author") or {}).get("handle", "")
        rec = post.get("record") or {}
        results.append(
            SearchResult(
                url=_bsky_post_url(handle, post.get("uri", "")),
                image_url=imgs[0],
                title=(rec.get("text") or "")[:200],
                source="bluesky_public_api",
            )
        )

    return results[:limit], stats


# -------------------------------------------------------------------
# Mastodon
# -------------------------------------------------------------------

def _search_mastodon(hint: str, limit: int) -> tuple[list[SearchResult], dict]:
    """Query public Mastodon endpoints for accounts + statuses matching *hint*."""
    results: list[SearchResult] = []
    stats: dict = {"accounts": 0, "statuses": 0}
    slug = re.sub(r"[^a-z0-9_]", "", hint.lower().replace(" ", ""))

    for inst in _MASTODON_INSTANCES:
        # Account lookup
        acct = None
        if slug:
            try:
                acct_resp = requests.get(
                    f"https://{inst}/api/v1/accounts/lookup",
                    params={"acct": slug},
                    timeout=10,
                )
                acct_resp.raise_for_status()
                acct = acct_resp.json()
            except Exception:  # noqa: BLE001
                acct = None
        if acct and acct.get("id"):
            stats["accounts"] += 1
            if acct.get("avatar"):
                results.append(
                    SearchResult(
                        url=acct.get("url") or f"https://{inst}/@{slug}",
                        image_url=acct["avatar"],
                        title=acct.get("display_name", ""),
                        source="mastodon_public_api",
                    )
                )
            # Account's media statuses
            try:
                st_resp = requests.get(
                    f"https://{inst}/api/v1/accounts/{acct['id']}/statuses",
                    params={"limit": 40, "only_media": "true", "exclude_reblogs": "true"},
                    timeout=10,
                )
                st_resp.raise_for_status()
                statuses = st_resp.json()
            except Exception:  # noqa: BLE001
                statuses = []
            for st in statuses:
                imgs = [
                    m.get("url")
                    for m in st.get("media_attachments", [])
                    if m.get("type") == "image" and m.get("url")
                ]
                if not imgs:
                    continue
                stats["statuses"] += 1
                results.append(
                    SearchResult(
                        url=st.get("url") or st.get("uri", ""),
                        image_url=imgs[0],
                        title=_strip_html(st.get("content", ""))[:200],
                        source="mastodon_public_api",
                    )
                )
        if len(results) >= limit:
            break

    # Fallback: public timeline (last resort)
    if len(results) < limit:
        try:
            tl_resp = requests.get(
                f"https://{_MASTODON_INSTANCES[0]}/api/v1/timelines/public",
                params={"limit": 40, "only_media": "true"},
                timeout=10,
            )
            tl_resp.raise_for_status()
            timeline = tl_resp.json()
        except Exception:  # noqa: BLE001
            timeline = []
        for st in timeline:
            imgs = [
                m.get("url")
                for m in st.get("media_attachments", [])
                if m.get("type") == "image" and m.get("url")
            ]
            if not imgs:
                continue
            results.append(
                SearchResult(
                    url=st.get("url") or st.get("uri", ""),
                    image_url=imgs[0],
                    title=_strip_html(st.get("content", ""))[:200],
                    source="mastodon_public_api",
                )
            )

    return results[:limit], stats


# -------------------------------------------------------------------
# Reddit
# -------------------------------------------------------------------

def _search_reddit(hint: str, limit: int) -> tuple[list[SearchResult], dict]:
    """Query Reddit's public JSON search for image posts matching *hint*."""
    try:
        resp = requests.get(
            "https://www.reddit.com/search.json",
            params={"q": hint, "limit": 40, "type": "link"},
            headers={"User-Agent": "faceproof-pipeline/1.0"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return [], {"error": str(exc)[:120]}

    children = (data.get("data") or {}).get("children", [])
    results: list[SearchResult] = []

    for ch in children:
        d = ch.get("data") or {}
        imgs: list[str] = []
        if d.get("post_hint") == "image" and d.get("url_overridden_by_dest"):
            imgs.append(d["url_overridden_by_dest"])
        for prev in ((d.get("preview") or {}).get("images") or []):
            src = (prev.get("source") or {}).get("url")
            if src:
                imgs.append(src.replace("&amp;", "&"))
        if not imgs:
            continue
        results.append(
            SearchResult(
                url="https://www.reddit.com" + d.get("permalink", ""),
                image_url=imgs[0],
                title=d.get("title", "")[:200],
                source="reddit_public_api",
            )
        )

    return results[:limit], {"results": len(children)}


# -------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------

def social_search(
    hint: str,
    max_results: int = 60,
) -> SearchResponse:
    """Run all keyless providers and return merged, deduplicated results.

    Returns a :class:`SearchResponse` with ``provider="keyless_social"``.
    """
    if not hint:
        return SearchResponse(
            provider="keyless_social",
            error="Keyless social search requires a --hint (a face carries no searchable text).",
        )

    per_source = max(10, max_results // 2)
    merged: list[SearchResult] = []
    seen: set[str] = set()
    provider_errors: dict[str, str] = {}
    sources_used: list[str] = []

    for name, fn in (
        ("bluesky", _search_bluesky),
        ("mastodon", _search_mastodon),
        ("reddit", _search_reddit),
    ):
        try:
            source_results, stats = fn(hint, per_source)
        except Exception as exc:  # noqa: BLE001
            provider_errors[name] = str(exc)[:160]
            continue
        if stats.get("error"):
            provider_errors[name] = stats["error"]
            continue
        sources_used.append(name)
        for sr in source_results:
            canonical = sr.url.rstrip("/")
            if canonical and canonical not in seen:
                seen.add(canonical)
                merged.append(sr)

    # Sort: social posts first, then everything else
    merged.sort(key=lambda r: (not _is_social(r.url),))

    if not merged:
        err_detail = "; ".join(f"{k}: {v}" for k, v in provider_errors.items()) or "no results"
        return SearchResponse(
            provider="keyless_social",
            error=f"No social results found ({err_detail})",
            provider_errors=provider_errors,
        )

    return SearchResponse(
        results=merged[:max_results],
        provider="keyless_social",
        providers_used=sources_used,
        providers_available=len(sources_used),
        provider_errors=provider_errors,
    )
