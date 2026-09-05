"""HTTP routes for EvidenceChain investigation API."""

from __future__ import annotations

import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from backend.api.schemas import (
    BlockchainSummary,
    ChainShowModel,
    ChainVerifyModel,
    CheckModel,
    EvidencePassportModel,
    IndependentEvidenceVerificationModel,
    IntegrityResponseModel,
    PostSummary,
    ReverifyResponseModel,
    SearchResponseModel,
    SearchSummary,
    TimelineStep,
    VerifyResponseModel,
)
from backend.evidence.source import (
    evidence_tier_label,
    extract_social_handle,
    normalize_platform,
    platform_display_name,
)
from backend.blockchain.backend import resolve_backend
from backend.blockchain.config import get_chain_dir, get_difficulty
from backend.blockchain.errors import BackendUnavailableError, ChainIntegrityError
from backend.blockchain.integrity import verify_integrity
from backend.blockchain.localchain import LocalChain
from backend.blockchain.reverify import reverify_job
from backend.blockchain.verifier import get_evidence_from_blockchain
from backend.blockchain.verifier import verify_evidence_on_blockchain
from backend.blockchain.verifier import verify_on_blockchain
from backend.database.models import Database
from backend.fingerprint.canonicalizer import EvidenceRecord
from backend.fingerprint.hasher import fingerprint
from backend.blockchain.registry import revoke_evidence_on_blockchain
from backend.blockchain.contract import get_contract_address
from backend.pipeline.runner import PipelineRunner

