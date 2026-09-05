"""Face crop-box targeting for reverse-image searches.

Reverse-image providers match whatever image they are given. Searching with a
whole photo (especially a group shot or a busy scene) lets background noise
dilute the visual match. Cropping to the face region focuses the search on the
subject, giving providers a stronger signal and reducing noise from irrelevant
content.

This mirrors the "crop-box targeting" offered by reverse-image APIs such as
Yandex: search *part* of an image (one face in a group photo) rather than the
whole frame.

Public API
----------
- :func:`crop_to_face` — crop a BGR image to a face bounding box with margin.
- :func:`crop_image_to_primary_face` — detect the primary face and crop to it.
"""

from __future__ import annotations

import numpy as np

from backend.face.detector import FaceDetection, detect_faces

#: Fraction of the face bbox width/height added around the face as margin.
#: A small margin keeps context (hair, neck) useful to the search engine;
#: too large a margin reintroduces background noise.
DEFAULT_FACE_MARGIN = 0.5


def _clamp_int(value: float, low: int, high: int) -> int:
    return int(max(low, min(high, value)))


def crop_to_face(
    image: np.ndarray,
    face: FaceDetection,
    margin: float = DEFAULT_FACE_MARGIN,
) -> np.ndarray:
    """Crop a BGR ``image`` to a face bounding box with ``margin`` padding.

    The face bbox is expanded by ``margin`` fractions of its own width/height
    on each side, then clamped to the image bounds. A ``margin`` of ``0.0``
    yields a tight crop exactly at the detection box.

    Args:
        image: BGR numpy array (as returned by :func:`read_image`).
        face: A :class:`FaceDetection` with a populated ``bbox``.
        margin: Fractional padding added around the face (default ``0.5``).

    Returns:
        A cropped BGR numpy array. If the face bbox is invalid/empty the
        original image is returned unchanged.
    """
    if len(face.bbox) < 4:
        return image

    h, w = image.shape[:2]
    x1, y1, x2, y2 = face.bbox[:4]
    fw = x2 - x1
    fh = y2 - y1

    if fw <= 0 or fh <= 0:
        return image

    pad_w = fw * margin
    pad_h = fh * margin

    cx = _clamp_int(x1 - pad_w, 0, w)
    cy = _clamp_int(y1 - pad_h, 0, h)
    c2x = _clamp_int(x2 + pad_w, 0, w)
    c2y = _clamp_int(y2 + pad_h, 0, h)

    if c2x <= cx or c2y <= cy:
        return image

    return image[cy:c2y, cx:c2x]


def crop_to_primary_face(
    image: str | np.ndarray,
    margin: float = DEFAULT_FACE_MARGIN,
) -> np.ndarray | None:
    """Crop ``image`` to its primary (largest, highest-confidence) face.

    Returns ``None`` when no face is detected (callers should fall back to the
    full image rather than failing).

    Args:
        image: file path or BGR numpy array.
        margin: Fractional padding around the face (default ``0.5``).

    Returns:
        A cropped BGR numpy array, or ``None`` if no face is present.
    """
    if isinstance(image, str):
        from backend.face.model import read_image

        image = read_image(image)

    faces = detect_faces(image)
    if not faces:
        return None

    primary = max(faces, key=lambda d: (d.confidence, d.area))
    return crop_to_face(image, primary, margin=margin)
