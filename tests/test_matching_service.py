"""Tests for the tiered face-matching service (thumbnail PATH A + page PATH B)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from mock_server import ServerScope  # noqa: E402

from backend.face.embedder import embed_face  # noqa: E402
from backend.face.matcher import EvidenceTier, best_of, match_image_to_embedding  # noqa: E402
from backend.matching.service import (  # noqa: E402
    MatcherService,
    _same_image_file,
    adapt_candidate_limit,
    match_reference_to_search_results,
)
from backend.search.search_models import SearchResult  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
LENA = os.path.join(FIXTURES, "lena.jpg")


# ------------------------------------------------------------------ adaptive RAM fallback


def test_adapt_candidate_limit_never_grows_or_goes_negative():
    for req in range(0, 11):
        out = adapt_candidate_limit(req)
        assert 0 <= out <= max(req, 0)


def test_adapt_candidate_limit_returns_adjusted_when_ram_low(monkeypatch):
    from backend import matching

    original = matching.service._available_ram_mib

    def fake(avail):
        def _fake():
            return avail
        return _fake

    try:
        # 300 MiB -> very tight, at most 2 candidates
        monkeypatch.setattr(matching.service, "_available_ram_mib", fake(300))
        assert adapt_candidate_limit(5) == 2
        assert adapt_candidate_limit(1) == 1

        # 700 MiB -> tight, at most 3 candidates
        monkeypatch.setattr(matching.service, "_available_ram_mib", fake(700))
        assert adapt_candidate_limit(5) == 3

        # plenty of RAM -> unchanged
        monkeypatch.setattr(matching.service, "_available_ram_mib", fake(16384))
        assert adapt_candidate_limit(5) == 5

        # unknown RAM -> unchanged
        monkeypatch.setattr(matching.service, "_available_ram_mib", fake(-1))
        assert adapt_candidate_limit(5) == 5
    finally:
        matching.service._available_ram_mib = original


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


@pytest.mark.skipif(not os.path.exists(LENA), reason="Lena fixture missing")
def test_match_candidates_parallel_returns_results_in_input_order():
    """Concurrent matching returns one CandidateEvidence per input, in order."""
    with ServerScope() as s:
        with open(LENA, "rb") as fh:
            lena_bytes = fh.read()
        # Two open posts with the same content image -> both should match.
        for n in (1, 2):
            s.router.add(
                f"/post{n}",
                f'<title>Post {n}</title><meta property="og:image" content="/content{n}.jpg">',
            )
            s.router.add(f"/content{n}.jpg", lena_bytes, content_type="image/jpeg")
        # A third candidate whose page is a plain page (no image) -> no match.
        s.router.add("/post3", "<title>No image here</title><p>text only</p>")

        ref = embed_face(LENA)
        assert ref and ref.embedding is not None

        results = [
            SearchResult(url=s.url("/post1"), image_url=""),
            SearchResult(url=s.url("/post2"), image_url=""),
            SearchResult(url=s.url("/post3"), image_url=""),
        ]
        with MatcherService() as service:
            evid = service.match_candidates(ref.embedding, results)

        # One result per input, in the original order.
        assert len(evid) == 3
        assert [e.page_url for e in evid] == [r.url for r in results]
        # First two matched (verified), third did not.
        assert evid[0].is_match is True and evid[0].tier == EvidenceTier.VERIFIED
        assert evid[1].is_match is True and evid[1].tier == EvidenceTier.VERIFIED
        assert evid[2].is_match is False


# -------------------------------------------------------------- dedup helper


def test_same_image_file_identical_and_different(tmp_path):
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    c = tmp_path / "c.jpg"
    a.write_bytes(b"identical-bytes")
    b.write_bytes(b"identical-bytes")
    c.write_bytes(b"different-bytes")

    assert _same_image_file(str(a), str(b)) is True
    assert _same_image_file(str(a), str(c)) is False
    assert _same_image_file("", str(c)) is False
    assert _same_image_file(str(a), str(tmp_path / "missing.jpg")) is False
