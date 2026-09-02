"""HTTP routes: POST /search, GET /search/{id}, GET /search/{id}/verify."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from backend.api.schemas import (
    BlockchainSummary,
    PostSummary,
    SearchResponseModel,
    VerifyResponseModel,
)
from backend.database.models import Database
from backend.pipeline.runner import PipelineRunner

router = APIRouter(prefix="/search", tags=["search"])

#: Max upload size in bytes (10 MB per the spec).
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}

_executor = ThreadPoolExecutor(max_workers=2)


class JobAccepted(BaseModel):
    job_id: str
    status: str = "processing"


def _runner(db: Database | None = None) -> PipelineRunner:
    return PipelineRunner(db or Database(), do_blockchain=False)


def get_db() -> Database:
    """FastAPI dependency: a fresh Database connection per request."""
    return Database()


@router.post("", response_model=JobAccepted)
async def create_search(
    file: UploadFile = File(...),
    limit: int = 5,
    threshold: float = 0.4,
) -> JobAccepted:
    """Upload a face image and start a reverse-image search pipeline.

    Validates the upload (Module 1), returns the ``job_id`` immediately, and
    runs the pipeline in the background. Poll ``GET /search/{job_id}`` for
    the result.
    """
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Unsupported content type; use JPEG, PNG or WebP.",
        )
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB).")
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")

    job_id = uuid.uuid4().hex
    db = Database()
    # Pre-create the job row so GET /search/{id} finds it immediately, even
    # before the background worker starts running the pipeline.
    db.create_job(job_id, f"pending:{file.filename or 'upload.jpg'}")
    runner = _runner(db)
    _executor.submit(_run_job, runner, db, job_id, data, file.filename, limit, threshold)
    return JobAccepted(job_id=job_id, status="processing")


def _run_job(
    runner: PipelineRunner,
    db: Database,
    job_id: str,
    data: bytes,
    filename: str,
    limit: int,
    threshold: float,
) -> None:
    try:
        runner.run(data, filename or "upload.jpg", job_id=job_id)
    except Exception:  # noqa: BLE001 - keep worker threads from crashing
        db.update_job_status(job_id, "failed")


@router.get("/{job_id}", response_model=SearchResponseModel)
def get_search(job_id: str, db: Database = Depends(get_db)) -> SearchResponseModel:
    """Fetch the current status and result for a job."""
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    posts = db.get_posts(job_id)
    candidates = [
        PostSummary(
            url=p["post_url"],
            image_url=p["image_url"],
            platform=p["platform"],
            title=p["title"],
            caption=p["caption"],
            similarity=p["face_similarity"],
            evidence_tier=p["evidence_tier"],
            matched=p["face_similarity"] >= 0.4 and bool(p["post_url"]),
        )
        for p in posts
    ]

    matched = [c for c in candidates if c.matched]
    matched_post = matched[0] if matched else None

    bc = db.get_blockchain_record(job_id)
    blockchain = None
    if bc:
        blockchain = BlockchainSummary(
            content_hash=bc["content_hash"],
            tx_hash=bc["transaction_hash"],
            block_number=bc["block_number"],
            verified=bool(bc["transaction_hash"]),
        )

    return SearchResponseModel(
        job_id=job_id,
        status=job["status"],
        face_detected=True,
        candidates_seen=len(candidates),
        match_found=bool(matched_post),
        matched_post=matched_post,
        blockchain=blockchain,
        candidates=candidates,
    )


@router.get("/{job_id}/verify", response_model=VerifyResponseModel)
def verify_search(job_id: str, db: Database = Depends(get_db)) -> VerifyResponseModel:
    """Verify the on-chain registration for a job."""
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    bc = db.get_blockchain_record(job_id)
    if bc is None:
        return VerifyResponseModel(
            job_id=job_id,
            verified=False,
            on_chain=False,
            hash_matches=False,
            error="No on-chain record stored for this job.",
        )

    try:
        from backend.blockchain.verifier import verify_on_blockchain

        on_chain = verify_on_blockchain(bc["content_hash"])
    except (ValueError, ConnectionError):
        on_chain = False

    return VerifyResponseModel(
        job_id=job_id,
        verified=bool(bc["transaction_hash"]),
        on_chain=on_chain,
        hash_matches=on_chain,
        content_hash=bc["content_hash"],
        tx_hash=bc["transaction_hash"],
    )
