"""Build Evidence Passport from pipeline results."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from backend.evidence.models import EvidencePassport, ScoredCandidate
from backend.evidence.source import platform_display_name


def build_passport(
    candidate: ScoredCandidate,
    *,
    evidence_id: str | None = None,
    content_hash: str = "",
    blockchain_network: str = "",
    tx_hash: str = "",
    block_number: int | None = None,
    registered_at: str = "",
) -> EvidencePassport:
    """Assemble the final evidence passport for the best candidate."""
    integrity = "pending"
    if content_hash and tx_hash:
        integrity = "attested"
    elif content_hash and not tx_hash:
        integrity = "fingerprinted"

    return EvidencePassport(
        evidence_id=evidence_id or uuid.uuid4().hex[:16],
        source_platform=platform_display_name(candidate.source.platform),
        source_url=candidate.source.source_url,
        canonical_url=candidate.source.canonical_url,
        source_type=candidate.source.source_type,
        discovered_at=datetime.now(timezone.utc).isoformat(),
        face_similarity=candidate.face_similarity,
        image_similarity=candidate.image_similarity,
        evidence_tier=candidate.evidence_tier,
        provider_count=candidate.consensus.provider_count,
        providers=candidate.consensus.providers,
        provider_consensus=candidate.consensus.provider_consensus,
        evidence_score=candidate.evidence_score.total,
        score_breakdown=dict(candidate.evidence_score.breakdown),
        verification_reasons=list(candidate.explanation.reasons),
        content_hash=content_hash,
        blockchain_network=blockchain_network,
        tx_hash=tx_hash,
        block_number=block_number,
        registered_at=registered_at,
        integrity_status=integrity,
    )
