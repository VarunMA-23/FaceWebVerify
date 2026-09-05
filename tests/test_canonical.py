"""Canonical fingerprint tests: byte-stability, ppm conversions, tamper-evidence."""

from backend.fingerprint.canonical import canonical_bytes, to_ppm
from backend.fingerprint.canonicalizer import EvidenceRecord
from backend.fingerprint.hasher import fingerprint, fingerprint_from_canonical_json


def _record(**over) -> EvidenceRecord:
    data = dict(
        evidence_id="ev-1",
        source_url="https://example.com/p",
        canonical_url="https://example.com/p",
        platform="example",
        source_type="post",
        discovered_at="2026-01-01T00:00:00Z",
        face_similarity=0.8123,
        image_similarity=0.9,
        evidence_tier="verified",
        image_sha256="ab" * 32,
        caption="caption",
        title="title",
        providers=["bing", "serp"],
        provider_consensus="unanimous",
        evidence_score=84,
        verification_reasons=["high face similarity"],
    )
    data.update(over)
    return EvidenceRecord(**data)


def test_canonical_bytes_stable_across_float_equivalents():
    assert canonical_bytes({"x": 1, "y": "z"}) == b'{"x":1,"y":"z"}'


def test_to_ppm_roundtrip():
    assert to_ppm(0.8123) == 812300
    assert to_ppm(0.0) == 0
    assert to_ppm(1.0) == 1000000


def test_canonical_dict_has_no_floats():
    d = _record().canonical_dict()
    assert "face_similarity" not in d
    assert d["face_similarity_ppm"] == 812300
    assert d["image_similarity_ppm"] == 900000


def test_display_dict_rehydrates_and_rehashes_same():
    rec = _record()
    rehydrated = EvidenceRecord(**rec.display_dict())
    assert fingerprint(rehydrated) == fingerprint(rec)


def test_fingerprint_matches_canonical_json():
    rec = _record()
    assert fingerprint(rec) == fingerprint_from_canonical_json(rec.canonical_json())


def test_same_hash_for_same_record():
    assert fingerprint(_record()) == fingerprint(_record())


def test_modified_record_changes_hash():
    original = fingerprint(_record(caption="caption"))
    tampered = fingerprint(_record(caption="modified caption"))
    assert original != tampered


def test_providers_and_reasons_sorted():
    before = _record(providers=["z", "a"], verification_reasons=["b", "a"]).canonical_dict()
    after = _record(providers=["a", "z"], verification_reasons=["a", "b"]).canonical_dict()
    assert canonical_bytes(before) == canonical_bytes(after)


def test_hash_is_sha256_hex():
    digest = fingerprint(_record())
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)