"""Evidence engine: scoring, consensus, passports, and explanations."""

from backend.evidence.models import (
    EvidencePassport,
    EvidenceScore,
    MatchExplanation,
    ScoredCandidate,
    SourceInfo,
    TimelineEvent,
)
from backend.evidence.passport import build_passport
from backend.evidence.scorer import compute_evidence_score
from backend.evidence.explain import build_explanation

__all__ = [
    "EvidencePassport",
    "EvidenceScore",
    "MatchExplanation",
    "ScoredCandidate",
    "SourceInfo",
    "TimelineEvent",
    "build_passport",
    "build_explanation",
    "compute_evidence_score",
]
