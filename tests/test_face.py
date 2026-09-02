"""Tests for face detection and embedding (Module 2)."""

import os

import pytest

from backend.face.detector import detect_faces, extract_face
from backend.face.embedder import embed_face, embedding_to_list
from backend.face.matcher import cosine_similarity

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

FACES = {
    "einstein.jpg": {"faces": 1, "min_conf": 0.5},
    "lena.jpg": {"faces": 1, "min_conf": 0.5},
    "lincoln.jpg": {"faces": 1, "min_conf": 0.5},
    "marx.jpg": {"faces": 1, "min_conf": 0.5},
    "smith.jpg": {"faces": 1, "min_conf": 0.5},
}


def _paths():
    for name, meta in FACES.items():
        path = os.path.join(FIXTURES, name)
        if os.path.exists(path):
            yield path, meta


@pytest.mark.parametrize(
    "path,meta",
    [(p, m) for p, m in _paths()],
    ids=[os.path.basename(p) for p, m in _paths()],
)
def test_detect_one_face_each(path, meta):
    """Each fixture should yield one high-confidence face.""" 
    dets = detect_faces(path)
    assert len(dets) == meta["faces"]
    assert dets[0].confidence >= meta["min_conf"]
    assert len(dets[0].bbox) == 4
    assert dets[0].area > 0


@pytest.mark.parametrize(
    "path",
    [p for p, _ in _paths()],
    ids=[os.path.basename(p) for p, _ in _paths()],
)
def test_embeddings_shape_and_range(path):
    """Each embedding is 512-d with reasonable float values."""
    face = embed_face(path)
    assert face is not None
    assert face.embedding is not None
    assert face.embedding.shape == (512,)
    emb_list = embedding_to_list(face.embedding)
    assert len(emb_list) == 512
    assert all(-1.0 <= v <= 1.0 for v in emb_list[:5])


def test_no_face_detected():
    """A blank white image must yield no faces."""
    import numpy as np

    blank = np.full((128, 128, 3), 255, dtype=np.uint8)
    assert detect_faces(blank) == []
    assert extract_face(blank) is None


def test_same_person_high_similarity():
    """Two crops of the same image should match strongly."""
    first = embed_face(os.path.join(FIXTURES, "lenna.jpg")
                       if os.path.exists(os.path.join(FIXTURES, "lenna.jpg"))
                       else os.path.join(FIXTURES, "lena.jpg"))
    second = embed_face(os.path.join(FIXTURES, "lena.jpg"))
    assert first is not None and second is not None
    assert first.embedding is not None and second.embedding is not None
    score = cosine_similarity(first.embedding, second.embedding)
    assert score > 0.8


def test_cosine_similarity_math():
    import numpy as np

    a = np.array([1.0, 0.0, 0.0])
    b = np.array([0.0, 1.0, 0.0])
    assert abs(cosine_similarity(a, a) - 1.0) < 1e-9
    assert abs(cosine_similarity(a, b)) < 1e-9