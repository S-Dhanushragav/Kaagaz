"""Frame quality: sharpness, edge contact, visibility, and choosing the best frames per document."""

from dataclasses import dataclass

import cv2
import numpy as np

SHARPNESS_LONG_SIDE = 512


def sharpness(image: np.ndarray, long_side: int = SHARPNESS_LONG_SIDE) -> float:
    """Variance of the Laplacian, measured at a fixed size so crops of different sizes compare fairly."""
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    s = long_side / max(h, w)
    gray = cv2.resize(gray, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def touches_edge(box: tuple[float, float, float, float], size: tuple[int, int], margin: float = 3.0) -> bool:
    """True if the box comes within `margin` px of the frame border (document probably cut off)."""
    x1, y1, x2, y2 = box
    w, h = size
    return x1 <= margin or y1 <= margin or x2 >= w - margin or y2 >= h - margin


def visible_estimate(area: float, reference_area: float) -> float:
    """How much of the document is in view: its area relative to its largest unclipped area."""
    return float(min(1.0, area / reference_area)) if reference_area > 0 else 0.0


@dataclass
class Candidate:
    frame: int  # source frame index
    time_s: float
    sharpness: float


def select_frames(candidates: list[Candidate], k: int = 3, min_gap_s: float = 0.5) -> list[Candidate]:
    """Up to k sharpest candidates that are at least `min_gap_s` apart in time (best first)."""
    chosen: list[Candidate] = []
    for c in sorted(candidates, key=lambda c: c.sharpness, reverse=True):
        if all(abs(c.time_s - o.time_s) >= min_gap_s for o in chosen):
            chosen.append(c)
            if len(chosen) == k:
                break
    return chosen
