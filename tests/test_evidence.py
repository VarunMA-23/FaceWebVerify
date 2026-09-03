"""Tests for the evidence engine (Phase 1)."""

from backend.evidence.consensus import (
    provider_consensus_label,
    search_all_providers,
)
from backend.evidence.explain import build_explanation
from backend.evidence.models import SourceInfo
from backend.evidence.scorer import WEIGHTS, build_provider_consensus, compute_evidence_score
from backend.evidence.source import (
    canonicalize_url,
    classify_source_type,
    evidence_tier_label,
    extract_domain,
    extract_social_handle,
    is_social_source,
    normalize_platform,
)
from backend.fingerprint.canonicalizer import EvidenceRecord
from backend.fingerprint.hasher import fingerprint
from backend.blockchain.integrity import verify_integrity


def test_canonicalize_url_strips_tracking():
    a = canonicalize_url(
        "https://www.instagram.com/p/abc/?utm_source=ig&utm_medium=share"
    )
    b = canonicalize_url("https://instagram.com/p/abc")
    assert "utm_" not in a
    assert a == b


def test_classify_social_instagram():
    assert classify_source_type("https://www.instagram.com/p/abc/", "instagram") == "social"


def test_classify_wikipedia():
    assert classify_source_type("https://en.wikipedia.org/wiki/Test", "web") == "wiki"


def test_extract_domain():
    assert extract_domain("https://www.facebook.com/page") == "facebook.com"


def test_is_social_source():
    assert is_social_source("social", "instagram") is True
    assert is_social_source("wiki", "web") is False


def test_provider_consensus_single():
    assert provider_consensus_label(1, 1) == "1 provider available"


def test_provider_consensus_multi():
    assert provider_consensus_label(2, 3) == "2/3"


def test_build_provider_consensus():
    c = build_provider_consensus(["serpapi", "bing"], 3)
    assert c.provider_count == 2
    assert c.provider_consensus == "2/3"


def test_evidence_score_face_only():
    source = SourceInfo(source_type="web", page_retrieved=False, image_retrieved=True)
    consensus = build_provider_consensus(["serpapi"], 1)
    score = compute_evidence_score(
        face_similarity=0.95,
        image_similarity=None,
        evidence_tier="thumbnail",
        source=source,
        consensus=consensus,
        has_title=True,
        has_caption=False,
    )
    assert 0 < score.total <= sum(WEIGHTS.values())
    assert "face_similarity" in score.breakdown


def test_evidence_score_no_fake_consensus():
    source = SourceInfo(source_type="social", page_retrieved=True, image_retrieved=True)
    consensus = build_provider_consensus(["serpapi"], 1)
    score = compute_evidence_score(
        face_similarity=0.9,
        image_similarity=1.0,
        evidence_tier="verified",
        source=source,
        consensus=consensus,
        has_title=True,
        has_caption=True,
    )
    assert "provider_consensus" not in score.breakdown


def test_explanation_truthful_no_fake_social():
    source = SourceInfo(
        source_url="https://en.wikipedia.org/wiki/Test",
        source_type="wiki",
        platform="web",
        page_retrieved=True,
        image_retrieved=True,
    )
    exp = build_explanation(
        face_similarity=0.9,
        threshold=0.4,
        evidence_tier="verified",
        source=source,
        consensus=build_provider_consensus(["serpapi"], 1),
        is_match=True,
    )
    assert any("wiki" in r.lower() or "reference" in r.lower() for r in exp.reasons)
    assert not any("social-media post verified" in r.lower() for r in exp.reasons)


def test_evidence_record_deterministic_hash():
    r1 = EvidenceRecord(
        evidence_id="ev1",
        source_url="https://instagram.com/p/abc/",
        canonical_url="https://instagram.com/p/abc",
        platform="instagram",
        source_type="social",
        discovered_at="2026-01-01T00:00:00+00:00",
        face_similarity=0.95,
        evidence_tier="verified",
        providers=["serpapi"],
        provider_consensus="1 provider available",
        evidence_score=80,
        verification_reasons=["Face detected"],
    )
    r2 = EvidenceRecord(
        evidence_id="ev1",
        source_url="https://instagram.com/p/abc/",
        canonical_url="https://instagram.com/p/abc",
        platform="instagram",
        source_type="social",
        discovered_at="2026-01-01T00:00:00+00:00",
        face_similarity=0.95,
        evidence_tier="verified",
        providers=["serpapi"],
        provider_consensus="1 provider available",
        evidence_score=80,
        verification_reasons=["Face detected"],
    )
    assert fingerprint(r1) == fingerprint(r2)


def test_evidence_record_modified_changes_hash():
    base = EvidenceRecord(
        evidence_id="ev1",
        source_url="https://instagram.com/p/abc/",
        discovered_at="2026-01-01T00:00:00+00:00",
        face_similarity=0.95,
        evidence_tier="verified",
    )
    modified = EvidenceRecord(
        evidence_id="ev1",
        source_url="https://instagram.com/p/xyz/",
        discovered_at="2026-01-01T00:00:00+00:00",
        face_similarity=0.95,
        evidence_tier="verified",
    )
    assert fingerprint(base) != fingerprint(modified)


def test_integrity_match():
    h = "a" * 64
    r = verify_integrity(h, h, True)
    assert r["integrity_verified"] is True
    assert r["status"] == "verified"


def test_integrity_mismatch():
    r = verify_integrity("a" * 64, "b" * 64, True)
    assert r["integrity_verified"] is False
    assert r["status"] == "changed"


def test_search_all_providers_no_keys():
    resp = search_all_providers("/nonexistent.jpg")
    assert resp.error or resp.providers_available == 0


def test_extract_social_handle_instagram():
    assert extract_social_handle("https://instagram.com/nasa/p/abc/", "instagram") == "@nasa"
    assert extract_social_handle("https://instagram.com/p/abc/", "instagram") is None


def test_extract_social_handle_x():
    assert extract_social_handle("https://x.com/nasa/status/123", "twitter") == "@nasa"


def test_evidence_tier_label_social_verified():
    assert evidence_tier_label("verified", "social") == "Verified Social Source"
    assert evidence_tier_label("thumbnail", "social") == "Social Result — Thumbnail Only"


def test_normalize_platform_twitter_to_x():
    assert normalize_platform("twitter") == "x"


def test_classify_pinterest_as_social():
    assert classify_source_type("https://pinterest.com/pin/123", "pinterest") == "social"


def test_integrity_unavailable():
    r = verify_integrity("", "", False)
    assert r["status"] == "unavailable"
