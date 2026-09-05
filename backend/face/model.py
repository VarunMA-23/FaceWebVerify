"""Shared InsightFace runtime initialisation.

A single FaceAnalysis app is created lazily and reused across all face
operations to avoid reloading the model on every call.
"""

from __future__ import annotations

import os
import threading
from typing import Optional

import cv2
import numpy as np

_MODEL_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "models")


class FaceModel:
    """Lazy singleton wrapper around an InsightFace FaceAnalysis app."""

    def __init__(self, model_name: str = "buffalo_l", providers: Optional[list] = None) -> None:
        self.model_name = model_name
        self.det_thresh = 0.5
        self.det_size = (640, 640)
        self._providers = providers or ["CPUExecutionProvider"]
        self._app: object | None = None
        self._lock = threading.Lock()

    @property
    def app(self) -> object:
        if self._app is None:
            with self._lock:
                if self._app is None:
                    self._app = self._build()
        return self._app

    def _build(self) -> object:
        import insightface

        providers = self._providers
        try:
            ort_providers = onnxruntime_providers()
            if ort_providers:
                providers = ort_providers
        except Exception:
            pass
        return insightface.app.FaceAnalysis(
            name=self.model_name,
            root=_MODEL_ROOT,
            providers=providers,
            allowed_modules=["detection", "recognition"],
        )

    def prepare(self) -> None:
        self.app.prepare(ctx_id=0, det_thresh=self.det_thresh, det_size=self.det_size)


def onnxruntime_providers() -> list[str]:
    """Return ONNX Runtime providers ordered by preference.

    Hard accelerators (CUDA / TensorRT / DirectML / ROCm) are preferred when
    installed so machines with a GPU use it automatically, while machines
    without one safely fall back to CPU. ``AzureExecutionProvider`` is
    deliberately deprioritized (it is a local shim, not an accelerator).
    """
    import onnxruntime as ort

    try:
        available = set(ort.get_available_providers())
    except Exception:
        return []

    preferred = [
        "TensorrtExecutionProvider",
        "CUDAExecutionProvider",
        "ROCMExecutionProvider",
        "DmlExecutionProvider",
        "CoreMLExecutionProvider",
    ]
    ordered = [p for p in preferred if p in available]
    if not ordered:
        ordered = [p for p in available if p != "AzureExecutionProvider"]
    if "CPUExecutionProvider" not in ordered:
        ordered.append("CPUExecutionProvider")
    return ordered


# Prefer CPU for maximum compatibility; CUDA is used when available.
_DEFAULT_MODEL: FaceModel | None = None


def get_face_model() -> FaceModel:
    global _DEFAULT_MODEL
    if _DEFAULT_MODEL is None:
        _DEFAULT_MODEL = FaceModel()
        _DEFAULT_MODEL.prepare()
    return _DEFAULT_MODEL


def read_image(path: str) -> np.ndarray:
    """Read an image file into a BGR numpy array, tolerating Unicode paths."""
    data = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"Could not decode image: {path}")
    return img