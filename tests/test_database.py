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
