"""Canonical serialization helpers for byte-stable hashing.

The canonical JSON form used for content/evidence fingerprints and the local
Merkle chain must produce identical bytes on every machine and Python version:
sorted keys, compact separators, UTF-8. Floats are excluded from hashed records
(they are converted to integers, e.g. parts-per-million) so hashing is exact.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_bytes(obj: Any) -> bytes:
    """Serialize ``obj`` to deterministic, byte-stable canonical JSON."""
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    """SHA-256 hex digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def to_ppm(value: float) -> int:
    """Convert a float similarity score to integer parts-per-million."""
    return int(round(float(value) * 1_000_000))