"""Face embedding generation using InsightFace/ArcFace."""

from __future__ import annotations

import numpy as np

from backend.face.detector import FaceDetection, detect_faces
from backend.face.model import get_face_model, read_image


def embed_face(image: str | np.ndarray) -> FaceDetection | None:
    """Generate the 512-d embedding for the primary face in an image.

    Equivalent to ``detect_faces`` + selecting the best face; the embedding
    is attached to the returned FaceDetection.

    Args:
        image: file path or BGR numpy array.

    Returns:
        FaceDetection with a 512-d embedding, or None if no face is found.
    """
    if isinstance(image, str):
        image = read_image(image)

    dets = detect_faces(image)
    if not dets:
        return None

    best = max(dets, key=lambda d: (d.confidence, d.area))
    if best.embedding is None:
        best.embedding = _recompute_embedding(image, best)
    return best


def _recompute_embedding(image: np.ndarray, det: FaceDetection) -> np.ndarray:
    model = get_face_model()
    app = model.app
    bbox = [int(x) for x in det.bbox]
    if hasattr(app, "models"):
        for model_inst in app.models.values():
            if hasattr(model_inst, "get_feat") and hasattr(model_inst, "get"):
                return model_inst.get(image, bbox)
    raise RuntimeError("Could not recompute face embedding")


def embedding_to_list(embedding: np.ndarray) -> list[float]:
    """Serialize a raw numpy embedding to a plain Python list of floats."""
    return [float(x) for x in np.asarray(embedding).ravel()]