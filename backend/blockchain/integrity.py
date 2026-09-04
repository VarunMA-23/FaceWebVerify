"""Integrity re-verification: compare current evidence vs blockchain-attested hash."""

from __future__ import annotations

from backend.fingerprint.canonicalizer import EvidenceRecord
from backend.fingerprint.hasher import fingerprint


def compute_current_hash(record: EvidenceRecord) -> str:
    """Recompute SHA-256 from a canonical evidence record."""
    return fingerprint(record)


def verify_integrity(attested_hash: str, current_hash: str, on_chain: bool) -> dict:
    """Compare attested vs current fingerprint."""
    if not attested_hash:
        return {
            "integrity_verified": False,
            "status": "unavailable",
            "message": "No blockchain-attested fingerprint stored for this job.",
            "blockchain_hash": None,
            "current_hash": current_hash or None,
            "match": False,
            "on_chain": on_chain,
        }
    if not current_hash:
        return {
            "integrity_verified": False,
            "status": "unavailable",
            "message": "Could not recompute current evidence fingerprint.",
            "blockchain_hash": attested_hash,
            "current_hash": None,
            "match": False,
            "on_chain": on_chain,
        }
    match = attested_hash.lower() == current_hash.lower()
    if match and on_chain:
        return {
            "integrity_verified": True,
            "status": "verified",
            "message": "Current evidence matches blockchain-attested fingerprint.",
            "blockchain_hash": attested_hash,
            "current_hash": current_hash,
            "match": True,
            "on_chain": on_chain,
        }
    return {
        "integrity_verified": False,
        "status": "changed",
        "message": "Current evidence does not match the blockchain-attested fingerprint.",
        "blockchain_hash": attested_hash,
        "current_hash": current_hash,
        "match": False,
        "on_chain": on_chain,
    }
