"""Tests for content fingerprinting (Module 6)."""

from backend.fingerprint.canonicalizer import ContentRecord, image_sha256
from backend.fingerprint.hasher import fingerprint


def _record(**overrides) -> ContentRecord:
    base = dict(
        post_url="https://www.instagram.com/p/abc123/",
        image_sha256="a" * 64,
        caption="A photo of a person",
        timestamp="2026-01-01T00:00:00+00:00",
        platform="instagram",
        title="My Post",
    )
    base.update(overrides)
    return ContentRecord(**base)


def test_same_data_same_hash():
    """Identical records produce identical hashes."""
    a = fingerprint(_record())
    b = fingerprint(_record())
    assert a == b
    assert len(a) == 64
    assert int(a, 16) >= 0  # valid hex


def test_modified_url_different_hash():
    assert fingerprint(_record(post_url="https://www.instagram.com/p/other/")) != fingerprint(
        _record()
    )


def test_modified_caption_different_hash():
    assert fingerprint(_record(caption="Changed caption")) != fingerprint(_record())


def test_modified_image_hash_different():
    assert fingerprint(_record(image_sha256="b" * 64)) != fingerprint(_record())


def test_evidence_tier_included_in_hash():
    """Different evidence tiers produce different hashes (honest attestation)."""
    assert fingerprint(_record(evidence="verified")) != fingerprint(
        _record(evidence="thumbnail")
    )
    assert fingerprint(_record(evidence="")) != fingerprint(_record(evidence="verified"))


def test_modified_timestamp_different():
    assert fingerprint(_record(timestamp="2026-02-01T00:00:00+00:00")) != fingerprint(
        _record()
    )


def test_schema_version_included():
    assert fingerprint(_record(schema_version="2")) != fingerprint(_record())


def test_none_empty_fields_normalized():
    """Empty/whitespace fields normalize to '' so hashing is stable."""
    a = fingerprint(_record(caption="", platform="  ", title=None))
    b = fingerprint(_record(caption="  ", platform="", title=""))
    assert a == b


def test_image_sha256_stable():
    assert image_sha256(b"hello") == image_sha256(b"hello")
    assert image_sha256(b"hello") != image_sha256(b"hello!")