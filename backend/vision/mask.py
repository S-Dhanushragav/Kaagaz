"""Hiding identity numbers on document images before they are shown in the app (thumbnails).

- `valid_boxes`: keep only sensible normalized boxes (x0, y0, x1, y1 in 0-1) from the vision model's reply.
- `blur_boxes`: pixelate and blur each box, with padding (the model's boxes are approximate).
- `preview`: a coarse, unreadable version of a whole document, for documents whose type is not known yet.
"""

from typing import Any

import cv2
import numpy as np

Box = tuple[float, float, float, float]
MAX_BOX_AREA = 0.4  # a box covering more than this of the document is not a number
PAD_X, PAD_Y = 0.15, 0.6  # padding as a fraction of the box's own width / height
THUMB_LONG_SIDE = 480


def valid_boxes(raw: Any) -> list[Box]:
    """Boxes from the model's reply ([{x0, y0, x1, y1}, ...]), clamped to the image; malformed ones dropped."""
    out: list[Box] = []
    for b in raw if isinstance(raw, list) else []:
        try:
            x0, y0, x1, y1 = (float(b[k]) for k in ("x0", "y0", "x1", "y1"))
        except (KeyError, TypeError, ValueError):
            continue
        x0, x1 = sorted((min(max(x0, 0.0), 1.0), min(max(x1, 0.0), 1.0)))
        y0, y1 = sorted((min(max(y0, 0.0), 1.0), min(max(y1, 0.0), 1.0)))
        if x1 - x0 < 0.02 or y1 - y0 < 0.005 or (x1 - x0) * (y1 - y0) > MAX_BOX_AREA:
            continue
        out.append((x0, y0, x1, y1))
    return out


def _pixelate(region: np.ndarray, cell: int) -> np.ndarray:
    h, w = region.shape[:2]
    small = cv2.resize(region, (max(1, w // cell), max(1, h // cell)), interpolation=cv2.INTER_AREA)
    coarse = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
    k = max(3, (min(h, w) // 2) | 1)
    return cv2.GaussianBlur(coarse, (k, k), 0)


def blur_boxes(image: np.ndarray, boxes: list[Box]) -> np.ndarray:
    """A copy of `image` with each box (padded) made unreadable."""
    out = image.copy()
    h, w = out.shape[:2]
    for x0, y0, x1, y1 in boxes:
        bw, bh = (x1 - x0) * w, (y1 - y0) * h
        left, right = int(max(0, x0 * w - PAD_X * bw)), int(min(w, x1 * w + PAD_X * bw))
        top, bottom = int(max(0, y0 * h - PAD_Y * bh)), int(min(h, y1 * h + PAD_Y * bh))
        if right > left and bottom > top:
            region = out[top:bottom, left:right]
            out[top:bottom, left:right] = _pixelate(region, cell=max(4, (bottom - top) // 2))
    return out


def preview(image: np.ndarray) -> np.ndarray:
    """The whole document reduced to coarse blocks: its shape and colours, no readable text."""
    return _pixelate(image, cell=max(8, max(image.shape[:2]) // 24))


def thumbnail_jpeg(image: np.ndarray, long_side: int = THUMB_LONG_SIDE, quality: int = 80) -> bytes:
    scale = long_side / max(image.shape[:2])
    if scale < 1:
        image = cv2.resize(image, (round(image.shape[1] * scale), round(image.shape[0] * scale)),
                           interpolation=cv2.INTER_AREA)
    ok, jpeg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("could not encode the thumbnail")
    return jpeg.tobytes()
