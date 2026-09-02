"""API layer tests using FastAPI TestClient + a mocked reverse-search."""

from __future__ import annotations

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.search.search_models import SearchResponse, SearchResult  # noqa: E402

from mock_server import ServerScope  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
LENA = os.path.join(FIXTURES, "lena.jpg")


@pytest.fixture
def client(monkeypatch):
    return TestClient(app)


def _with_mocked_search(monkeypatch, results):
    from backend import pipeline
    from backend.pipeline import runner as runner_mod

    def fake_search(image_path, provider="auto"):
        return SearchResponse(results=results, provider="test")

    monkeypatch.setattr(runner_mod, "search_web", fake_search)


def _post_face_bytes():
    with open(LENA, "rb") as fh:
        return fh.read()


@pytest.mark.skipif(not os.path.exists(LENA), reason="Lena fixture missing")
def test_upload_returns_job_and_background_completes(monkeypatch):
    """POST accepts a JPEG, returns a job_id; pipeline completes in background."""
    with ServerScope() as s:
        lena = _post_face_bytes()
        # Post page exposes its own content image (an open post) -> verified.
        s.router.add(
            "/post",
            '<title>Open Post</title><meta property="og:image" content="/content.jpg">',
        )
        s.router.add("/content.jpg", lena, content_type="image/jpeg")
        _with_mocked_search(
            monkeypatch,
            [SearchResult(url=s.url("/post"), image_url=s.url("/content.jpg"))],
        )

        # Use a temp DB so we don't touch the real pipeline.db.
        tmp_db = os.path.join(tempfile.gettempdir(), "api_test.db")
        if os.path.exists(tmp_db):
            os.remove(tmp_db)
        monkeypatch.setenv("PIPELINE_DB", tmp_db)

        client = TestClient(app)
        r = client.post(
            "/search",
            files={"file": ("lena.jpg", lena, "image/jpeg")},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "processing"
        job_id = body["job_id"]
        assert job_id

        # Poll until complete.
        for _ in range(40):
            res = client.get(f"/search/{job_id}").json()
            if res["status"] != "processing":
                break
            import time

            time.sleep(1)

        assert res["status"] == "complete"
        assert res["face_detected"] is True
        assert res["match_found"] is True
        assert res["matched_post"] is not None
        assert res["matched_post"]["evidence_tier"] == "verified"
        assert res["candidates_seen"] == 1

        if os.path.exists(tmp_db):
            os.remove(tmp_db)


@pytest.mark.skipif(not os.path.exists(LENA), reason="Lena fixture missing")
def test_verify_endpoint_for_unregistered_job(monkeypatch):
    with ServerScope() as s:
        lena = _post_face_bytes()
        s.router.add(
            "/post",
            '<title>Open Post</title><meta property="og:image" content="/content.jpg">',
        )
        s.router.add("/content.jpg", lena, content_type="image/jpeg")
        _with_mocked_search(
            monkeypatch,
            [SearchResult(url=s.url("/post"), image_url=s.url("/content.jpg"))],
        )
        tmp_db = os.path.join(tempfile.gettempdir(), "api_verify_test.db")
        if os.path.exists(tmp_db):
            os.remove(tmp_db)
        monkeypatch.setenv("PIPELINE_DB", tmp_db)

        client = TestClient(app)
        body = client.post(
            "/search", files={"file": ("lena.jpg", lena, "image/jpeg")}
        ).json()
        job_id = body["job_id"]
        for _ in range(40):
            res = client.get(f"/search/{job_id}").json()
            if res["status"] != "processing":
                break
            import time

            time.sleep(1)
        v = client.get(f"/search/{job_id}/verify").json()
        # No blockchain record stored (do_blockchain=False) -> not on chain.
        assert v["on_chain"] is False
        assert "No on-chain record" in v["error"]

        if os.path.exists(tmp_db):
            os.remove(tmp_db)


def test_upload_rejects_bad_content_type(client):
    r = client.post(
        "/search",
        files={"file": ("x.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 415


def test_get_missing_job_returns_404(client):
    r = client.get("/search/does-not-exist")
    assert r.status_code == 404


def test_health_endpoint(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_frontend_served_at_root(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Face" in r.text
    assert "Face" in r.text
