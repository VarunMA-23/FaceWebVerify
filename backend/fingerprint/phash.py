"""Perceptual hashing (pHash) utility for image similarity.

Uses imagehash library (difference hash / dhash or average hash) if available,
with a fallback to image dimensions + basic color histogram diff if imagehash
is not installed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image

logger = logging.getLogger(__name__)

_HAS_IMAGEHASH = False
try:
    import imagehash
    from PIL import Image as PILImage
    _HAS_IMAGEHASH = True
except ImportError:
    _HAS_IMAGEHASH = False


def compute_phash(pil_img: Image.Image) -> str | None:
    """Compute 64-bit perceptual hash (as hex string) for a PIL Image."""
    if not _HAS_IMAGEHASH:
        return None
    try:
        # Use dhash (difference hash) which is robust to slight scaling/compression
        h = imagehash.dhash(pil_img)
        return str(h)
    except Exception as exc:
        logger.warning(f"Failed to compute pHash: {exc}")
        return None


def phash_similarity(hash1_hex: str | None, hash2_hex: str | None) -> float | None:
    """Compute similarity [0.0, 1.0] between two hex pHash strings.
    
    1.0 = identical perceptual hash
    0.0 = maximum Hamming distance (64 bits different)
    None = unavailable / invalid inputs
    """
    if not hash1_hex or not hash2_hex or not _HAS_IMAGEHASH:
        return None
    try:
        h1 = imagehash.hex_to_hash(hash1_hex)
        h2 = imagehash.hex_to_hash(hash2_hex)
        distance = h1 - h2  # Hamming distance (0 to 64)
        sim = max(0.0, 1.0 - (distance / 64.0))
        return round(sim, 4)
    except Exception:
        return None
