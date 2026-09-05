"""Independent re-verification: recompute the fingerprint from the persisted
passport and re-run the anchor backend's per-check verification.

This is the tamper-evidence guarantee: if any persisted evidence or chain data
was modified, at least one check FAILs and the report names the broken link.
"""

from __future__ import annotations

import json

from backend.blockchain.checks import Check, checks_to_dicts
from backend.fingerprint.canonicalizer import EvidenceRecord
from backend.fingerprint.hasher import fingerprint, fingerprint_from_canonical_json


def recompute_current_hash(passport: dict) -> str:
    """Recompute the current fingerprint from the persisted passport."""
    evidence_record = passport.get("evidence_record") or {}
    canonical_json = passport.get("canonical_json") or ""
    if evidence_record:
        try:
            record = EvidenceRecord(**evidence_record)
        except TypeError:
            record = None
        if record is not None:
            return fingerprint(record)
    if canonical_json:
        return fingerprint_from_canonical_json(canonical_json)
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
    return fingerprint(record)


def _receipt_from_record(bc: dict) -> dict:
    backend = bc.get("backend") or "evm"
    from backend.blockchain import config

    ref: dict = {
        "tx_hash": bc.get("transaction_hash") or "",
        "block_hash": bc.get("block_hash") or "",
        "merkle_root": bc.get("merkle_root") or "",
        "leaf_index": bc.get("leaf_index"),
        "block_index": bc.get("block_number"),
    }
    if backend == "local":
        # Prefer the chain root persisted with the record; fall back to the
        # current configured root so reverify for an older/custom chain_dir
        # still checks the ledger that actually anchored the record.
        ref["chain_root"] = str(
            bc.get("chain_root") or config.get_chain_dir() / "local"
        )
    return {
        "backend": backend,
        "network": bc.get("network") or "",
        "record_hash": bc.get("content_hash") or "",
        "idempotent_hit": bool(bc.get("idempotent")),
        "ref": ref,
        "block_index": bc.get("block_number"),
        "block_hash": bc.get("block_hash") or "",
        "merkle_root": bc.get("merkle_root") or "",
        "leaf_index": bc.get("leaf_index"),
        "merkle_proof": json.loads(bc.get("merkle_proof_json") or "[]"),
    }


def reverify_job(job_id: str, db) -> dict:
    """Re-verify a finished job end to end and return a per-check report."""
    meta = db.get_job_metadata(job_id) or {}
    passport = dict(meta.get("passport") or {})
    bc = db.get_blockchain_record(job_id) or {}
    checks: list[Check] = []

    attested_hash = (bc or {}).get("content_hash") or passport.get("content_hash") or ""

    current_hash = ""
    if passport:
        try:
            current_hash = recompute_current_hash(passport)
        except Exception as exc:  # noqa: BLE001
            checks.append(
                Check(
                    name="evidence.self_consistent",
                    ok=False,
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )
        else:
            checks.append(
                Check(
                    name="evidence.self_consistent",
                    ok=bool(current_hash),
                    detail="fingerprint recomputed from persisted evidence",
                )
            )
    else:
        checks.append(
            Check(name="evidence.self_consistent", ok=False, detail="no passport stored for job")
        )

    if attested_hash and current_hash:
        checks.append(
            Check(
                name="evidence.hash_matches_attested",
                ok=attested_hash.lower() == current_hash.lower(),
                expected=attested_hash,
                actual=current_hash,
            )
        )
    elif attested_hash:
        checks.append(
            Check(
                name="evidence.hash_matches_attested",
                ok=False,
                detail="could not recompute current fingerprint",
            )
        )

    if attested_hash and bc:
        from backend.blockchain.verifier import verify_record

        checks.extend(verify_record(attested_hash, _receipt_from_record(bc)))
    else:
        checks.append(
            Check(
                name=f"{(bc or {}).get('backend') or 'none'}.record",
                ok=False,
                detail="no on-chain record stored for this job",
            )
        )

    return {
        "job_id": job_id,
        "overall_verified": bool(checks) and all(c.ok for c in checks),
        "attested_hash": attested_hash,
        "current_hash": current_hash,
        "backend": (bc or {}).get("backend") or "",
        "network": (bc or {}).get("network") or "",
        "checks": checks_to_dicts(checks),
    }