"""Small shared helpers for the blockchain layer."""

from __future__ import annotations


def validate_record_hash(record_hash: str) -> str:
    """Normalize + validate a 64-char SHA-256 hex digest."""
    record_hash = (record_hash or "").strip().lower()
    if len(record_hash) != 64:
        raise ValueError("record hash must be a 64-char SHA-256 hex digest")
    try:
        bytes.fromhex(record_hash)
    except ValueError as exc:
        raise ValueError("record hash must be hexadecimal") from exc
    return record_hash