"""SHA-256 content fingerprinting over the canonical JSON record."""

from __future__ import annotations

import hashlib
from typing import Union

from backend.fingerprint.canonical import canonical_bytes
from backend.fingerprint.canonicalizer import ContentRecord, EvidenceRecord


def fingerprint(record: Union[ContentRecord, EvidenceRecord]) -> str:
    """Compute the tamper-evident SHA-256 hash of a content/evidence record."""
    return hashlib.sha256(canonical_bytes(record.canonical_dict())).hexdigest()


def fingerprint_from_canonical_json(canonical_json: str) -> str:
    """Hash an already-canonicalized JSON string."""
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()