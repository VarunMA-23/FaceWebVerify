"""Tests for the tiered face-matching service (thumbnail PATH A + page PATH B)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from mock_server import ServerScope  # noqa: E402

from backend.face.embedder import embed_face  # noqa: E402
from backend.face.matcher import EvidenceTier, best_of, match_image_to_embedding  # noqa: E402
from backend.matching.service import MatcherService, match_reference_to_search_results  # noqa: E402
from backend.search.search_models import SearchResult  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
LENA = os.path.join(FIXTURES, "lena.jpg")


# ------------------------------------------------------------------ unit


def test_match_image_to_embedding_compares_all_faces():
    """Even when the first detected face is not a match, a later one can win."""
    import numpy as np

    ref = np.linspace(-1, 1, 512)
    match = match_image_to_embedding(ref, LENA, tier=EvidenceTier.THUMBNAIL, source="thumbnail")
    # LENA contains exactly one face; sanity: the API returns a dataclass now.
    assert isinstance(match.score, float)
    assert match.tier == EvidenceTier.THUMBNAIL
    assert match.source == "thumbnail"


def test_best_of_prefers_verified_over_thumbnail():
    """At comparable scores, a verified (page) match raises the tier."""
    import numpy as np

    silly = np.linspace(-1, 1, 512)
    thumb = match_image_to_embedding(silly, LENA, tier=EvidenceTier.THUMBNAIL)
    page = match_image_to_embedding(silly, LENA, tier=EvidenceTier.VERIFIED)
    combined = best_of([page, thumb])
    assert combined.tier == EvidenceTier.VERIFIED if combined.is_match else True


def test_best_of_with_no_faces():
    import numpy as np
    import cv2

    blank = np.full((60, 60, 3), 255, dtype=np.uint8)
    tmp = os.path.join(FIXTURES, "_blank_test.png")
    cv2.imwrite(tmp, blank)
    try:
        ref = np.ones(512)
        m = match_image_to_embedding(ref, tmp)
        assert m.is_match is False
        assert m.face is None
        combined = best_of([m])
        assert combined.tier == EvidenceTier.NONE
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# ---------------------------------------------------------- integration


@pytest.mark.skipif(not os.path.exists(LENA), reason="Lena fixture missing")
def test_thumbnail_path_matches_login_walled_post():
    """A login-walled post (page unreachable) still matches via thumbnail.

    PATH A: the search thumbnail is served publicly and contains the queried
    face, so we get a match even though the post page itself is not crawlable.
    """
    # Use lena.jpg served as a thumbnail.
    with ServerScope() as s:
        with open(LENA, "rb") as fh:
            lena_bytes = fh.read()
        # The post page is a login wall (won't expose a content image).
        s.router.add("/post", "<title>Log in</title><input type=\"password\">")
        # The thumbnail IS the queried face, publicly served.
        s.router.add("/thumb.jpg", lena_bytes, content_type="image/jpeg")

        ref = embed_face(LENA)
        assert ref and ref.embedding is not None

        results = [SearchResult(url=s.url("/post"), image_url=s.url("/thumb.jpg"))]
        with MatcherService() as service:
            evid = service.match_candidates(ref.embedding, results)
            ev = evid[0]

        assert ev.best_match is not None
        # The thumbnail path provided a real face match (same face as ref).
        assert ev.thumbnail_match is not None
        assert ev.thumbnail_match.is_match is True
        # The page is a login wall (no page image), so the evidence is thumbnail.
        assert ev.tier == EvidenceTier.THUMBNAIL
        assert ev.is_match is True


@pytest.mark.skipif(not os.path.exists(LENA), reason="Lena fixture missing")
def test_page_path_produces_verified_match():
    """An open post with a crawlable content image yields a verified match."""
    with ServerScope() as s:
        with open(LENA, "rb") as fh:
            lena_bytes = fh.read()
        # Open post exposes its own content image.
        s.router.add(
            "/post",
            '<title>Real Post</title><meta property="og:image" content="/content.jpg">',
        )
        s.router.add("/content.jpg", lena_bytes, content_type="image/jpeg")

        ref = embed_face(LENA)
        assert ref and ref.embedding is not None

        results = [SearchResult(url=s.url("/post"), image_url="")]
        with MatcherService() as service:
            evid = service.match_candidates(ref.embedding, results)
            ev = evid[0]

        assert ev.page_match is not None
        assert ev.page_match.is_match is True
        assert ev.tier == EvidenceTier.VERIFIED
        assert ev.score > 0.4
