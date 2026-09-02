"""Pydantic response models for the API."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class PostSummary(BaseModel):
    """A discovered candidate post (whether or not it matched)."""

    url: str = ""
    image_url: str = ""
    platform: str = ""
    title: str = ""
    caption: str = ""
    similarity: float = 0.0
    evidence_tier: str = ""
    matched: bool = False


class BlockchainSummary(BaseModel):
    """Result of the on-chain register/verify step."""

    content_hash: str = ""
    tx_hash: str = ""
    block_number: Optional[int] = None
    verified: bool = False
    error: Optional[str] = None


class SearchResponseModel(BaseModel):
    """Full result for a job."""

    job_id: str
    status: str
    provider: str = ""
    face_detected: bool = False
    face_confidence: float = 0.0
    candidates_seen: int = 0
    match_found: bool = False
    matched_post: Optional[PostSummary] = None
    blockchain: Optional[BlockchainSummary] = None
    error: Optional[str] = None
    candidates: list[PostSummary] = []


class VerifyResponseModel(BaseModel):
    """Result of verifying a job's on-chain record."""

    job_id: str
    verified: bool = False
    on_chain: bool = False
    hash_matches: bool = False
    content_hash: Optional[str] = None
    tx_hash: Optional[str] = None
    error: Optional[str] = None
