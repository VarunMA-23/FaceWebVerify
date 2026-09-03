"""Tests for CaseDir output-artifact manager."""

import json

import cv2
import numpy as np
import pytest

from backend.output import CaseDir


@pytest.fixture
def case_dir(tmp_path):
    return CaseDir(base=str(tmp_path), case_id="case-test-abc123")


def test_create_dir(case_dir, tmp_path):
    assert case_dir.path.exists()
    assert case_dir.path.is_dir()
    assert case_dir.path == tmp_path / "case-test-abc123"


def test_make_id_unique():
    a = CaseDir._make_id()
    b = CaseDir._make_id()
    assert a != b
    assert a.startswith("case-")


def test_save_input(case_dir):
    dest = case_dir.save_input(b"\xff\xd8\xff\xe0", "photo.jpg")
    assert dest.exists()
    assert dest.read_bytes() == b"\xff\xd8\xff\xe0"
    # unsafe name is sanitised
    dest2 = case_dir.save_input(b"x", "../../../evil.png")
    assert ".." not in dest2.name
    assert dest2.exists()


def _fake_face(bbox, conf=0.9):
    class _F:
        def __init__(self):
            self.bbox = bbox
            self.confidence = conf

    return _F()


def test_save_annotated(case_dir, tmp_path):
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    faces = [_fake_face([10, 10, 20, 20])]
    dest = case_dir.save_annotated(img, faces, label="probe")
    assert dest.exists()
    assert dest.name == "probe_annotated.jpg"
    loaded = cv2.imread(str(dest))
    assert loaded.shape == img.shape


def test_save_match_bytes(case_dir):
    dest = case_dir.save_match_bytes(b"imagedata")
    assert dest.name == "match.jpg"
    assert dest.read_bytes() == b"imagedata"


def test_save_match_artifacts(case_dir):
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    faces = [_fake_face([10, 10, 20, 20])]
    a = case_dir.save_match_annotated(img, faces)
    assert a.name == "match_annotated.jpg"


def test_save_evidence(case_dir):
    bundle = {"schema": "1", "match": {"url": "x"}}
    dest = case_dir.save_evidence(bundle)
    assert dest.name == "evidence.json"
    assert json.loads(dest.read_text(encoding="utf-8")) == bundle


def test_save_receipt(case_dir):
    rec = {"tx_hash": "0x", "block": 5}
    dest = case_dir.save_receipt(rec)
    assert dest.name == "receipt.json"
    assert json.loads(dest.read_text(encoding="utf-8")) == rec
