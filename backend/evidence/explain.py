"""Build truthful 'Why this match?' explanations."""

from __future__ import annotations

from backend.evidence.models import MatchExplanation, ProviderConsensus, SourceInfo


def build_explanation(
    *,
    face_similarity: float,
    threshold: float,
    evidence_tier: str,
    source: SourceInfo,
    consensus: ProviderConsensus,
    is_match: bool,
    image_similarity: float | None = None,
) -> MatchExplanation:
    """Only include reasons that are actually true."""
    reasons: list[str] = []

    if not is_match:
        if face_similarity > 0:
            reasons.append(
                f"Face similarity ({face_similarity:.1%}) below configured threshold ({threshold:.1%})"
            )
        else:
            reasons.append("No face match detected in candidate image")
        return MatchExplanation(reasons=reasons)

    if face_similarity > 0:
        reasons.append("Face detected in source image")
    if face_similarity >= threshold:
        reasons.append("Face similarity exceeded configured threshold")
    if source.image_retrieved:
        reasons.append("Source image successfully retrieved")
    if evidence_tier == "verified":
        reasons.append("Source page successfully verified")
        reasons.append("Search result corresponds to source page content image")
    elif evidence_tier == "thumbnail":
        reasons.append("Match based on search-engine thumbnail (page not fully verified)")
    if image_similarity is not None and image_similarity >= 0.9:
        reasons.append("High image similarity between retrieved sources")
    if consensus.providers_available > 1 and consensus.provider_count > 1:
        reasons.append(
            f"Multiple search providers returned this source ({consensus.provider_consensus})"
        )
    elif consensus.provider_count == 1 and consensus.providers_available == 1:
        reasons.append("Single configured search provider returned this source")
    if source.source_type == "social" and evidence_tier == "verified":
        plat = "X" if source.platform in ("x", "twitter") else source.platform.title()
        reasons.append(f"Verified as a matching public {plat} source")
    elif source.source_type == "social" and evidence_tier == "thumbnail":
        plat = "X" if source.platform in ("x", "twitter") else source.platform.title()
        reasons.append(
            f"Social-media URL identified ({plat}); page content not independently verified"
        )
    elif source.source_type == "wiki":
        reasons.append("Source classified as reference/wiki page, not a social-media post")
    elif source.source_type == "reference":
        reasons.append("Source classified as reference/news page, not a social-media post")

    return MatchExplanation(reasons=reasons)
