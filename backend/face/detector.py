"""Face detection: bounding boxes, landmarks and confidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from backend.face.model import get_face_model, read_image


@dataclass
class FaceDetection:
    """A single detected face."""

    bbox: list[float] = field(default_factory=list)
    confidence: float = 0.0
    landmarks: list[list[float]] = field(default_factory=list)
    embedding: np.ndarray | None = None

    @property
    def width(self) -> float:
        if len(self.bbox) < 4:
            return 0.0
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> float:
        if len(self.bbox) < 4:
            return 0.0
        return self.bbox[3] - self.bbox[1]

    @property
    def area(self) -> float:
        return self.width * self.height


def detect_faces(image: str | np.ndarray) -> list[FaceDetection]:
    """Detect all faces in an image.

    Args:
        image: file path or BGR numpy array.

    Returns:
        A list of FaceDetection objects, each with bbox/landmarks/confidence
        and a 512-d embedding.
    """
    if isinstance(image, str):
        image = read_image(image)

    model = get_face_model()
    raw = model.app.get(image)
    detections: list[FaceDetection] = []

    for face in raw:
        lm = face.landmark_2d_106
        if lm is None:
            lm = face.landmark_3d_68 if hasattr(face, "landmark_3d_68") else None
        emb = getattr(face, "normed_embedding", None)
        if emb is None:
            emb = face.embedding if face.embedding is not None else None
        det = FaceDetection(
            bbox=[float(x) for x in face.bbox],
            confidence=float(face.det_score),
            landmarks=[[float(x) for x in pt] for pt in lm] if lm is not None else [],
            embedding=emb,
        )
        detections.append(det)

    return detections


def extract_face(image: str | np.ndarray) -> FaceDetection | None:
    """Detect the primary face in an image.

    Uses the largest, highest-confidence face. Returns None when no face is
    found.
    """
    detections = detect_faces(image)
    if not detections:
        return None
    # Prefer highest confidence, break ties by size.
    return max(detections, key=lambda d: (d.confidence, d.area))