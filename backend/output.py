"""Case directory manager for pipeline output artifacts.

Every pipeline run creates a ``out/case-<timestamp>-<embed8>/`` directory
containing all intermediate images, the evidence bundle, and the blockchain
receipt — everything needed to audit or re-verify the result later.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

OUT_DIR = Path(__file__).resolve().parent.parent / "out"


class CaseDir:
    """Manages the output directory for a single pipeline run."""

    def __init__(
        self,
        base: str | Path = OUT_DIR,
        case_id: str | None = None,
    ) -> None:
        self._base = Path(base)
        self._base.mkdir(parents=True, exist_ok=True)
        self._case_id = case_id or self._make_id()
        self._dir = self._base / self._case_id
        self._dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_id() -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        # Use a short random suffix to avoid collisions
        import uuid
        short = uuid.uuid4().hex[:8]
        return f"case-{ts}-{short}"

    @property
    def case_id(self) -> str:
        return self._case_id

    @property
    def path(self) -> Path:
        return self._dir

    def save_input(self, data: bytes, filename: str = "upload.jpg") -> Path:
        """Save the original uploaded image."""
        safe = Path(filename).name or "upload.jpg"
        dest = self._dir / f"input_{safe}"
        dest.write_bytes(data)
        return dest

    def save_annotated(
        self,
        image: np.ndarray,
        faces: list,
        label: str = "probe",
    ) -> Path:
        """Draw detection boxes on an image and save it.

        ``faces`` should be a list of objects with ``.bbox`` and ``.confidence``
        (i.e. :class:`FaceDetection` instances).
        """
        canvas = image.copy()
        for i, f in enumerate(faces):
            x, y, bw, bh = [int(v) for v in f.bbox[:4]]
            colour = (0, 220, 0) if i == 0 else (0, 170, 255)
            cv2.rectangle(canvas, (x, y), (x + bw, y + bh), colour, 2)
            score_text = f"{f.confidence:.2f}"
            cv2.putText(
                canvas,
                score_text,
                (x, max(14, y - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                colour,
                1,
                cv2.LINE_AA,
            )
        if label:
            cv2.putText(
                canvas,
                label,
                (8, 22),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
        dest = self._dir / f"{label}_annotated.jpg"
        cv2.imwrite(str(dest), canvas)
        return dest

    def save_match_bytes(self, data: bytes) -> Path:
        """Save the raw image bytes downloaded from the matched post."""
        dest = self._dir / "match.jpg"
        dest.write_bytes(data)
        return dest

    def save_match_annotated(
        self,
        image: np.ndarray,
        faces: list,
    ) -> Path:
        """Save the match image with detection boxes."""
        return self.save_annotated(image, faces, label="match")

    def save_evidence(self, bundle: dict) -> Path:
        """Write the canonical evidence bundle as JSON."""
        dest = self._dir / "evidence.json"
        dest.write_text(
            json.dumps(bundle, indent=1, ensure_ascii=False),
            encoding="utf-8",
        )
        return dest

    def save_receipt(self, receipt: dict) -> Path:
        """Write the blockchain transaction receipt."""
        dest = self._dir / "receipt.json"
        dest.write_text(
            json.dumps(receipt, indent=1, ensure_ascii=False),
            encoding="utf-8",
        )
        return dest

    def save_crop(self, image: np.ndarray, filename: str = "crop_face.jpg") -> Path:
        """Save a face-cropped copy of the input image (search artifact)."""
        dest = self._dir / filename
        cv2.imwrite(str(dest), image)
        return dest