router = APIRouter(prefix="/search", tags=["search"])
chain_router = APIRouter(prefix="/chain", tags=["chain"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}

_executor = ThreadPoolExecutor(max_workers=2)


class JobAccepted(BaseModel):
    job_id: str
    status: str = "processing"


@router.get(
    "/evidence/{evidence_id}/verify",
    response_model=IndependentEvidenceVerificationModel,
)
def verify_independent_evidence(evidence_id: str) -> IndependentEvidenceVerificationModel:
    try:
        evidence = get_evidence_from_blockchain(evidence_id)
    except ValueError as exc:
        if "Evidence is not registered:" in str(exc):
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except (ConnectionError, OSError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    active = evidence["status"] == "active"
    return IndependentEvidenceVerificationModel(
        evidence_id=evidence_id,
        verified=active,
        on_chain=True,
        status=evidence["status"],
        content_hash=evidence["content_hash"],
        issuer=evidence["issuer"],
        timestamp=evidence["timestamp"],
        network="Ethereum Sepolia",
        contract_address=get_contract_address(),
    )


def _runner(db: Database | None = None, limit: int = 5, threshold: float = 0.4) -> PipelineRunner:
    do_bc = os.environ.get("DO_BLOCKCHAIN", "true").lower()
    enable = do_bc not in ("0", "false", "no", "off", "none")
    return PipelineRunner(db or Database(), limit=limit, threshold=threshold, do_blockchain=enable)


def _make_local_chain() -> LocalChain:
    return LocalChain(get_chain_dir() / "local", difficulty_bits=get_difficulty())


def _load_checks(bc: dict | None) -> list[dict]:
    if not bc:
        return []
    try:
        return json.loads(bc.get("checks_json") or "[]")
    except (ValueError, TypeError):
        return []


def get_db() -> Database:
    return Database()


def _post_from_row(p: dict, threshold: float = 0.4) -> PostSummary:
    meta = {}
    raw_meta = p.get("metadata_json") or ""
    if raw_meta:
        try:
            meta = json.loads(raw_meta)
        except json.JSONDecodeError:
            meta = {}
    providers = []
    raw_prov = p.get("providers_json") or ""
    if raw_prov:
        try:
            providers = json.loads(raw_prov)
        except json.JSONDecodeError:
            providers = []
    explanation = []
    raw_exp = p.get("explanation_json") or ""
    if raw_exp:
        try:
            explanation = json.loads(raw_exp)
        except json.JSONDecodeError:
            explanation = []
    sim = float(p.get("face_similarity") or 0)
    tier = p.get("evidence_tier") or ""
    platform = normalize_platform(p.get("platform") or "", p.get("post_url") or "")
    source_type = p.get("source_type") or ""
    url = p.get("post_url") or ""
    handle = meta.get("social_handle") or extract_social_handle(url, platform) or ""
    return PostSummary(
        url=url,
        image_url=p.get("image_url") or "",
        platform=platform_display_name(platform) if platform not in ("web", "") else (p.get("platform") or ""),
        domain=p.get("domain") or "",
        source_type=source_type,
        title=p.get("title") or "",
        caption=p.get("caption") or "",
        similarity=sim,
        image_similarity=meta.get("image_similarity"),
        evidence_tier=tier,
        evidence_tier_label=evidence_tier_label(tier, source_type),
        evidence_score=int(p.get("evidence_score") or 0),
        score_breakdown=meta.get("score_breakdown") or {},
        provider_count=int(p.get("provider_count") or 0),
        providers=providers,
        provider_consensus=meta.get("provider_consensus") or "",
        social_handle=handle,
        explanation=explanation,
        matched=sim >= threshold and tier in ("verified", "thumbnail") and bool(url),
        rank=int(meta.get("rank") or 0),
    )


@router.post("", response_model=JobAccepted)
async def create_search(
    file: UploadFile = File(...),
    limit: int = 5,
    threshold: float = 0.4,
    hint: str = "",
) -> JobAccepted:
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
    db.create_job(job_id, f"pending:{file.filename or 'upload.jpg'}")
    runner = _runner(db, limit=limit, threshold=threshold)
    _executor.submit(_run_job, runner, db, job_id, data, file.filename, limit, threshold, hint)
    return JobAccepted(job_id=job_id, status="processing")


def _run_job(
    runner: PipelineRunner,
    db: Database,
    job_id: str,
    data: bytes,
    filename: str,
    limit: int,
    threshold: float,
    hint: str = "",
) -> None:
    try:
        runner.limit = limit
        runner.threshold = threshold
        runner.run(data, filename or "upload.jpg", job_id=job_id, hint=hint)
    except Exception:  # noqa: BLE001
        db.update_job_status(job_id, "failed")


@router.get("/{job_id}", response_model=SearchResponseModel)
def get_search(job_id: str, db: Database = Depends(get_db)) -> SearchResponseModel:
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    meta = db.get_job_metadata(job_id)
    posts = db.get_posts(job_id)
    candidates = [_post_from_row(p) for p in posts]
    candidates.sort(
        key=lambda c: (
            c.matched,
            c.evidence_tier == "verified",
            c.similarity,
            c.evidence_score,
        ),
        reverse=True,
    )

    matched = [c for c in candidates if c.matched]
    matched_post = matched[0] if matched else None

    bc = db.get_blockchain_record(job_id)
    blockchain = None
    if bc:
        on_chain = False
        try:
            on_chain = verify_on_blockchain(
                bc["content_hash"],
                backend_name=bc.get("backend") or "evm",
            )
        except (ValueError, ConnectionError, BackendUnavailableError):
            on_chain = False
        blockchain = BlockchainSummary(
            content_hash=bc["content_hash"],
            tx_hash=bc["transaction_hash"] or None,
            block_number=bc["block_number"],
            verified=on_chain,
            backend=bc.get("backend") or "evm",
            network=bc.get("network") or "",
            block_hash=bc.get("block_hash") or "",
            idempotent=bool(bc.get("idempotent")),
            checks=_load_checks(bc),
        )

    passport_data = meta.get("passport") or {}
    if passport_data:
        plat = normalize_platform(passport_data.get("source_platform") or "")
        url = passport_data.get("source_url") or ""
        passport_data = dict(passport_data)
        passport_data["social_handle"] = passport_data.get("social_handle") or extract_social_handle(url, plat) or ""
        passport_data["evidence_tier_label"] = evidence_tier_label(
            passport_data.get("evidence_tier") or "",
            passport_data.get("source_type") or "",
        )
    passport = EvidencePassportModel(**passport_data) if passport_data else None
    summary_data = meta.get("summary") or {}
    summary = SearchSummary(**summary_data) if summary_data else None
    timeline = [TimelineStep(**t) for t in meta.get("timeline") or []]

    return SearchResponseModel(
        job_id=job_id,
        status=job["status"],
        provider=meta.get("provider") or "",
        providers_used=meta.get("providers_used") or [],
        providers_available=int(meta.get("providers_available") or 0),
        provider_errors=meta.get("provider_errors") or {},
        face_detected=bool(meta.get("face_confidence") or job["status"] != "failed"),
        face_confidence=float(meta.get("face_confidence") or 0),
        candidates_seen=len(candidates),
        match_found=bool(matched_post),
        matched_post=matched_post,
        passport=passport,
        summary=summary,
        timeline=timeline,
        blockchain=blockchain,
        error=meta.get("error") or None,
        candidates=candidates,
        case_dir=meta.get("case_dir") or "",
    )


@router.get("/{job_id}/verify", response_model=VerifyResponseModel)
def verify_search(job_id: str, db: Database = Depends(get_db)) -> VerifyResponseModel:
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
        on_chain = verify_on_blockchain(
            bc["content_hash"],
            backend_name=bc.get("backend") or "evm",
        )
    except (ValueError, ConnectionError, BackendUnavailableError):
        on_chain = False

    backend_name = bc.get("backend") or "evm"
    verified = on_chain and (backend_name != "evm" or bool(bc["transaction_hash"]))
    return VerifyResponseModel(
        job_id=job_id,
        verified=verified,
        on_chain=on_chain,
        hash_matches=on_chain,
        content_hash=bc["content_hash"],
        tx_hash=bc["transaction_hash"],
        backend=backend_name,
        network=bc.get("network") or "",
        block_hash=bc.get("block_hash") or "",
        idempotent_hit=bool(bc.get("idempotent")),
        checks=_load_checks(bc),
        merkle_root=bc.get("merkle_root") or "",
    )


@router.get("/{job_id}/reverify", response_model=ReverifyResponseModel)
def reverify_search(job_id: str, db: Database = Depends(get_db)) -> ReverifyResponseModel:
    """Recompute the fingerprint from persisted evidence and re-run all checks."""
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    try:
        report = reverify_job(job_id, db)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail=f"Re-verification failed: {exc}",
        ) from exc

    return ReverifyResponseModel(
        job_id=job_id,
        overall_verified=report["overall_verified"],
        attested_hash=report["attested_hash"],
        current_hash=report["current_hash"],
        backend=report["backend"],
        network=report["network"],
        checks=[
            CheckModel(**c) for c in report["checks"]
        ],
    )


@router.post("/{job_id}/evidence/{evidence_id}/revoke")
def revoke_evidence(job_id: str, evidence_id: str, db: Database = Depends(get_db)) -> dict:
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    evidence_attestation = db.get_evidence_attestation_record(job_id, evidence_id)
    if evidence_attestation is None:
        raise HTTPException(status_code=404, detail="Evidence attestation not found.")

    mode = os.environ.get("BLOCKCHAIN_EVM_MODE", "registry").lower()
    if mode not in ("registry", "calldata"):
        mode = "registry" if os.environ.get("SEPOLIA_CONTRACT_ADDRESS", "") else "calldata"
    if mode != "registry":
        raise HTTPException(
            status_code=409,
            detail=(
                "Evidence revocation requires EVM registry mode "
                "(BLOCKCHAIN_EVM_MODE=registry with a deployed contract)."
            ),
        )

    content_hash = evidence_attestation["content_hash"]
    try:
        evidence = get_evidence_from_blockchain(evidence_id)
    except (ValueError, ConnectionError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Blockchain evidence lookup failed: {exc}",
        ) from exc

    if evidence["content_hash"].lower().removeprefix("0x") != content_hash.lower().removeprefix("0x"):
        raise HTTPException(
            status_code=409,
            detail="On-chain evidence content hash does not match the stored attestation.",
        )
    if evidence["status"] != "active":
        raise HTTPException(status_code=409, detail="Evidence is not active.")

    try:
        tx_hash, block_number = revoke_evidence_on_blockchain(evidence_id)
    except (ValueError, ConnectionError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Blockchain evidence revocation failed: {exc}",
        ) from exc

    try:
        db.add_blockchain_record(
            job_id,
            content_hash,
            tx_hash,
            block_number,
            evidence_id=evidence_id,
            record_type="evidence_revocation",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "On-chain evidence revocation succeeded, but local persistence failed: "
                f"{exc}"
            ),
        ) from exc

    return {
        "job_id": job_id,
        "evidence_id": evidence_id,
        "status": "revoked",
        "tx_hash": tx_hash,
        "block_number": block_number,
    }


