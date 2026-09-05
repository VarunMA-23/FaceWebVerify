"""Regression tests for bugs found during the audit.

Each test pins a specific fix so the broken behaviour cannot silently return.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from fastapi.testclient import TestClient  # noqa: E402

from backend.fingerprint.canonicalizer import EvidenceRecord  # noqa: E402
from backend.evidence.source import classify_source_type  # noqa: E402
from backend.blockchain.localchain import LocalChain  # noqa: E402
from backend.face.matcher import EvidenceTier, FaceMatch, best_of  # noqa: E402
from backend.crawler.collector import Collector  # noqa: E402
from backend.evidence.consensus import provider_consensus_label  # noqa: E402


# ------------------------------------------------------------------ API params


def test_create_search_rejects_zero_or_negative_limit(monkeypatch):
    """limit=0 once caused an infinite loop in the runner's batch loop."""
    from backend.main import app

    _isolate_state(monkeypatch)
    client = TestClient(app)
    lena = _lena_bytes()
    for bad in (0, -3):
        r = client.post(
            "/search?limit=%d" % bad,
            files={"file": ("lena.jpg", lena, "image/jpeg")},
        )
        assert r.status_code == 422, f"limit={bad} was accepted"


def test_create_search_rejects_out_of_range_threshold(monkeypatch):
    from backend.main import app

    _isolate_state(monkeypatch)
    client = TestClient(app)
    lena = _lena_bytes()
    r = client.post(
        "/search?threshold=1.5",
        files={"file": ("lena.jpg", lena, "image/jpeg")},
    )
    assert r.status_code == 422


# ------------------------------------------------------------------ SerpAPI


def test_serpapi_sends_url_param_for_url_input(monkeypatch):
    """The query image URL was silently dropped for SerpAPI URL inputs."""
    import backend.search.visual_search as vs
    from backend.search.visual_search import SerpApiProvider

    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {}

    def fake_get(url, params=None, timeout=None):
        captured["params"] = params
        return FakeResp()

    monkeypatch.setenv("SERPAPI_API_KEY", "k")
    monkeypatch.setattr(vs.requests, "get", fake_get)
    resp = SerpApiProvider("serpapi").search("https://example.com/face.jpg")
    assert resp.error == ""
    assert captured["params"].get("url") == "https://example.com/face.jpg"


# ------------------------------------------------------------------ best_of


def test_best_of_keeps_tier_source_score_consistent():
    """A higher-scoring thumbnail must not claim the 'verified' tier."""
    thumb = FaceMatch(
        is_match=True,
        score=0.9,
        face=None,
        tier=EvidenceTier.THUMBNAIL,
        source="thumbnail",
        image_url="http://thumb",
    )
    page = FaceMatch(
        is_match=True,
        score=0.6,
        face=None,
        tier=EvidenceTier.VERIFIED,
        source="page",
        image_url="http://page",
    )
    best = best_of([thumb, page])
    assert best.tier == EvidenceTier.VERIFIED
    assert best.source == "page"
    assert best.image_url == "http://page"
    assert best.score == 0.6


def test_best_of_nonmatch_stays_none():
    m = FaceMatch(is_match=False, score=0.2, face=None, tier=EvidenceTier.THUMBNAIL)
    best = best_of([m])
    assert best.tier == EvidenceTier.NONE


# ------------------------------------------------------------------ fingerprint


def test_to_ppm_rejects_non_finite():
    from backend.fingerprint.canonical import to_ppm

    with pytest.raises(ValueError):
        to_ppm(float("nan"))
    with pytest.raises(ValueError):
        to_ppm(float("inf"))


def test_evidence_record_accepts_none_lists():
    rec = EvidenceRecord(evidence_id="x", providers=None, verification_reasons=None)
    d = rec.canonical_dict()
    assert d["providers"] == []
    assert d["verification_reasons"] == []


# ------------------------------------------------------------------ local chain


def test_localchain_bootstraps_empty_ledger(tmp_path):
    """A crashed/truncated ledger (empty file) must recover, not IndexError."""
    root = tmp_path / "chain"
    chain = LocalChain(root, difficulty_bits=0)
    assert (root / "blocks.jsonl").exists()
    (root / "blocks.jsonl").write_text("", encoding="utf-8")  # simulate crash

    chain2 = LocalChain(root, difficulty_bits=0)
    receipt = chain2.anchor("a" * 64)
    assert receipt.block_index == 1
    assert chain2.find_record("a" * 64) is not None
    chain2.verify_chain()  # structural integrity intact


# ------------------------------------------------------------------ source classification


def test_substring_domain_guards():
    """Lookalike domains must not be (mis)classified as social/reference."""
    assert classify_source_type("https://notinstagram.com/p/abc", "web") == "web"
    assert classify_source_type("https://faketwitter.com/status/1", "web") == "web"
    assert classify_source_type("https://foobbc.com/art", "web") == "web"
    assert classify_source_type("https://youtube.com.attacker.io/v", "web") == "web"
    # Real hosts still classify correctly.
    assert classify_source_type("https://www.instagram.com/p/abc", "web") == "social"
    assert classify_source_type("https://news.bbc.com/story", "web") == "reference"


def test_provider_consensus_label_zero():
    assert provider_consensus_label(0, 0) == "no provider available"


# ------------------------------------------------------------------ collector


def test_collector_tolerates_malformed_content_length(monkeypatch):
    """A non-numeric Content-Length header must not crash the batch."""

    class FakeResp:
        headers = {"Content-Type": "image/jpeg", "Content-Length": "garbage"}
        status_code = 200

        def iter_content(self, chunk_size=65536):
            yield b"\xff\xd8\xff\xe0" + b"\x00" * 64
            return

        def close(self):
            pass

    col = Collector()
    monkeypatch.setattr(col.session, "get", lambda *a, **k: FakeResp())
    local = col.download_image("http://127.0.0.1/never-used/x.jpg")
    assert local.endswith(".jpg")
    col.cleanup()


# ------------------------------------------------------------------ helpers


def _lena_bytes() -> bytes:
    fixture = os.path.join(os.path.dirname(__file__), "fixtures", "lena.jpg")
    if not os.path.exists(fixture):
        pytest.skip("Lena fixture missing")
    with open(fixture, "rb") as fh:
        return fh.read()


def _isolate_state(monkeypatch) -> None:
    import tempfile

    scratch = tempfile.mkdtemp(prefix="fvw_reg_")
    monkeypatch.setenv("PIPELINE_DB", os.path.join(scratch, "pipeline.db"))
    monkeypatch.setenv("BLOCKCHAIN_CHAIN_DIR", os.path.join(scratch, "chaindata"))
    monkeypatch.setenv("BLOCKCHAIN_ANCHOR", "local")