"""Evidence layer data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SourceInfo:
    """Classification of a discovered source."""

    source_url: str = ""
    canonical_url: str = ""
    domain: str = ""
    platform: str = ""
    source_type: str = "web"  # social | web | wiki | reference | thumbnail
    page_retrieved: bool = False
    image_retrieved: bool = False


@dataclass
class ProviderConsensus:
    """Multi-provider agreement for a candidate URL."""

    providers: list[str] = field(default_factory=list)
    provider_count: int = 0
    providers_available: int = 0
    provider_consensus: str = ""  # e.g. "2/3" or "1 provider available"
    consensus_score: float = 0.0  # 0-1 fraction of providers agreeing


@dataclass
class EvidenceScore:
    """Weighted evidence score breakdown (0-100)."""

    total: int = 0
    breakdown: dict[str, int] = field(default_factory=dict)
    max_score: int = 100


@dataclass
class MatchExplanation:
    """Human-readable reasons why a candidate matched."""

    reasons: list[str] = field(default_factory=list)


@dataclass
class ScoredCandidate:
    """A candidate enriched with evidence metadata."""

    source: SourceInfo = field(default_factory=SourceInfo)
    consensus: ProviderConsensus = field(default_factory=ProviderConsensus)
    face_similarity: float = 0.0
    image_similarity: float | None = None
    evidence_tier: str = "none"
    evidence_score: EvidenceScore = field(default_factory=EvidenceScore)
    explanation: MatchExplanation = field(default_factory=MatchExplanation)
    title: str = ""
    caption: str = ""
    image_url: str = ""
    is_match: bool = False
    rank: int = 0


@dataclass
class TimelineEvent:
    """A single pipeline stage event."""

    step: str
    label: str
    status: str = "waiting"  # waiting | processing | success | warning | failed
    timestamp: str = ""
    detail: str = ""


@dataclass
class EvidencePassport:
    """Final attestation bundle for the strongest verified candidate."""

    evidence_id: str = ""
    source_platform: str = ""
    source_url: str = ""
    canonical_url: str = ""
    source_type: str = ""
    discovered_at: str = ""
    face_similarity: float = 0.0
    image_similarity: float | None = None
    evidence_tier: str = ""
    provider_count: int = 0
    providers: list[str] = field(default_factory=list)
    provider_consensus: str = ""
    evidence_score: int = 0
    score_breakdown: dict[str, int] = field(default_factory=dict)
    verification_reasons: list[str] = field(default_factory=list)
    content_hash: str = ""
    blockchain_network: str = ""
    tx_hash: str = ""
    block_number: int | None = None
    registered_at: str = ""
    integrity_status: str = "pending"  # pending | attested | unavailable

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source_platform": self.source_platform,
            "source_url": self.source_url,
            "canonical_url": self.canonical_url,
            "source_type": self.source_type,
            "discovered_at": self.discovered_at,
            "face_similarity": self.face_similarity,
            "image_similarity": self.image_similarity,
            "evidence_tier": self.evidence_tier,
            "provider_count": self.provider_count,
            "providers": self.providers,
            "provider_consensus": self.provider_consensus,
            "evidence_score": self.evidence_score,
            "score_breakdown": self.score_breakdown,
            "verification_reasons": self.verification_reasons,
            "content_hash": self.content_hash,
            "blockchain_network": self.blockchain_network,
            "tx_hash": self.tx_hash,
            "block_number": self.block_number,
            "registered_at": self.registered_at,
            "integrity_status": self.integrity_status,
        }
