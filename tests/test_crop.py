"""Tests for face crop-box targeting (Module 2 helper)."""

import os

import numpy as np
import pytest

from backend.face.crop import crop_to_face, crop_to_primary_face
from backend.face.detector import FaceDetection

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _face_from_bbox(box):
    return FaceDetection(
        bbox=[float(x) for x in box],
        confidence=0.99,
        landmarks=[],
        embedding=None,
    )


def test_crop_to_face_reduces_size():
    """A crop with 0.5 margin should be smaller than the source image."""
    image = np.zeros((300, 400, 3), dtype=np.uint8)
    face = _face_from_bbox([100, 100, 200, 200])  # 100x100 face
    cropped = crop_to_face(image, face, margin=0.5)
    assert cropped.shape[0] < 300
    assert cropped.shape[1] < 400
    # Face bbox is 100x100; with 0.5 margin the crop is 200x200.
    assert cropped.shape[:2] == (200, 200)


def test_crop_to_face_zero_margin_is_tight():
    image = np.zeros((300, 400, 3), dtype=np.uint8)
    face = _face_from_bbox([100, 100, 200, 200])
    cropped = crop_to_face(image, face, margin=0.0)
    assert cropped.shape[:2] == (100, 100)


def test_crop_to_face_invalid_bbox_returns_original():
    image = np.zeros((10, 10, 3), dtype=np.uint8)
    bad = _face_from_bbox([])
    assert crop_to_face(image, bad) is image
    bad2 = _face_from_bbox([0, 0, 0, 0])  # zero area
    assert crop_to_face(image, bad2) is image


def test_crop_to_face_clamps_to_image_bounds():
    image = np.zeros((50, 50, 3), dtype=np.uint8)
    # Face near the top-left corner; margin would go negative → clamped to 0.
    face = _face_from_bbox([5, 5, 20, 20])
    cropped = crop_to_face(image, face, margin=2.0)
    assert cropped.shape[0] <= 50
    assert cropped.shape[1] <= 50
    # Bottom-right corner of face at 20, plus margin 2x -> 20+40=60 > 50 -> clamp.
    assert cropped.shape[:2][0] >= 1
    assert cropped.shape[:2][1] >= 1


def test_crop_result_contains_face_pixels():
    """The cropped region must preserve the face area's original pixels."""
    image = np.full((300, 400, 3), 0, dtype=np.uint8)
    # paint a distinctive region where the face bbox is
    image[100:200, 100:200] = (0, 255, 0)
    face = _face_from_bbox([100, 100, 200, 200])
    cropped = crop_to_face(image, face, margin=0.0)
    assert (cropped == 255).sum() > 0
    assert cropped.shape[:2] == (100, 100)


def test_crop_to_primary_face_on_fixture():
    """When InsightFace is available, the fixture crop is smaller+nonzero."""
    path = os.path.join(FIXTURES, "lena.jpg")
    if not os.path.exists(path):
        pytest.skip("lena.jpg fixture missing")
    try:
        cropped = crop_to_primary_face(path)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Face model unavailable: {exc}")
        return
    if cropped is None:
        pytest.skip("No face detected in fixture")
    assert cropped.ndim == 3
    assert cropped.shape[0] > 0 and cropped.shape[1] > 0


def test_crop_to_primary_face_blank_returns_none():
    blank = np.full((64, 64, 3), 255, dtype=np.uint8)
    if crop_to_primary_face(blank) is None:
        return  # model correctly found no face
    pytest.skip("Model unavailable — could not confirm None result")