"""Mask -> outline -> 4-corner shape -> perspective warp -> upright crop.

Falls back to the minimum-area rectangle when no clean 4-corner shape is found.
Corner order everywhere: top-left, top-right, bottom-right, bottom-left. The corners are labelled so the warp
turns the document by at most 45 degrees; a document whose text still runs sideways (or upside down) is then
turned by quarter turns (see vision/orient.py).
"""

from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np

from vision.orient import frame_aligned_corners, rotate_quarters, text_rotation

Method = Literal["quad", "min_area_rect"]


@dataclass
class DeskewResult:
    crop: np.ndarray
    quad: np.ndarray  # (4, 2) in the image the crop was cut from; TL..BL of the upright crop
    method: Method
    turns: int = 0  # quarter turns clockwise applied after the warp to make the text upright


def order_corners(pts: np.ndarray) -> np.ndarray:
    """Sort 4 points clockwise starting at the top-left (smallest x + y)."""
    pts = np.asarray(pts, float).reshape(4, 2)
    centre = pts.mean(axis=0)
    clockwise = pts[np.argsort(np.arctan2(pts[:, 1] - centre[1], pts[:, 0] - centre[0]))]
    start = int(np.argmin(clockwise.sum(axis=1)))
    return np.roll(clockwise, -start, axis=0)


def quad_from_mask(mask: np.ndarray) -> tuple[np.ndarray, Method]:
    """4 corners of the largest region in a binary mask."""
    m = (mask > 0).astype(np.uint8)
    contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise ValueError("empty mask")
    hull = cv2.convexHull(max(contours, key=cv2.contourArea))
    hull_area = cv2.contourArea(hull)
    perimeter = cv2.arcLength(hull, True)
    for eps in (0.01, 0.02, 0.03, 0.05, 0.08):
        approx = cv2.approxPolyDP(hull, eps * perimeter, True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            quad = frame_aligned_corners(order_corners(approx.reshape(4, 2)))
            # Reject shapes that cut off or overshoot the region noticeably.
            if hull_area > 0 and 0.92 <= cv2.contourArea(quad.astype(np.float32)) / hull_area <= 1.08:
                return quad, "quad"
            break
    return frame_aligned_corners(order_corners(cv2.boxPoints(cv2.minAreaRect(hull)))), "min_area_rect"


def warp_quad(image: np.ndarray, quad: np.ndarray) -> np.ndarray:
    """Perspective-warp the quad (TL, TR, BR, BL) to an upright rectangle."""
    tl, tr, br, bl = quad.astype(np.float32)
    w = int(round(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))))
    h = int(round(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))))
    if w < 2 or h < 2:
        raise ValueError("quad too small to warp")
    dst = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
    M = cv2.getPerspectiveTransform(np.float32([tl, tr, br, bl]), dst)
    return cv2.warpPerspective(image, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def deskew(image: np.ndarray, mask: np.ndarray, *, upright: bool = True) -> DeskewResult:
    """Find the document in `mask` and cut it from `image` as an upright crop.

    `mask` may be smaller than `image` (e.g. segmenter run on a downscaled copy); the corners are
    scaled up so the crop is cut from the full-resolution image. upright=False skips the text check.
    """
    quad, method = quad_from_mask(mask)
    sx, sy = image.shape[1] / mask.shape[1], image.shape[0] / mask.shape[0]
    quad = quad * [sx, sy]
    crop = warp_quad(image, quad)
    turns = text_rotation(crop).turns if upright else 0
    # Turning the crop clockwise makes the old bottom-left corner the new top-left.
    return DeskewResult(crop=rotate_quarters(crop, turns), quad=np.roll(quad, turns, axis=0), method=method, turns=turns)
