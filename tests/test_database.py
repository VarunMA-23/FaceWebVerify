"""Database (SQLite) repository tests."""

from __future__ import annotations

import os
import tempfile

import pytest

from backend.database.models import Database


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "test.db"))


def test_create_and_get_job(db):
    db.create_job("abc", "/tmp/x.jpg")
    job = db.get_job("abc")
    assert job is not None
    assert job["job_id"] == "abc"
    assert job["input_image_path"] == "/tmp/x.jpg"
    assert job["status"] == "processing"


def test_update_job_status(db):
    db.create_job("abc", "/tmp/x.jpg")
    db.update_job_status("abc", "complete")
    assert db.get_job("abc")["status"] == "complete"


def test_missing_job_returns_none(db):
    assert db.get_job("nope") is None


def test_add_and_get_posts_ordered_by_similarity(db):
    db.create_job("j1", "/tmp/x.jpg")
    db.add_post("j1", "u1", "img1", "ig", "cap1", "t1", 0.5, "verified")
    db.add_post("j1", "u2", "img2", "yt", "cap2", "t2", 0.9, "verified")
    posts = db.get_posts("j1")
    assert len(posts) == 2
    # Ordered by face_similarity DESC -> u2 (0.9) first.
    assert posts[0]["post_url"] == "u2"
    assert posts[1]["post_url"] == "u1"
    assert posts[0]["evidence_tier"] == "verified"


def test_blockchain_record_roundtrip(db):
    db.create_job("j1", "/tmp/x.jpg")
    assert db.get_blockchain_record("j1") is None
    db.add_blockchain_record("j1", "hash123", "txabc", 42)
    rec = db.get_blockchain_record("j1")
    assert rec["content_hash"] == "hash123"
    assert rec["transaction_hash"] == "txabc"
    assert rec["block_number"] == 42


def test_add_posts_batch(db):
    db.create_job("j1", "/tmp/x.jpg")
    posts = [
        {
            "post_url": "u1",
            "image_url": "img1",
            "platform": "ig",
            "caption": "cap1",
            "title": "t1",
            "face_similarity": 0.5,
            "evidence_tier": "verified",
        },
        {
            "post_url": "u2",
            "image_url": "img2",
            "platform": "yt",
            "caption": "cap2",
            "title": "t2",
            "face_similarity": 0.9,
            "evidence_tier": "thumbnail",
            "source_type": "social",
            "domain": "youtube.com",
            "evidence_score": 8,
            "provider_count": 2,
            "providers": ["bing", "tineye"],
            "explanation": ["a", "b"],
            "metadata": {"rank": 1},
        },
    ]
    db.add_posts("j1", posts)
    got = {p["post_url"]: p for p in db.get_posts("j1")}
    assert set(got) == {"u1", "u2"}
    # Simpler one uses defaults.
    assert got["u1"]["source_type"] == ""
    assert got["u1"]["providers_json"] == "[]"
    # Richer one persists all serialized metadata.
    assert got["u2"]["provider_count"] == 2
    assert got["u2"]["evidence_score"] == 8
    assert got["u2"]["source_type"] == "social"
    assert "bing" in got["u2"]["providers_json"]

    # Empty batch is a no-op.
    db.add_posts("j1", [])
    assert len(db.get_posts("j1")) == 2
