"""Mask -> outline -> 4-corner shape -> perspective warp to an upright crop.

Falls back to the minimum-area rectangle when no clean 4-corner shape is found.
Corner order everywhere: top-left, top-right, bottom-right, bottom-left.
"""

from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np

Method = Literal["quad", "min_area_rect"]


@dataclass
class DeskewResult:
    crop: np.ndarray
    quad: np.ndarray  # (4, 2) in the image the crop was cut from
    method: Method


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
            quad = order_corners(approx.reshape(4, 2))
            # Reject shapes that cut off or overshoot the region noticeably.
            if hull_area > 0 and 0.92 <= cv2.contourArea(quad.astype(np.float32)) / hull_area <= 1.08:
                return quad, "quad"
            break
    return order_corners(cv2.boxPoints(cv2.minAreaRect(hull))), "min_area_rect"


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


def deskew(image: np.ndarray, mask: np.ndarray) -> DeskewResult:
    """Find the document in `mask` and cut it from `image` as an upright crop.

    `mask` may be smaller than `image` (e.g. segmenter run on a downscaled copy); the corners are
    scaled up so the crop is cut from the full-resolution image.
    """
    quad, method = quad_from_mask(mask)
    sx, sy = image.shape[1] / mask.shape[1], image.shape[0] / mask.shape[0]
    quad = quad * [sx, sy]
    return DeskewResult(crop=warp_quad(image, quad), quad=quad, method=method)
