"""Face quality assessment for the pipeline.

Provides a lightweight, dependency-free quality score for a detected face
before it is sent to the reverse-image search providers.  A low-quality
face (blurry, too small, too few landmarks) wastes API quota and tends to
return noisy or irrelevant results.

The module is intentionally *non-blocking*: a low quality score is logged
as a timeline warning but never stops the pipeline.  Callers receive a
:class:`FaceQuality` object they can inspect and attach to metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np


# Minimum side-length of the face bounding-box (pixels) for a reliable match.
MIN_FACE_SIDE_PX: int = 48

# Minimum Laplacian variance (after normalisation to 0-255) considered sharp.
MIN_SHARPNESS: float = 50.0

# InsightFace buffalo_l provides 5 facial landmarks; fewer suggests a very
# poor detection.
MIN_LANDMARK_COUNT: int = 5


@dataclass
class FaceQuality:
    """Quality assessment result for a single detected face.

    Attributes
    ----------
    score:
        Aggregate quality score in [0, 1].  Higher is better.
    sharpness:
        Laplacian variance of the face crop, normalised to [0, 1].
    size_score:
        Face bounding-box size score in [0, 1].
    landmark_score:
        1.0 when all expected landmarks are present, else proportional.
    warnings:
        Human-readable list of quality issues (empty when score ≥ 0.7).
    """

    score: float = 0.0
    sharpness: float = 0.0
    size_score: float = 0.0
    landmark_score: float = 0.0
    warnings: list[str] = field(default_factory=list)

    @property
    def is_acceptable(self) -> bool:
        """True when the face is good enough for reliable matching."""
        return self.score >= 0.4

    def summary(self) -> str:
        grade = "good" if self.score >= 0.7 else ("acceptable" if self.score >= 0.4 else "poor")
        return (
            f"quality={self.score:.2f} ({grade}), "
            f"sharpness={self.sharpness:.2f}, "
            f"size={self.size_score:.2f}, "
            f"landmarks={self.landmark_score:.2f}"
        )


def assess_quality(face: object, full_image: np.ndarray | None = None) -> FaceQuality:
    """Assess the quality of a detected *face* object.

    Parameters
    ----------
    face:
        An InsightFace ``Face`` object (or any object with ``.bbox`` and
        optional ``.kps`` / ``.landmark_2d_106`` attributes).
    full_image:
        The full BGR image array from which *face* was detected.  When
        provided, the face crop is used for sharpness measurement.  When
        ``None`` only the bbox-based size score is computed.

    Returns
    -------
    FaceQuality
    """
    warnings: list[str] = []

    # ── 1. Bounding-box size score ──────────────────────────────────────
    bbox = getattr(face, "bbox", None) or []
    size_score = 0.0
    if len(bbox) >= 4:
        x1, y1, x2, y2 = bbox[:4]
        w, h = abs(float(x2 - x1)), abs(float(y2 - y1))
        side = min(w, h)
        if side < MIN_FACE_SIDE_PX:
            warnings.append(
                f"Face too small ({int(side)}px min-side; recommend ≥{MIN_FACE_SIDE_PX}px)"
            )
        # Score rises from 0 at 0px to 1 at 2× the minimum
        size_score = min(1.0, side / (MIN_FACE_SIDE_PX * 2))
    else:
        warnings.append("No bounding box available")

    # ── 2. Sharpness (Laplacian variance on face crop) ──────────────────
    sharpness = 0.0
    if full_image is not None and len(bbox) >= 4:
        try:
            x1, y1, x2, y2 = [int(v) for v in bbox[:4]]
            h_img, w_img = full_image.shape[:2]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w_img, x2), min(h_img, y2)
            crop = full_image[y1:y2, x1:x2]
            if crop.size > 0:
                gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop
                lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
                # Normalise: 0 → score 0, MIN_SHARPNESS → score 0.5, 4×MIN → score 1
                sharpness = min(1.0, lap_var / (MIN_SHARPNESS * 4))
                if lap_var < MIN_SHARPNESS:
                    warnings.append(
                        f"Face appears blurry (Laplacian variance={lap_var:.1f}; "
                        f"recommend ≥{MIN_SHARPNESS:.0f})"
                    )
        except Exception:  # noqa: BLE001
            sharpness = 0.5  # unknown — assume neutral

    # ── 3. Landmark score ───────────────────────────────────────────────
    landmark_score = 1.0
    kps = getattr(face, "kps", None)
    if kps is None:
        kps = getattr(face, "landmark_2d_106", None)
    if kps is None:
        kps = getattr(face, "landmarks", None)
    if kps is None:
        # No landmark data at all
        landmark_score = 0.5
        warnings.append("Facial landmarks not available")
    else:
        n_kps = len(kps)
        if n_kps < MIN_LANDMARK_COUNT:
            landmark_score = n_kps / MIN_LANDMARK_COUNT
            warnings.append(f"Only {n_kps} landmarks detected (expect ≥{MIN_LANDMARK_COUNT})")

    # ── 4. Detection confidence (det_score / confidence) ────────────────
    det_score_val = getattr(face, "det_score", None)
    if det_score_val is None:
        det_score_val = getattr(face, "confidence", 1.0)
    det_score = float(det_score_val or 1.0)
    # det_score from InsightFace is already in [0, 1]

    # ── 5. Aggregate ────────────────────────────────────────────────────
    # Weights chosen so that a large, sharp, well-detected face scores ≥ 0.85.
    # If the full_image was not provided, sharpness is 0 — we skip its weight.
    if full_image is not None:
        aggregate = (
            size_score * 0.30
            + sharpness * 0.30
            + landmark_score * 0.20
            + det_score * 0.20
        )
    else:
        aggregate = (
            size_score * 0.40
            + landmark_score * 0.30
            + det_score * 0.30
        )

    return FaceQuality(
        score=round(min(1.0, max(0.0, aggregate)), 4),
        sharpness=round(sharpness, 4),
        size_score=round(size_score, 4),
        landmark_score=round(landmark_score, 4),
        warnings=warnings,
    )
