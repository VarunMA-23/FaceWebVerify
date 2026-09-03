"""Evidence score computation (0-100) with configurable weights."""

from __future__ import annotations

from backend.evidence.consensus import provider_consensus_label
from backend.evidence.models import EvidenceScore, ProviderConsensus, SourceInfo

# Configurable weights — must sum to 100 max contribution
WEIGHTS = {
    "face_similarity": 40,
    "image_similarity": 25,
    "source_verified": 15,
    "provider_consensus": 10,
    "metadata_consistency": 4,
    "social_source_bonus": 6,
}

MAX_SCORE = sum(WEIGHTS.values())


def compute_evidence_score(
    *,
    face_similarity: float,
    image_similarity: float | None,
    evidence_tier: str,
    source: SourceInfo,
    consensus: ProviderConsensus,
    has_title: bool,
    has_caption: bool,
) -> EvidenceScore:
    """Compute weighted evidence score from available signals only."""
    breakdown: dict[str, int] = {}

    # A. Face similarity (scaled 0-weight max)
    if face_similarity > 0:
        breakdown["face_similarity"] = round(
            min(WEIGHTS["face_similarity"], face_similarity * WEIGHTS["face_similarity"])
        )

    # B. Image similarity (only when actually computed)
    if image_similarity is not None and image_similarity > 0:
        breakdown["image_similarity"] = round(
            min(WEIGHTS["image_similarity"], image_similarity * WEIGHTS["image_similarity"])
        )

    # C. Source page verification
    if evidence_tier == "verified" and source.page_retrieved:
        breakdown["source_verified"] = WEIGHTS["source_verified"]
    elif evidence_tier == "thumbnail" and source.image_retrieved:
        breakdown["source_verified"] = WEIGHTS["source_verified"] // 2

    # D. Provider consensus (only when multiple providers available)
    if consensus.providers_available > 1 and consensus.provider_count > 0:
        fraction = consensus.provider_count / consensus.providers_available
        breakdown["provider_consensus"] = round(
            min(WEIGHTS["provider_consensus"], fraction * WEIGHTS["provider_consensus"])
        )

    # E. Metadata consistency
    meta_points = 0
    if has_title:
        meta_points += 2
    if has_caption:
        meta_points += 2
    if source.page_retrieved:
        meta_points += 1
    if meta_points:
        breakdown["metadata_consistency"] = min(WEIGHTS["metadata_consistency"], meta_points)

    # F. Social source classification (bonus only for genuine social URLs)
    if source.source_type == "social" and evidence_tier in ("verified", "thumbnail"):
        breakdown["social_source_bonus"] = WEIGHTS["social_source_bonus"]

    total = min(MAX_SCORE, sum(breakdown.values()))
    return EvidenceScore(total=total, breakdown=breakdown, max_score=MAX_SCORE)


def build_provider_consensus(
    providers: list[str],
    providers_available: int,
) -> ProviderConsensus:
    count = len(providers)
    label = provider_consensus_label(count, providers_available)
    score = count / providers_available if providers_available > 1 else 0.0
    return ProviderConsensus(
        providers=list(providers),
        provider_count=count,
        providers_available=providers_available,
        provider_consensus=label,
        consensus_score=round(score, 3),
    )