@router.get("/{job_id}/integrity", response_model=IntegrityResponseModel)
def verify_integrity_endpoint(job_id: str, db: Database = Depends(get_db)) -> IntegrityResponseModel:
    """Re-verify integrity: compare attested hash vs current evidence record."""
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    meta = db.get_job_metadata(job_id)
    passport = meta.get("passport") or {}
    bc = db.get_blockchain_record(job_id)
    backend_name = (bc or {}).get("backend") or "auto"
    attested = (bc or {}).get("content_hash") or passport.get("content_hash") or ""

    on_chain = False
    if attested:
        try:
            on_chain = verify_on_blockchain(attested, backend_name=backend_name)
        except (ValueError, ConnectionError, BackendUnavailableError):
            on_chain = False

    # Recompute from the persisted structured evidence record when available.
    evidence_record = passport.get("evidence_record") or {}
    canonical_json = passport.get("canonical_json") or ""
    current_hash = ""
    if evidence_record:
        record = EvidenceRecord(**evidence_record)
        current_hash = fingerprint(record)
    elif canonical_json:
        from backend.fingerprint.hasher import fingerprint_from_canonical_json
        current_hash = fingerprint_from_canonical_json(canonical_json)
    elif passport:
        record = EvidenceRecord(
            evidence_id=passport.get("evidence_id", ""),
            source_url=passport.get("source_url", ""),
            canonical_url=passport.get("canonical_url", ""),
            platform=passport.get("source_platform", ""),
            source_type=passport.get("source_type", ""),
            discovered_at=passport.get("discovered_at", ""),
            face_similarity=float(passport.get("face_similarity") or 0),
            image_similarity=passport.get("image_similarity"),
            evidence_tier=passport.get("evidence_tier", ""),
            providers=passport.get("providers") or [],
            provider_consensus=passport.get("provider_consensus", ""),
            evidence_score=int(passport.get("evidence_score") or 0),
            verification_reasons=passport.get("verification_reasons") or [],
        )
        current_hash = fingerprint(record)

    result = verify_integrity(attested, current_hash, on_chain)
    evidence_id = (evidence_record or {}).get("evidence_id") or passport.get("evidence_id") or ""
    evidence_attestation = None
    if evidence_id:
        evidence_attestation = db.get_evidence_attestation_record(job_id, evidence_id)

    details = {"evidence_id": evidence_id} if evidence_id else {}
    if evidence_attestation:
        evidence_content_hash = evidence_attestation["content_hash"]
        try:
            evidence_on_chain = verify_evidence_on_blockchain(
                evidence_id,
                evidence_content_hash,
            )
        except (ValueError, ConnectionError, BackendUnavailableError):
            evidence_on_chain = False
        evidence_hash_matches_current = bool(current_hash) and (
            evidence_content_hash.lower() == current_hash.lower()
        )
        details.update({
            "evidence_content_hash": evidence_content_hash,
            "evidence_verified": evidence_on_chain and evidence_hash_matches_current,
            "evidence_hash_matches_current": evidence_hash_matches_current,
            "evidence_on_chain": evidence_on_chain,
            "evidence_tx_hash": evidence_attestation.get("transaction_hash"),
            "evidence_block_number": evidence_attestation.get("block_number"),
        })
        try:
            on_chain_evidence = get_evidence_from_blockchain(evidence_id)
        except (ValueError, ConnectionError, BackendUnavailableError):
            on_chain_evidence = None
        if on_chain_evidence:
            details.update(
                {
                    "issuer": on_chain_evidence["issuer"],
                    "timestamp": on_chain_evidence["timestamp"],
                    "status": on_chain_evidence["status"],
                    "evidence_content_hash_on_chain": on_chain_evidence["content_hash"],
                    "evidence_on_chain_hash_matches_attestation": (
                        on_chain_evidence["content_hash"].lower()
                        == evidence_content_hash.lower()
                    ),
                }
            )
    elif evidence_id:
        details.update(
            {
                "evidence_verified": False,
                "evidence_hash_matches_current": False,
                "evidence_on_chain": False,
            }
        )

    result["details"] = details
    return IntegrityResponseModel(job_id=job_id, **result)


