"""Finder building blocks and an offline end-to-end run with a fake segmenter (no network)."""

import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest

from clients.segmenter import SegmentResult, Track, TrackFrame
from graph.nodes.find_documents import find_documents
from synthetic.video import VideoSpec, build_scene, iter_frames
from vision.deskew import deskew, order_corners, quad_from_mask
from vision.frames import probe_video, resample_video
from vision.quality import Candidate, select_frames, sharpness, touches_edge
from vision.tracks import box_iou, clean_tracks

# ---------- frames ----------


def _write_video(path: Path, n: int = 90, fps: int = 30, size=(216, 384)) -> None:
    w, h = size
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for i in range(n):
        frame = np.full((h, w, 3), 40, np.uint8)
        cv2.putText(frame, str(i), (20, 200), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 3)
        writer.write(frame)
    writer.release()


def test_resample_keeps_5fps_and_full_res_frames(tmp_path: Path) -> None:
    src = tmp_path / "in.mp4"
    _write_video(src)
    rs = resample_video(src, tmp_path / "small.mp4", tmp_path / "frames", target_fps=5, long_side=192)
    assert rs.source_indices == list(range(0, 90, 6))
    assert (rs.width, rs.height) == (108, 192)
    assert probe_video(Path(rs.path)).height == 192
    assert len(list((tmp_path / "frames").glob("*.jpg"))) == 15
    assert cv2.imread(str(next((tmp_path / "frames").glob("*.jpg")))).shape[:2] == (384, 216)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_resample_accepts_hevc(tmp_path: Path) -> None:
    src = tmp_path / "in.mp4"
    _write_video(src)
    hevc = tmp_path / "hevc.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-c:v", "libx265",
                    "-tag:v", "hvc1", "-x265-params", "log-level=error", str(hevc)], check=True)
    assert probe_video(hevc).codec.lower() in ("hvc1", "hev1", "hevc")
    rs = resample_video(hevc, tmp_path / "small.mp4", tmp_path / "frames", target_fps=5, long_side=192)
    assert len(rs.source_indices) == 15


# ---------- quality ----------


