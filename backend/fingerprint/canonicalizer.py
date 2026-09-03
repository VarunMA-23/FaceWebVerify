"""Build a canonical JSON record from discovered content."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

SCHEMA_VERSION = "1.0"
LEGACY_SCHEMA_VERSION = "1"


@dataclass
class ContentRecord:
    """Canonical, hash-ready content record (legacy v1)."""

    schema_version: str = LEGACY_SCHEMA_VERSION
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


@dataclass
class EvidenceRecord:
    """Phase 1 canonical evidence record (schema v1.0)."""

    schema_version: str = SCHEMA_VERSION
    evidence_id: str = ""
    source_url: str = ""
    canonical_url: str = ""
    platform: str = ""
    source_type: str = ""
    discovered_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    face_similarity: float = 0.0
    image_similarity: float | None = None
    evidence_tier: str = ""
    image_sha256: str = ""
    caption: str = ""
    title: str = ""
    providers: list[str] = field(default_factory=list)
    provider_consensus: str = ""
    evidence_score: int = 0
    verification_reasons: list[str] = field(default_factory=list)

    def canonical_dict(self) -> dict:
        d: dict = {
            "schema_version": self.schema_version,
            "evidence_id": (self.evidence_id or "").strip(),
            "source_url": (self.source_url or "").strip(),
            "canonical_url": (self.canonical_url or "").strip(),
            "platform": (self.platform or "").strip(),
            "source_type": (self.source_type or "").strip(),
            "discovered_at": (self.discovered_at or "").strip(),
            "face_similarity": round(float(self.face_similarity), 6),
            "evidence_tier": (self.evidence_tier or "").strip(),
            "image_sha256": (self.image_sha256 or "").strip(),
            "caption": (self.caption or "").strip(),
            "title": (self.title or "").strip(),
            "providers": sorted(self.providers),
            "provider_consensus": (self.provider_consensus or "").strip(),
            "evidence_score": int(self.evidence_score),
            "verification_reasons": sorted(self.verification_reasons),
        }
        if self.image_similarity is not None:
            d["image_similarity"] = round(float(self.image_similarity), 6)
        return d

    def canonical_json(self, sort_keys: bool = True) -> str:
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