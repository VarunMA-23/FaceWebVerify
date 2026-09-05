"""FastAPI application entry point.

Run with::

    uvicorn backend.main:app --reload

Exposes the reverse-image-search / face-match / blockchain pipeline over HTTP.
The static frontend (``frontend/index.html``) is mounted at the root.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI

load_dotenv()
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api.routes import chain_router, router, verify_independent_evidence
from backend.api.schemas import IndependentEvidenceVerificationModel

evidence_router = APIRouter(prefix="/evidence", tags=["evidence"])
evidence_router.add_api_route(
    "/{evidence_id}/verify",
    verify_independent_evidence,
    methods=["GET"],
    response_model=IndependentEvidenceVerificationModel,
)

app = FastAPI(
    title="Face-Web-Blockchain Pipeline",
    description=(
        "Upload a face image; the pipeline reverse-searches the web, matches "
        "the face against candidates (via thumbnail and page-content evidence "
        "tiers), fingerprints the best match, and can register the hash on a "
        "blockchain for tamper-evident attestation."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes (registered before the static mount so they take precedence).
app.include_router(router)
app.include_router(evidence_router)
app.include_router(chain_router)


@app.get("/api/health")
def health() -> dict:
    return {"service": "Face-Web-Blockchain Pipeline", "status": "ok"}


# Serve the static frontend when SERVE_FRONTEND is enabled (single-port mode).
_SERVE_FRONTEND = os.environ.get("SERVE_FRONTEND", "true").lower() in (
    "1",
    "true",
    "yes",
)
_FRONTEND_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend"
)
if _SERVE_FRONTEND and os.path.isdir(_FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
