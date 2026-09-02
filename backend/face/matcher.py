"""Face matching via cosine similarity between two embeddings."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np

from backend.face.detector import FaceDetection, detect_faces
from backend.face.embedder import embed_face

#: InsightFace cosine-similarity threshold above which two faces are
#: considered a match.
SIMILARITY_THRESHOLD = 0.4


class EvidenceTier(str, Enum):
    """Confidence tier of a face match, based on what evidence produced it.

    - ``verified``: matched against the real post content image (page crawl).
    - ``thumbnail``: matched against the search-engine thumbnail only
      (login-walled post whose page could not be crawled).
    - ``none``: no face match found.
    """

    VERIFIED = "verified"
    THUMBNAIL = "thumbnail"
    NONE = "none"


@dataclass
class FaceMatch:
    """Result of matching a reference face against a candidate image set."""

    is_match: bool
    score: float
    face: FaceDetection | None
    tier: EvidenceTier = EvidenceTier.NONE
    source: str = "image"  # e.g. 'thumbnail' or 'page'
    image_url: str = ""
    page_url: str = ""


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two embeddings, in [-1, 1]."""
    a = np.asarray(a, dtype=np.float64).ravel()
    b = np.asarray(b, dtype=np.float64).ravel()
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def match_embeddings(
    reference: np.ndarray,
    candidate: np.ndarray,
    threshold: float = SIMILARITY_THRESHOLD,
) -> tuple[bool, float]:
    """Compare reference vs candidate embedding.

    Returns (is_match, cosine_similarity).
    """
    score = cosine_similarity(reference, candidate)
    return score >= threshold, score


def match_image_to_embedding(
    reference_embedding: np.ndarray,
    candidate_image: str,
    threshold: float = SIMILARITY_THRESHOLD,
    tier: EvidenceTier = EvidenceTier.VERIFIED,
    source: str = "image",
    image_url: str = "",
    page_url: str = "",
) -> FaceMatch:
    """Match a reference embedding against EVERY face in a candidate image.

    Unlike the primary-face-only approach, this compares against all detected
    faces and returns the single best score — important because thumbnails and
    page images often contain multiple people.

    Returns a :class:`FaceMatch` with the best (is_match, score, face).
    """
    best_face = None
    best_score = 0.0
    best_is_match = False
    for det in detect_faces(candidate_image):
        if det.embedding is None:
            continue
        is_match, score = match_embeddings(reference_embedding, det.embedding, threshold)
        if score > best_score:
            best_score = score
            best_is_match = is_match
            best_face = det

    return FaceMatch(
        is_match=best_is_match,
        score=best_score,
        face=best_face,
        tier=tier,
        source=source,
        image_url=image_url,
        page_url=page_url,
    )


def best_of(
    matches: list[FaceMatch],
    threshold: float = SIMILARITY_THRESHOLD,
) -> FaceMatch:
    """Combine multiple candidate-image matches into the single best result.

    The tier of the overall match is derived from the strongest evidence that
    produced a face above threshold.
    """
    if not matches:
        return FaceMatch(is_match=False, score=0.0, face=None)

    best = max(matches, key=lambda m: m.score)

    # Evidence tier: a verified (page-content) match always outranks a
    # thumbnail-only match at the same score; no match stays 'none'.
    strongest_tier = EvidenceTier.NONE
    for m in matches:
        if m.is_match:
            if strongest_tier is EvidenceTier.NONE:
                strongest_tier = m.tier
            elif strongest_tier == EvidenceTier.THUMBNAIL and m.tier == EvidenceTier.VERIFIED:
                strongest_tier = EvidenceTier.VERIFIED

    return FaceMatch(
        is_match=best.is_match,
        score=best.score,
        face=best.face,
        tier=strongest_tier if best.is_match else EvidenceTier.NONE,
        source=best.source,
        image_url=best.image_url,
        page_url=best.page_url,
    )


def best_match_from_embeddings(
    reference_embedding: np.ndarray,
    candidate_embeddings: list[np.ndarray],
    threshold: float = SIMILARITY_THRESHOLD,
) -> tuple[bool, float]:
    """Return the best match across a list of candidate embeddings."""
    best_score = 0.0
    best_hit = False
    for cand in candidate_embeddings:
        hit, score = match_embeddings(reference_embedding, cand, threshold)
        if score > best_score:
            best_score = score
            best_hit = hit
    return best_hit, best_score