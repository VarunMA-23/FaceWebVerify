"""Pydantic response models for the EvidenceChain API."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ScoreBreakdown(BaseModel):
    face_similarity: int = 0
    image_similarity: int = 0
    source_verified: int = 0
    provider_consensus: int = 0
    metadata_consistency: int = 0
    social_source_bonus: int = 0


class PostSummary(BaseModel):
    """A discovered candidate post enriched with evidence metadata."""

    url: str = ""
    image_url: str = ""
    platform: str = ""
    domain: str = ""
    source_type: str = ""
    title: str = ""
    caption: str = ""
    similarity: float = 0.0
    image_similarity: Optional[float] = None
    evidence_tier: str = ""
    evidence_score: int = 0
    score_breakdown: dict[str, int] = Field(default_factory=dict)
    provider_count: int = 0
    providers: list[str] = Field(default_factory=list)
    provider_consensus: str = ""
    social_handle: str = ""
    evidence_tier_label: str = ""
    explanation: list[str] = Field(default_factory=list)
    matched: bool = False
    rank: int = 0


class BlockchainSummary(BaseModel):
    content_hash: str = ""
    tx_hash: str = ""
    block_number: Optional[int] = None
    verified: bool = False
    network: str = "Ethereum Sepolia"
    error: Optional[str] = None


class SearchSummary(BaseModel):
    candidates_found: int = 0
    face_matches: int = 0
    verified_sources: int = 0
    social_sources: int = 0
    providers_used: list[str] = Field(default_factory=list)
    providers_available: int = 0
    provider_consensus: str = ""
    provider_errors: dict[str, str] = Field(default_factory=dict)
    best_evidence_score: int = 0


class TimelineStep(BaseModel):
    step: str
    label: str
    status: str = "waiting"
    timestamp: str = ""
    detail: str = ""


class EvidencePassportModel(BaseModel):
    evidence_id: str = ""
    source_platform: str = ""
    source_url: str = ""
    canonical_url: str = ""
    source_type: str = ""
    discovered_at: str = ""
    face_similarity: float = 0.0
    image_similarity: Optional[float] = None
    evidence_tier: str = ""
    provider_count: int = 0
    providers: list[str] = Field(default_factory=list)
    provider_consensus: str = ""
    evidence_score: int = 0
    score_breakdown: dict[str, int] = Field(default_factory=dict)
    social_handle: str = ""
    evidence_tier_label: str = ""
    verification_reasons: list[str] = Field(default_factory=list)
    content_hash: str = ""
    blockchain_network: str = ""
    tx_hash: str = ""
    block_number: Optional[int] = None
    registered_at: str = ""
    integrity_status: str = "pending"


class SearchResponseModel(BaseModel):
    job_id: str
    status: str
    provider: str = ""
    providers_used: list[str] = Field(default_factory=list)
    providers_available: int = 0
    provider_errors: dict[str, str] = Field(default_factory=dict)
    face_detected: bool = False
    face_confidence: float = 0.0
    candidates_seen: int = 0
    match_found: bool = False
    matched_post: Optional[PostSummary] = None
    passport: Optional[EvidencePassportModel] = None
    summary: Optional[SearchSummary] = None
    timeline: list[TimelineStep] = Field(default_factory=list)
    blockchain: Optional[BlockchainSummary] = None
    error: Optional[str] = None
    candidates: list[PostSummary] = Field(default_factory=list)


class VerifyResponseModel(BaseModel):
    job_id: str
    verified: bool = False
    on_chain: bool = False
    hash_matches: bool = False
    content_hash: Optional[str] = None
    tx_hash: Optional[str] = None
    error: Optional[str] = None


class IntegrityResponseModel(BaseModel):
    job_id: str
    integrity_verified: bool = False
    status: str = "unknown"  # verified | changed | unavailable
    message: str = ""
    blockchain_hash: Optional[str] = None
    current_hash: Optional[str] = None
    match: bool = False
    on_chain: bool = False
    details: dict[str, Any] = Field(default_factory=dict)
