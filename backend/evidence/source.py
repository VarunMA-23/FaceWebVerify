"""Source URL classification and canonicalization."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse, urlunparse

from backend.crawler.parser import infer_platform
from backend.evidence.models import SourceInfo

SOCIAL_PLATFORMS = frozenset(
    {
        "instagram",
        "twitter",
        "x",
        "facebook",
        "tiktok",
        "reddit",
        "linkedin",
        "youtube",
        "pinterest",
        "tumblr",
        "flickr",
    }
)

# Known social domains → platform (for classify when infer_platform returns web)
SOCIAL_DOMAIN_MAP = {
    "instagram.com": "instagram",
    "twitter.com": "x",
    "x.com": "x",
    "facebook.com": "facebook",
    "fb.com": "facebook",
    "tiktok.com": "tiktok",
    "reddit.com": "reddit",
    "linkedin.com": "linkedin",
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "pinterest.com": "pinterest",
    "tumblr.com": "tumblr",
    "flickr.com": "flickr",
}

WIKI_DOMAINS = ("wikipedia.org", "wikimedia.org", "wikidata.org")

REFERENCE_DOMAINS = (
    "britannica.com",
    "biography.com",
    "imdb.com",
    "news.",
    "bbc.com",
    "cnn.com",
    "nytimes.com",
    "theguardian.com",
)

TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "fbclid",
        "gclid",
        "ref",
        "ref_src",
        "igshid",
    }
)


def extract_domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:  # noqa: BLE001
        return ""


def _domain_matches(domain: str, candidates) -> bool:
    """Exact / subdomain match (never substring), so a crafty lookalike host
    like ``notinstagram.com`` or ``foobbc.com`` can never be misclassified."""
    return any(domain == d or domain.endswith("." + d) for d in candidates)


def canonicalize_url(url: str) -> str:
    """Normalize URL for deduplication (strip tracking params, trailing slash)."""
    if not url:
        return ""
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return url.strip()
    query = parse_qs(parsed.query, keep_blank_values=False)
    filtered = [
        f"{k}={v[0]}"
        for k, v in sorted(query.items())
        if k.lower() not in TRACKING_PARAMS
    ]
    path = parsed.path.rstrip("/") or "/"
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return urlunparse(
        (parsed.scheme.lower(), netloc, path, "", "&".join(filtered), "")
    )


def _reference_matches(domain: str) -> bool:
    for d in REFERENCE_DOMAINS:
        if d.endswith("."):  # host-prefix marker (e.g. "news.")
            if domain.startswith(d):
                return True
        elif domain == d or domain.endswith("." + d):
            return True
    return False


def classify_source_type(url: str, platform: str) -> str:
    """Classify source as social, wiki, reference, web, or search_thumbnail."""
    low = url.lower()
    domain = extract_domain(url)
    plat = normalize_platform(platform, url)
    if plat in SOCIAL_PLATFORMS or _domain_matches(domain, SOCIAL_DOMAIN_MAP):
        return "social"
    if _domain_matches(domain, WIKI_DOMAINS):
        return "wiki"
    if _reference_matches(domain):
        return "reference"
    return "web"


def normalize_platform(platform: str, url: str = "") -> str:
    """Normalize platform slug (e.g. twitter → x)."""
    p = (platform or "").lower().strip()
    if p == "twitter":
        return "x"
    if p == "web" and url:
        domain = extract_domain(url)
        return _lookup_social_platform(domain) or "web"
    return p or "web"


def _lookup_social_platform(domain: str) -> str:
    """Return the social platform slug for a domain (exact/subdomain match)."""
    for dom, name in SOCIAL_DOMAIN_MAP.items():
        if domain == dom or domain.endswith("." + dom):
            return name
    return ""


def platform_display_name(platform: str) -> str:
    names = {
        "instagram": "Instagram",
        "x": "X",
        "twitter": "X",
        "facebook": "Facebook",
        "tiktok": "TikTok",
        "reddit": "Reddit",
        "linkedin": "LinkedIn",
        "youtube": "YouTube",
        "pinterest": "Pinterest",
        "tumblr": "Tumblr",
        "flickr": "Flickr",
        "web": "Web",
    }
    return names.get(normalize_platform(platform), platform.title() if platform else "Unknown")


def extract_social_handle(url: str, platform: str) -> str | None:
    """Extract @handle from URL when path structure allows — never invent."""
    plat = normalize_platform(platform, url)
    if plat not in SOCIAL_PLATFORMS:
        return None
    try:
        parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
    except Exception:  # noqa: BLE001
        return None
    if not parts:
        return None

    reserved = frozenset(
        {
            "p", "reel", "tv", "stories", "explore", "accounts", "login",
            "i", "intent", "search", "hashtag", "watch", "shorts", "channel",
            "r", "user", "posts", "photo", "photos", "groups", "events",
        }
    )

    if plat == "instagram":
        if parts[0] in ("p", "reel", "tv", "stories"):
            return None
        if parts[0] not in reserved:
            return f"@{parts[0]}"
    elif plat == "x":
        if parts[0] not in reserved:
            return f"@{parts[0]}"
    elif plat == "tiktok":
        if parts[0].startswith("@") and len(parts[0]) > 1:
            return parts[0]
        if parts[0] not in reserved and not parts[0].startswith("video"):
            return f"@{parts[0].lstrip('@')}"
    elif plat == "reddit":
        if parts[0] == "u" and len(parts) > 1:
            return f"u/{parts[1]}"
        if parts[0] == "user" and len(parts) > 1:
            return f"u/{parts[1]}"
    elif plat == "youtube":
        if parts[0] in ("@", "c", "channel") and len(parts) > 1:
            return parts[1] if parts[0] != "@" else f"@{parts[1]}"
        if parts[0].startswith("@"):
            return parts[0]
    elif plat in ("facebook", "linkedin", "pinterest", "tumblr", "flickr"):
        if parts[0] not in reserved:
            return parts[0]
    return None


def evidence_tier_label(evidence_tier: str, source_type: str = "web") -> str:
    """Human-readable evidence tier — truthful, not inflated."""
    if source_type == "social" and evidence_tier == "verified":
        return "Verified Social Source"
    if evidence_tier == "verified":
        return "Verified Source"
    if source_type == "social" and evidence_tier == "thumbnail":
        return "Social Result — Thumbnail Only"
    if evidence_tier == "thumbnail":
        return "Thumbnail Match"
    return "Unverified"


def is_social_source(source_type: str, platform: str) -> bool:
    return source_type == "social" and normalize_platform(platform) in SOCIAL_PLATFORMS


def build_source_info(
    url: str,
    *,
    page_retrieved: bool = False,
    image_retrieved: bool = False,
    platform: str | None = None,
) -> SourceInfo:
    plat = normalize_platform(platform or infer_platform(url), url)
    source_type = classify_source_type(url, plat)
    return SourceInfo(
        source_url=url,
        canonical_url=canonicalize_url(url),
        domain=extract_domain(url),
        platform=plat,
        source_type=source_type,
        page_retrieved=page_retrieved,
        image_retrieved=image_retrieved,
    )
