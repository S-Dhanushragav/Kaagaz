"""Image prep for LLM calls: downscale to ~1024 px on the long side and encode as JPEG."""

from pathlib import Path

import cv2
import numpy as np

LLM_LONG_SIDE = 1024
JPEG_QUALITY = 85


def read_image(path: str | Path) -> np.ndarray:
    """Read an image file as a BGR array (works with non-ASCII Windows paths)."""
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Could not decode image: {path}")
    return image


def encode_for_llm(
    image: np.ndarray, long_side: int = LLM_LONG_SIDE, jpeg_quality: int = JPEG_QUALITY
) -> bytes:
    """Downscale so the long side is at most `long_side` px and return JPEG bytes.

    Smaller images are not upscaled. Accepts grayscale, BGR, or BGRA arrays.
    """
    if image is None or image.size == 0:
        raise ValueError("Empty image")
    if image.ndim == 3 and image.shape[2] == 4:
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

    h, w = image.shape[:2]
    scale = long_side / max(h, w)
    if scale < 1:
        size = (max(1, round(w * scale)), max(1, round(h * scale)))
        image = cv2.resize(image, size, interpolation=cv2.INTER_AREA)

    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
    if not ok:
        raise ValueError("JPEG encoding failed")
    return buf.tobytes()
