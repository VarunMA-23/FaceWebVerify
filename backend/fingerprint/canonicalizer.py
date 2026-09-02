"""Build a canonical JSON record from discovered content."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

SCHEMA_VERSION = "1"


@dataclass
class ContentRecord:
    """Canonical, hash-ready content record."""

    schema_version: str = SCHEMA_VERSION
    post_url: str = ""
    image_sha256: str = ""
    caption: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    platform: str = ""
    title: str = ""
    #: Evidence tier (verified/thumbnail) describing how the match was made.
    #: Kept in the hashed record so the on-chain attestation is honest about
    #: the strength of evidence behind it.
    evidence: str = ""

    def canonical_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "post_url": (self.post_url or "").strip(),
            "image_sha256": (self.image_sha256 or "").strip(),
            "caption": (self.caption or "").strip(),
            "timestamp": (self.timestamp or "").strip(),
            "platform": (self.platform or "").strip(),
            "title": (self.title or "").strip(),
            "evidence": (self.evidence or "").strip(),
        }

    def canonical_json(self, sort_keys: bool = True) -> str:
        """Serialize to a canonical JSON string for hashing."""
        return json.dumps(
            self.canonical_dict(),
            sort_keys=sort_keys,
            separators=(",", ":"),
            ensure_ascii=False,
        )


def image_sha256(image_bytes: bytes) -> str:
    """SHA-256 hex digest of raw image bytes."""
    return hashlib.sha256(image_bytes).hexdigest()


def image_sha256_from_file(path: str) -> str:
    """SHA-256 hex digest of a local image file (Unicode-safe)."""
    with open(path, "rb") as fh:
        return image_sha256(fh.read())