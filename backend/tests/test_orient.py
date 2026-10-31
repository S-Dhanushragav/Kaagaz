"""Upright crops: documents placed at different angles must come out of deskew with their text upright."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from vision.deskew import deskew
from vision.orient import frame_aligned_corners, rotate_quarters, text_rotation

ROOT = Path(__file__).resolve().parents[2]
DOCS = {
    "portrait": ROOT / "synthetic" / "households" / "HH001" / "caste_certificate_m1.png",  # 1000 x 1300
    "landscape": ROOT / "synthetic" / "households" / "HH001" / "identity_card_m1.png",  # 1012 x 638
    "table": ROOT / "synthetic" / "households" / "HH001" / "ration_card.png",  # 1100 x 742
}


def place(doc: np.ndarray, angle: float, canvas: int = 2200) -> tuple[np.ndarray, np.ndarray]:
    """The document turned `angle` degrees (counter-clockwise, as cv2) in the middle of a grey canvas, and its mask."""
    h, w = doc.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    m[:, 2] += (canvas / 2 - w / 2, canvas / 2 - h / 2)
    image = cv2.warpAffine(doc, m, (canvas, canvas), borderValue=(90, 90, 90))
    mask = cv2.warpAffine(np.full((h, w), 255, np.uint8), m, (canvas, canvas), flags=cv2.INTER_NEAREST)
    return image, mask


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    size = (200, 200)
    a = cv2.resize(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), size).astype(float)
    b = cv2.resize(cv2.cvtColor(b, cv2.COLOR_BGR2GRAY), size).astype(float)
    a, b = (a - a.mean()) / (a.std() + 1e-6), (b - b.mean()) / (b.std() + 1e-6)
    return float((a * b).mean())


# Known limit: upside down, the ration card's table weakens the headline evidence (difference 0.47 < FLIP_MARGIN), so
# it is left upside down rather than risk turning upright blurry crops over (see vision/orient.py).
UPSIDE_DOWN_LEFT = {"table"}


@pytest.mark.parametrize("kind", sorted(DOCS))
@pytest.mark.parametrize("angle", [0, 30, -30, 45, -45, 90, -90, 180])
def test_deskew_crop_is_upright(kind: str, angle: float) -> None:
    if angle == 180 and kind in UPSIDE_DOWN_LEFT:
        pytest.skip("known limit: upside-down table document is left as it is")
    doc = cv2.imread(str(DOCS[kind]))
    image, mask = place(doc, angle)
    crop = deskew(image, mask).crop
    # Upright means: of the 4 quarter turns of the crop, no turn matches the original better than none.
    scores = [similarity(rotate_quarters(crop, k), doc) for k in range(4)]
    assert int(np.argmax(scores)) == 0, f"{kind} at {angle}: scores {np.round(scores, 2)}"
    assert scores[0] > 0.8


def test_upright_documents_are_left_alone() -> None:
    for path in DOCS.values():
        o = text_rotation(cv2.imread(str(path)))
        assert o.turns == 0 and not o.sideways


def test_several_crops_of_one_document_are_judged_together() -> None:
    doc = cv2.imread(str(DOCS["portrait"]))
    sideways = rotate_quarters(doc, 1)
    blurry = cv2.GaussianBlur(cv2.resize(sideways, None, fx=0.25, fy=0.25), (5, 5), 0)
    assert text_rotation(sideways, blurry, blurry).turns == 3


@pytest.mark.parametrize("turns", [1, 2, 3])
def test_text_rotation_undoes_quarter_turns(turns: int) -> None:
    for kind, path in DOCS.items():
        if turns == 2 and kind in UPSIDE_DOWN_LEFT:
            continue
        doc = cv2.imread(str(path))
        o = text_rotation(rotate_quarters(doc, turns))
        assert (o.turns + turns) % 4 == 0, f"{path.name} turned {turns}: {o}"


def test_blank_crop_is_not_turned() -> None:
    assert text_rotation(np.full((400, 300, 3), 230, np.uint8)).turns == 0


def test_frame_aligned_corners_picks_the_most_horizontal_top_edge() -> None:
    # A square turned 30 degrees clockwise (y down): clockwise corners starting from the left-most one.
    c, s = np.cos(np.radians(30)), np.sin(np.radians(30))
    square = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]], float) @ np.array([[c, s], [-s, c]]) + 10
    for start in range(4):
        quad = frame_aligned_corners(np.roll(square, start, axis=0))
        edge = quad[1] - quad[0]
        assert edge[0] > 0 and abs(np.degrees(np.arctan2(edge[1], edge[0]))) <= 45
