"""Tests for candidate collection + face matching (Modules 4 + 5).

Crawler tests run against a local mock server so they are deterministic and
never depend on the live internet.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from mock_server import ServerScope  # noqa: E402

from backend.crawler.collector import (  # noqa: E402
    Collector,
    MAX_REDIRECTS,
    validate_url,
)
from backend.crawler.parser import infer_platform, parse_html  # noqa: E402
from backend.face.embedder import embed_face  # noqa: E402
from backend.face.matcher import (  # noqa: E402
    SIMILARITY_THRESHOLD,
    cosine_similarity,
    match_embeddings,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
LENA = os.path.join(FIXTURES, "lena.jpg")

# ---------------------------------------------------------------- URL/utils


def test_validate_url():
    assert validate_url("https://example.com/post/1")
    assert validate_url("http://example.com")
    assert validate_url("https://example.com:8080/a?b=c#d")
    assert not validate_url("ftp://example.com")
    assert not validate_url("javascript:alert(1)")
    assert not validate_url("not a url")
    assert not validate_url("http://")
    assert not validate_url("https://exa mple.com")


def test_infer_platform():
    assert infer_platform("https://www.instagram.com/p/abc/") == "instagram"
    assert infer_platform("https://twitter.com/user/status/1") == "twitter"
    assert infer_platform("https://x.com/u/status/2") == "twitter"
    assert infer_platform("https://www.facebook.com/x") == "facebook"
    assert infer_platform("https://example.com/somewhere") == "web"


# ----------------------------------------------------------------- parser


def test_parse_html_extracts_fields():
    html = """
    <html><head><title>My Post</title>
    <meta property="og:description" content="Look at this!">
    <meta property="og:image" content="/static/img1.jpg">
    </head><body>
    <img src="http://cdn.example.com/logo.png">
    <p>Hello <b>world</b></p>
    </body></html>
    """
    page = parse_html(html, "https://www.instagram.com/p/abc/")
    assert page.title == "My Post"
    assert page.caption == "Look at this!"
    assert "https://www.instagram.com/static/img1.jpg" in page.images
    assert page.platform == "instagram"
    assert "Hello world" in page.text


def test_parse_og_image_wins_over_icon():
    """og:image is ranked above favicon/logo/icon images."""
    html = """
    <meta property="og:image" content="https://cdn.example/img/real.jpg">
    <img src="https://cdn.example/favicon.ico">
    <img src="https://cdn.example/logo.png">
    <img src="https://img.example/photo1.jpg">
    """
    page = parse_html(html, "https://example.com/post")
    assert page.primary_image == "https://cdn.example/img/real.jpg"


def test_parse_skips_svg_icons_for_primary():
    """SVG/icon-image URLs are excluded from the content image list."""
    html = """
    <img src="https://cdn.example/icons/close.svg">
    <img src="https://img.example/photo1.jpg">
    <img src="https://cdn.example/avatar.png">
    """
    page = parse_html(html, "https://example.com/post")
    assert page.primary_image == "https://img.example/photo1.jpg"
    # Icon/avatar URLs are filtered from the content image list entirely.
    assert any("photo1.jpg" in i for i in page.images)
    assert not any("close.svg" in i for i in page.images)
    assert not any("avatar" in i for i in page.images)


def test_parse_prefers_landscape_large_image():
    """Largest content image ranks highest when no og:image is present."""
    html = """
    <img src="https://img.example/small.jpg" width="100" height="100">
    <img src="https://img.example/big.jpg" width="1200" height="800">
    """
    page = parse_html(html, "https://example.com/post")
    assert page.primary_image == "https://img.example/big.jpg"


def test_parse_resolves_relative_and_protocol_relative_images():
    html = '<img data-src="//cdn.example/img1.png"><img src="/img2.jpg">'
    page = parse_html(html, "https://example.com/post")
    assert "https://cdn.example/img1.png" in page.images
    assert "https://example.com/img2.jpg" in page.images


def test_parse_caption_variants():
    for meta in (
        '<meta property="og:description" content="OG desc">',
        '<meta name="description" content="Name desc">',
        '<meta name="twitter:description" content="TW desc">',
    ):
        page = parse_html(f"<html><head>{meta}</head></html>", "https://example.com/")
        assert page.caption


def test_parse_keywords():
    html = '<meta name="keywords" content="a, b, [c]">'
    page = parse_html(html, "https://example.com/")
    assert "a" in page.keywords and "b" in page.keywords


# ------------------------------------------------------------ mock crawler


def test_collector_fetch_parses_ok_page():
    with ServerScope() as s:
        s.router.add("/post", '<title>Hello</title><img src="/img.jpg"><meta property="og:description" content="cap">')
        col = Collector()
        try:
            page = col.fetch_page(s.url("/post"))
        finally:
            col.cleanup()
        assert page is not None
        assert page.title == "Hello"
        assert page.caption == "cap"


def test_collector_follows_same_origin_redirect():
    with ServerScope() as s:
        s.router.add_redirect("/a", "/b")
        s.router.add("/b", "<title>Landed</title>")
        col = Collector()
        try:
            page = col.fetch_page(s.url("/a"))
        finally:
            col.cleanup()
        assert page is not None
        assert page.title == "Landed"


def test_collector_refuses_off_origin_redirect():
    with ServerScope() as s1, ServerScope() as s2:
        # /a on server1 redirects to server2
        s1.router.add_redirect("/a", s2.url("/b"))
        s2.router.add("/b", "<title>Other</title>")
        col = Collector()
        try:
            page = col.fetch_page(s1.url("/a"))
        finally:
            col.cleanup()
        assert page is None  # off-origin redirect refused


def test_collector_stops_after_max_redirects():
    with ServerScope() as s:
        for i in range(MAX_REDIRECTS + 3):
            s.router.add_redirect(f"/r{i}", f"/r{i+1}")
        col = Collector()
        try:
            page = col.fetch_page(s.url("/r0"))
        finally:
            col.cleanup()
        assert page is None


def test_collector_rejects_non_html_content():
    with ServerScope() as s:
        s.router.add("/file.docx", b"PK\x03\x04binary", content_type="application/msword")
        s.router.add("/image.jpg", b"\xff\xd8\xff", content_type="image/jpeg")
        col = Collector()
        try:
            assert col.fetch_page(s.url("/file.docx")) is None
            assert col.fetch_page(s.url("/image.jpg")) is None
        finally:
            col.cleanup()


def test_collector_returns_none_on_not_found():
    with ServerScope() as s:
        col = Collector()
        try:
            assert col.fetch_page(s.url("/missing")) is None
        finally:
            col.cleanup()


def test_collector_download_image_success():
    with ServerScope() as s:
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        s.router.add("/pic.png", png, content_type="image/png")
        col = Collector()
        try:
            local = col.download_image(s.url("/pic.png"))
            assert local
            with open(local, "rb") as fh:
                assert fh.read() == png
        finally:
            col.cleanup()
            assert col._tmpdir is None


def test_collector_download_rejects_html_and_missing():
    with ServerScope() as s:
        s.router.add("/page.html", "<html></html>", content_type="text/html")
        col = Collector()
        try:
            assert col.download_image(s.url("/page.html")) == ""
            assert col.download_image(s.url("/nope.png")) == ""
        finally:
            col.cleanup()


def test_collector_collect_full_flow():
    """collect() fetches a page, picks its best image and downloads it."""
    with ServerScope() as s:
        img = b"\xff\xd8\xff\xe0" + b"\x00" * 30
        s.router.add("/pic.jpg", img, content_type="image/jpeg")
        s.router.add(
            "/article",
            "<title>Article</title>"
            '<meta property="og:image" content="/pic.jpg">'
            '<meta property="og:description" content="A caption">',
        )
        col = Collector()
        try:
            c = col.collect(s.url("/article"))
            assert c is not None
            assert c.title == "Article"
            assert c.caption == "A caption"
            assert c.image_url == s.url("/pic.jpg")
            assert c.local_image_path
            assert os.path.exists(c.local_image_path)
        finally:
            col.cleanup()


def test_collector_falls_back_to_provided_image_url():
    """If the page is unreachable, use the search-engine image URL."""
    with ServerScope() as s:
        img = b"JPEGDATA"
        s.router.add("/direct.jpg", img, content_type="image/jpeg")
        col = Collector()
        try:
            c = col.collect(s.url("/missing-page"), image_url=s.url("/direct.jpg"))
            assert c is not None
            assert c.source_url == s.url("/missing-page")
            assert c.local_image_path and os.path.exists(c.local_image_path)
        finally:
            col.cleanup()


def test_collect_collect_returns_none_when_nothing_available():
    with ServerScope() as s:
        col = Collector()
        try:
            assert col.collect(s.url("/missing"), image_url="") is None
        finally:
            col.cleanup()


def test_collector_handles_login_required_redirect_to_login():
    """A redirect to a /login page yields a ParsedPage (or None) gracefully."""
    with ServerScope() as s:
        s.router.add("/post", '<title>Log in</title><input type="password">')
        col = Collector()
        try:
            page = col.fetch_page(s.url("/post"))
            # Should not raise; either the login page or None is acceptable.
            assert page is not None
            assert "Log in" in page.title
        finally:
            col.cleanup()


def test_collector_handles_server_errors_gracefully():
    with ServerScope() as s:
        for path, status in (("/500", 500), ("/403", 403), ("/429", 429)):
            s.router.add_status(path, status)
        col = Collector()
        try:
            for path in ("/500", "/403", "/429"):
                assert col.fetch_page(s.url(path)) is None
        finally:
            col.cleanup()


def test_collector_empty_or_blank_page_returns_parsed():
    """A page with no meaningful content should still parse (not crash)."""
    with ServerScope() as s:
        s.router.add("/blank", "<html><head></head><body></body></html>")
        col = Collector()
        try:
            page = col.fetch_page(s.url("/blank"))
            assert page is not None
        finally:
            col.cleanup()


def test_collector_download_caps_oversized_file():
    """Downloads exceeding the size cap must be rejected."""
    with ServerScope() as s:
        big = b"\x00" * (2 * 1024 * 1024)  # 2 MB
        s.router.add("/big.jpg", big, content_type="image/jpeg")
        from backend.crawler.collector import MAX_DOWNLOAD_BYTES as cap

        # Temporarily lower the cap to force rejection.
        import backend.crawler.collector as col_mod

        old = col_mod.MAX_DOWNLOAD_BYTES
        try:
            col_mod.MAX_DOWNLOAD_BYTES = 1024
            col = Collector()
            try:
                assert col.download_image(s.url("/big.jpg")) == ""
            finally:
                col.cleanup()
        finally:
            col_mod.MAX_DOWNLOAD_BYTES = old


# ----------------------------------------------------------------- face match


def test_cosine_similarity_basics():
    import numpy as np

    a = np.ones(512)
    b = np.ones(512) * 2
    c = np.ones(512)
    c[0] = -1
    assert cosine_similarity(a, b) > 0.99
    assert -1.0 <= cosine_similarity(a, c) <= 1.0


def test_match_threshold():
    import numpy as np

    a = np.linspace(-1, 1, 512)
    is_match, score = match_embeddings(a, a.copy(), threshold=0.4)
    assert is_match
    assert score > 0.4
    is_match, score = match_embeddings(a, -a, threshold=0.4)
    assert not is_match


@pytest.mark.skipif(not os.path.exists(LENA), reason="Lena fixture missing")
def test_same_image_embeddings_match():
    """The exact same image embed twice must score above the 0.4 threshold."""
    a = embed_face(LENA)
    b = embed_face(LENA)
    assert a and b and a.embedding is not None and b.embedding is not None
    is_match, score = match_embeddings(a.embedding, b.embedding)
    assert is_match
    assert score > SIMILARITY_THRESHOLD


@pytest.mark.skipif(not os.path.exists(LENA), reason="Lena fixture missing")
def test_different_faces_do_not_match():
    a = embed_face(LENA)
    alt = os.path.join(FIXTURES, "einstein.jpg")
    if os.path.exists(alt):
        b = embed_face(alt)
        if a and b:
            _, score = match_embeddings(a.embedding, b.embedding)
            assert score < SIMILARITY_THRESHOLD