@router.get("/{job_id}/export")
def export_evidence(job_id: str, db: Database = Depends(get_db)) -> dict:
    """Export Evidence Passport as JSON (no biometric data)."""
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    meta = db.get_job_metadata(job_id)
    passport = meta.get("passport") or {}
    if not passport:
        raise HTTPException(status_code=404, detail="No evidence passport for this job.")
    export = {k: v for k, v in passport.items() if k not in ("canonical_json",)}
    export["schema_version"] = "1.0"
    export["exported_at"] = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ).isoformat()
    bc = db.get_blockchain_record(job_id)
    if bc:
        export["blockchain"] = {
            "content_hash": bc.get("content_hash"),
            "backend": bc.get("backend") or "evm",
            "transaction_hash": bc.get("transaction_hash"),
            "block_number": bc.get("block_number"),
            "network": bc.get("network") or "",
        }
    return export


@chain_router.get("/show", response_model=ChainShowModel)
def chain_show() -> ChainShowModel:
    """Render the local Merkle chain (block-by-block) for inspection."""
    chain = _make_local_chain()
    blocks = [
        {
            "index": b["index"],
            "hash": b["hash"],
            "prev_hash": b.get("prev_hash", ""),
            "timestamp": b.get("timestamp", ""),
            "merkle_root": b.get("merkle_root", ""),
            "difficulty": int(b.get("difficulty", 0)),
            "records": list(b.get("records", [])),
        }
        for b in chain.blocks()
    ]
    return ChainShowModel(
        chain_dir=str(chain.path),
        network=chain.network,
        blocks=blocks,
    )


@chain_router.get("/verify", response_model=ChainVerifyModel)
def chain_verify() -> ChainVerifyModel:
    """Verify the local Merkle chain from genesis to head."""
    chain = _make_local_chain()
    try:
        chain.verify_chain()
    except (ChainIntegrityError, OSError, ValueError) as exc:
        return ChainVerifyModel(ok=False, detail=f"CHAIN INTEGRITY: FAILED -- {exc}")
    return ChainVerifyModel(ok=True, detail="CHAIN INTEGRITY: OK")