def test_sharpness_prefers_sharp() -> None:
    img = np.zeros((200, 300, 3), np.uint8)
    cv2.putText(img, "SPECIMEN", (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 2)
    assert sharpness(img) > 3 * sharpness(cv2.GaussianBlur(img, (0, 0), 3))


def test_touches_edge() -> None:
    assert touches_edge((0, 10, 50, 50), (100, 100))
    assert touches_edge((10, 10, 99, 50), (100, 100))
    assert not touches_edge((10, 10, 90, 90), (100, 100))


def test_select_frames_best_first_and_spread() -> None:
    c = [Candidate(f, f / 30, s) for f, s in [(0, 5), (3, 9), (6, 8), (30, 7), (60, 1), (45, 6)]]
    chosen = select_frames(c, k=3, min_gap_s=0.5)
    assert [x.frame for x in chosen] == [3, 30, 60] or [x.frame for x in chosen] == [3, 30, 45]
    assert [x.frame for x in chosen][:2] == [3, 30]
    assert all(abs(a.time_s - b.time_s) >= 0.5 for a in chosen for b in chosen if a is not b)


# ---------- deskew ----------


def _document() -> np.ndarray:
    doc = np.full((200, 300, 3), 235, np.uint8)
    for (x, y), color in zip([(0, 0), (270, 0), (270, 170), (0, 170)], [(0, 0, 255), (0, 255, 0), (255, 0, 0), (0, 0, 0)]):
        doc[y : y + 30, x : x + 30] = color
    cv2.putText(doc, "SPECIMEN", (40, 115), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (30, 30, 30), 3)
    return doc


def test_deskew_recovers_known_warp() -> None:
    doc = _document()
    true = np.float32([[120, 80], [470, 110], [450, 360], [100, 330]])
    M = cv2.getPerspectiveTransform(np.float32([[0, 0], [300, 0], [300, 200], [0, 200]]), true)
    canvas = cv2.warpPerspective(doc, M, (640, 480), borderValue=(60, 90, 120))
    mask = cv2.warpPerspective(np.ones((200, 300), np.uint8), M, (640, 480))
    res = deskew(canvas, mask)
    assert res.method == "quad"
    assert np.abs(res.quad - true).max() < 3
    back = cv2.resize(res.crop, (300, 200))
    assert np.abs(back.astype(int) - doc.astype(int)).mean() < 20
    # corner markers land in the right corners
    assert back[10, 10].argmax() == 2 and back[10, 290].argmax() == 1 and back[190, 290].argmax() == 0


def test_deskew_scales_mask_to_full_resolution() -> None:
    doc = _document()
    true = np.float32([[120, 80], [470, 110], [450, 360], [100, 330]])
    M = cv2.getPerspectiveTransform(np.float32([[0, 0], [300, 0], [300, 200], [0, 200]]), true)
    canvas = cv2.warpPerspective(doc, M, (640, 480))
    mask = cv2.warpPerspective(np.ones((200, 300), np.uint8), M, (640, 480))
    small = cv2.resize(mask, (320, 240), interpolation=cv2.INTER_NEAREST)
    assert np.abs(deskew(canvas, small).quad - true).max() < 5


def test_deskew_falls_back_to_min_area_rect() -> None:
    mask = np.zeros((300, 300), np.uint8)
    cv2.ellipse(mask, (150, 150), (100, 60), 20, 0, 360, 1, -1)
    _, method = quad_from_mask(mask)
    assert method == "min_area_rect"


def test_order_corners() -> None:
    pts = np.array([[10, 90], [100, 5], [0, 0], [95, 100]], float)
    assert order_corners(pts).tolist() == [[0, 0], [100, 5], [95, 100], [10, 90]]


# ---------- tracks ----------


def _track(tid: str, boxes: dict[int, tuple], score: float = 0.9) -> Track:
    return Track(tid, "document", {f: TrackFrame(f, b, score, lambda: np.zeros((1, 1), bool)) for f, b in boxes.items()})


def test_clean_tracks() -> None:
    big = (100, 100, 300, 400)
    beside = (300, 100, 500, 400)  # touching the first: IoU 0
    tracks = [
        _track("document:1", {f: big for f in range(10)}),
        _track("document:2", {f: (102, 98, 301, 405) for f in range(2, 8)}),  # duplicate of 1
        _track("document:3", {f: beside for f in range(10)}),
        _track("document:4", {0: big, 1: big}),  # too short
        _track("document:5", {f: (10, 10, 20, 20) for f in range(10)}),  # too small
    ]
    r = clean_tracks(tracks, (720, 1280))
    assert [t.track_id for t in r.kept] == ["document:1", "document:3"]
    assert r.dropped_short == ["document:4"] and r.dropped_small == ["document:5"]
    assert r.dropped_duplicate == ["document:2 ~ document:1"]
    assert box_iou(big, beside) == 0


# ---------- offline end-to-end ----------

COLORS = {"a": (0, 0, 255), "b": (0, 200, 0), "c": (255, 0, 0)}


class ColourSegmenter:
    """Fake segmenter: finds each solid-coloured document by colour in the uploaded video."""

    name = "fake"

    def segment_video(self, path: Path, prompts) -> SegmentResult:
        cap = cv2.VideoCapture(str(path))
        tracks = {k: Track(f"document:{k}", "document") for k in COLORS}
        i = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            for k, colour in COLORS.items():
                mask = (np.abs(frame.astype(int) - colour).max(axis=2) < 70)
                if mask.sum() < 30:
                    continue
                ys, xs = np.nonzero(mask)
                tracks[k].frames[i] = TrackFrame(i, (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1), 0.9,
                                                 lambda m=mask: m)
            i += 1
        size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        cap.release()
        return SegmentResult(list(tracks.values()), size, billed_frames=max(i, 50), timings={"segment_s": 0.0})


def _quad_iou(a: np.ndarray, b: np.ndarray) -> float:
    inter, _ = cv2.intersectConvexConvex(a.astype(np.float32), b.astype(np.float32))
    union = cv2.contourArea(a.astype(np.float32)) + cv2.contourArea(b.astype(np.float32)) - inter
    return inter / union


def test_find_documents_offline(tmp_path: Path) -> None:
    spec = VideoSpec("T", "T", duration_s=3.0, fps=10, size=(216, 384))
    docs = [("a", "identity_card", np.full((54, 86, 3), COLORS["a"], np.uint8)),
            ("b", "income_certificate", np.full((297, 210, 3), COLORS["b"], np.uint8)),
            ("c", "identity_card", np.full((54, 86, 3), COLORS["c"], np.uint8))]
    scene = build_scene(spec, docs, 1.0)
    video = tmp_path / "sweep.mp4"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), spec.fps, spec.size)
    truth = []
    for frame, record in iter_frames(spec, scene, effects=False, px_per_mm=1.0, fov_w_mm=300):
        writer.write(frame)
        truth.append(record)
    writer.release()

    result = find_documents(video, segmenter=ColourSegmenter(), segmenter_fps=5, segmenter_long_side=192,
                            tmp_root=tmp_path / "tmp", debug=True)
    seen = {d for r in truth for d, v in r["docs"].items() if v["visible"] >= 0.999}
    assert {f.track_id.split(":")[1] for f in result.documents} == seen
    for f in result.documents:
        doc = f.track_id.split(":")[1]
        assert 1 <= len(f.document.images) <= 3
        for frame, quad in zip(f.source_frames, f.quads):
            true = np.array(truth[frame]["docs"][doc]["corners"])
            assert _quad_iou(np.array(quad), true) > 0.8, (doc, frame)
        crop = cv2.imdecode(np.frombuffer(f.document.images[0], np.uint8), cv2.IMREAD_COLOR)
        assert np.abs(crop.reshape(-1, 3).mean(axis=0) - COLORS[doc]).max() < 50
    # frames deleted; only the debug contact sheet stays
    leftovers = [p.name for p in (tmp_path / "tmp").rglob("*") if p.is_file()]
    assert leftovers == ["contact_sheet.jpg"]
    assert set(result.timings) >= {"resample_s", "cleanup_s", "deskew_s"}


def test_find_documents_cleans_tmp_without_debug(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    _write_video(video, n=30)
    find_documents(video, segmenter=ColourSegmenter(), tmp_root=tmp_path / "tmp")
    assert not any((tmp_path / "tmp").rglob("*"))
