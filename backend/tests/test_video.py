"""Sweep-video generator: determinism and truth geometry, on a tiny scene (no renders needed)."""

import numpy as np

from synthetic.video import VideoSpec, build_scene, iter_frames, visible_fraction

COLORS = {"a": (0, 0, 255), "b": (0, 255, 0), "c": (255, 0, 0), "d": (0, 255, 255)}
PXMM = 1.0  # tiny table
FOV = 300.0


def _docs():
    sizes = {"a": ("identity_card", (54, 86)), "b": ("income_certificate", (297, 210)),
             "c": ("identity_card", (54, 86)), "d": ("caste_certificate", (297, 210))}
    return [(k, t, np.full((h, w, 3), COLORS[k], np.uint8)) for k, (t, (h, w)) in sizes.items()]


def _spec(**kw) -> VideoSpec:
    return VideoSpec("T", "T", duration_s=2.0, fps=10, size=(108, 192), **kw)


def _run(spec: VideoSpec, effects: bool = False):
    scene = build_scene(spec, _docs(), PXMM)
    return list(iter_frames(spec, scene, effects=effects, px_per_mm=PXMM, fov_w_mm=FOV))


def test_same_spec_same_frames_and_truth() -> None:
    a, b = _run(_spec(), effects=True), _run(_spec(), effects=True)
    assert [t for _, t in a] == [t for _, t in b]
    assert all(np.array_equal(fa, fb) for (fa, _), (fb, _) in zip(a, b))
    c = _run(_spec(seed=7), effects=True)
    assert [t for _, t in a] != [t for _, t in c]


def test_frame_count_follows_speed() -> None:
    assert len(_run(_spec())) == 20
    assert len(_run(_spec(speed=2.0))) == 10


def test_layout_has_no_overlaps() -> None:
    scene = build_scene(_spec(), _docs(), PXMM)
    polys = [p.corners for p in scene.placements]
    import cv2

    for i in range(len(polys)):
        for j in range(i + 1, len(polys)):
            inter, _ = cv2.intersectConvexConvex(polys[i].astype(np.float32), polys[j].astype(np.float32))
            assert inter < 1.0


def test_touching_variant_shares_an_edge() -> None:
    scene = build_scene(_spec(touching=True), _docs(), PXMM)
    a, b = (next(p for p in scene.placements if p.doc_id == d) for d in scene.touching)
    # a's right edge x == b's left edge x (both unrotated)
    assert abs(a.corners[1, 0] - b.corners[0, 0]) < 1e-6


def test_truth_corners_match_rendered_pixels() -> None:
    """Inside each fully visible document's projected quad, the frame shows that document's colour."""
    checked = 0
    for frame, truth in _run(_spec()):
        for doc_id, d in truth["docs"].items():
            if d["visible"] < 1.0:
                continue
            corners = np.array(d["corners"])
            centre = corners.mean(axis=0)
            # a point well inside the quad: 70% of the way from each corner towards the centre
            for corner in corners:
                x, y = (corner + 0.7 * (centre - corner)).round().astype(int)
                assert np.abs(frame[y, x].astype(int) - COLORS[doc_id]).max() < 40, (truth["i"], doc_id)
            checked += 1
    assert checked > 0


def test_visible_fraction() -> None:
    size = (100, 100)
    assert visible_fraction(np.array([[10, 10], [50, 10], [50, 50], [10, 50]], float), size) == 1.0
    assert abs(visible_fraction(np.array([[-40, 10], [40, 10], [40, 50], [-40, 50]], float), size) - 0.5) < 1e-6
    assert visible_fraction(np.array([[200, 10], [240, 10], [240, 50], [200, 50]], float), size) == 0.0


def test_truth_visible_is_one_iff_all_corners_inside() -> None:
    w, h = _spec().size
    for _, truth in _run(_spec()):
        for d in truth["docs"].values():
            c = np.array(d["corners"])
            inside = bool(((c[:, 0] >= 0) & (c[:, 0] <= w) & (c[:, 1] >= 0) & (c[:, 1] <= h)).all())
            assert inside == (d["visible"] >= 0.999)
