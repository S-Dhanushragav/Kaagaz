"""Upright crops: which way is up on a document crop.

Two steps, both deterministic (no model call):
1. Geometry (`frame_aligned_corners`): of the 4 ways to label a quad's corners, take the one whose top edge is
   closest to horizontal, so the warp never turns the document by more than 45 degrees.
2. Text (`text_rotation`): a document shown sideways in the frame (e.g. a landscape page on a laptop screen filmed
   with a portrait phone) is still sideways after step 1. Text lines are found by smearing dark pixels along each
   axis; the axis with long thin blobs is the text direction. Which of the two ends is up comes from the Devanagari
   headline (shirorekha): each word's darkest row is its top line. Every document here carries Marathi text.
A 180-degree turn is only made when the headline evidence is overwhelming (FLIP_MARGIN): on blurry, low-resolution
crops the headline test is noisy, and an upright crop wrongly turned over is worse than one left alone. Several
crops of the same document (video frames) are judged together and turned the same way.
"""

from dataclasses import dataclass

import cv2
import numpy as np

ANALYSIS_LONG_SIDE = 1000
SIDEWAYS_RATIO = 1.5  # vertical text blobs must outweigh horizontal ones by this much
FLIP_MARGIN = 0.6  # up-share difference needed to turn a crop upside down. Measured (Phase 9c) on 34 upright
# crops from a real phone video and HH009: wrong-way differences reached 0.41; really upside-down text gives ~0.76.
MIN_TEXT_PIXELS = 300  # smear-blob area below this: no text found, leave the crop alone


def frame_aligned_corners(quad: np.ndarray) -> np.ndarray:
    """Clockwise corners (TL, TR, BR, BL) relabelled so the top edge (TL -> TR) points most nearly right.

    `quad` must already be in clockwise order (as from `order_corners`). Ties (exactly 45 degrees) go to the
    labelling whose top-left is nearest the image origin.
    """
    quad = np.asarray(quad, float).reshape(4, 2)

    def key(i: int) -> tuple[float, float]:
        edge = quad[(i + 1) % 4] - quad[i]
        cos = edge[0] / (np.linalg.norm(edge) + 1e-9)
        return (round(cos, 6), -float(quad[i].sum()))

    start = max(range(4), key=key)
    return np.roll(quad, -start, axis=0)


def _binarize(image: np.ndarray) -> np.ndarray:
    """Dark ink as 1s at a fixed size, with long ruled lines (tables, borders) removed."""
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    s = ANALYSIS_LONG_SIDE / max(gray.shape[:2])
    gray = cv2.resize(gray, None, fx=s, fy=s, interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    ink = cv2.adaptiveThreshold(gray, 1, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 15)
    h, w = ink.shape
    lines = (cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(1, w // 6), 1)))
             | cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(1, h // 6)))))
    return cv2.subtract(ink, lines)


def _line_area(ink: np.ndarray, horizontal: bool) -> float:
    """Area of blobs that are long and thin along the axis after smearing along it (text lines)."""
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 1) if horizontal else (1, 15))
    _, _, stats, _ = cv2.connectedComponentsWithStats(cv2.dilate(ink, kernel))
    total = 0.0
    for _, _, w, h, area in stats[1:]:
        along, across = (w, h) if horizontal else (h, w)
        if area >= 30 and along >= 3 * across:
            total += area
    return total


def _up_share(ink: np.ndarray) -> float | None:
    """For horizontal text: share of words (by width) whose darkest row is in their upper part. None: no words."""
    _, _, stats, _ = cv2.connectedComponentsWithStats(cv2.dilate(ink, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 1))))
    up = down = 0.0
    for x, y, w, h, _ in stats[1:]:
        if h < 8 or h > 80 or w < 2 * h:
            continue
        profile = ink[y:y + h, x:x + w].sum(axis=1).astype(float)
        if profile.max() < 1.8 * (np.median(profile) + 1):
            continue
        peak = np.argmax(profile) / (h - 1)
        if peak < 0.4:
            up += w
        elif peak > 0.6:
            down += w
    return up / (up + down) if up + down > 0 else None


@dataclass
class Orientation:
    turns: int  # quarter turns clockwise that make the crop upright (0-3)
    sideways: bool  # the text ran vertically before turning
    scores: dict[str, float]


def text_rotation(*images: np.ndarray) -> Orientation:
    """Quarter turns that make the text upright. Several images (crops of one document) are judged together."""
    inks = [_binarize(im) for im in images]
    horizontal = sum(_line_area(ink, True) for ink in inks)
    vertical = sum(_line_area(ink, False) for ink in inks)
    scores = {"horizontal": horizontal, "vertical": vertical}
    if max(horizontal, vertical) < MIN_TEXT_PIXELS * len(inks):
        return Orientation(0, False, scores)
    sideways = vertical > SIDEWAYS_RATIO * horizontal
    # Candidate pair: as is / upside down, or a quarter turn either way.
    first, second = (1, 3) if sideways else (0, 2)

    def up(turns: int) -> float:
        shares = [_up_share(np.ascontiguousarray(np.rot90(ink, k=-turns))) for ink in inks]
        known = [x for x in shares if x is not None]
        return float(np.mean(known)) if known else 0.5

    a, b = up(first), up(second)
    scores.update({f"up_{first * 90}": a, f"up_{second * 90}": b})
    if not sideways:  # upright unless clearly upside down
        return Orientation(2 if b - a >= FLIP_MARGIN else 0, False, scores)
    return Orientation(first if a >= b else second, True, scores)


def rotate_quarters(image: np.ndarray, turns: int) -> np.ndarray:
    turns %= 4
    if turns == 0:
        return image
    return cv2.rotate(image, {1: cv2.ROTATE_90_CLOCKWISE, 2: cv2.ROTATE_180, 3: cv2.ROTATE_90_COUNTERCLOCKWISE}[turns])


def make_upright(image: np.ndarray) -> tuple[np.ndarray, Orientation]:
    o = text_rotation(image)
    return rotate_quarters(image, o.turns), o
