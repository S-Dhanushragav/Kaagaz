"""Synthetic hand-held phone sweep videos over a household's documents, with per-frame truth.

Usage (from the repo root, with the backend venv; needs the household renders from synthetic.generate):
    python -m synthetic.video                    # the 4 standard videos
    python -m synthetic.video --video HH008_hard

Writes synthetic/videos/<video_id>/sweep.mp4 (gitignored) and video_truth.json (committed):
for every frame, each visible document's 4 corners in the frame (document's own top-left,
top-right, bottom-right, bottom-left) and the fraction of it inside the frame.
Everything is seeded: same spec -> same truth and same frames.
"""

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import cv2
import numpy as np

from synthetic.photo import _motion_kernel, make_background

ROOT = Path(__file__).resolve().parent
HOUSEHOLDS = ROOT / "households"
VIDEOS = ROOT / "videos"

PX_PER_MM = 5.0  # table texture resolution; the clean renders are ~4.8 px/mm
FOV_W_MM = 300.0  # table width across the frame at zoom 1 (phone ~35 cm above the table)
MAX_ROW_MM = 700.0
MARGIN_MM = 80.0
DOC_WIDTH_MM = {
    "identity_card": 85.6,
    "income_certificate": 210.0,
    "caste_certificate": 210.0,
    "ration_card": 180.0,
}


@dataclass(frozen=True)
class VideoSpec:
    video_id: str
    household: str
    seed: int = 42
    speed: float = 1.0  # >1: faster sweep over the same path (shorter video)
    touching: bool = False  # place two documents edge to edge
    duration_s: float = 20.0  # at speed 1
    fps: int = 30
    size: tuple[int, int] = (1080, 1920)  # width, height (portrait)


STANDARD = [
    VideoSpec("HH001", "HH001"),
    VideoSpec("HH008", "HH008"),
    VideoSpec("HH009", "HH009"),
    VideoSpec("HH008_hard", "HH008", speed=1.6, touching=True),
]


@dataclass
class Placement:
    doc_id: str
    doc_type: str
    corners: np.ndarray  # (4, 2) table px: document's own TL, TR, BR, BL


@dataclass
class Scene:
    table: np.ndarray  # uint8 BGR, with the documents
    texture: np.ndarray  # the same table surface without documents; repeated beyond the table edge
    placements: list[Placement]
    rows: list[tuple[float, float, float]]  # (y_center, x_min, x_max) in table px
    touching: list[str] | None
    background: str


def _rng(spec: VideoSpec, stream: str) -> np.random.Generator:
    digest = hashlib.sha256(f"{spec.seed}:{spec.video_id}:{stream}".encode()).hexdigest()
    return np.random.default_rng(int(digest[:16], 16))


def _rect_corners(cx: float, cy: float, w: float, h: float, angle_deg: float) -> np.ndarray:
    a = np.deg2rad(angle_deg)
    rot = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    local = np.array([[-w / 2, -h / 2], [w / 2, -h / 2], [w / 2, h / 2], [-w / 2, h / 2]])
    return local @ rot.T + [cx, cy]


# ---------- scene: documents on a table ----------

def build_scene(
    spec: VideoSpec, docs: list[tuple[str, str, np.ndarray]], px_per_mm: float = PX_PER_MM
) -> Scene:
    """Lay the documents out in rows (non-overlapping, small rotations) on a textured table."""
    rng = _rng(spec, "layout")
    items = []
    for doc_id, doc_type, img in docs:
        w = DOC_WIDTH_MM[doc_type] * px_per_mm
        items.append({"id": doc_id, "type": doc_type, "img": img, "w": w,
                      "h": w * img.shape[0] / img.shape[1], "angle": float(rng.uniform(-6, 6))})
    order = [items[i] for i in rng.permutation(len(items))]

    touching = None
    if spec.touching and len(order) >= 2:
        # Two documents side by side with no gap and no rotation, so their edges touch.
        a, b = order[0], order[1]
        a["angle"] = b["angle"] = 0.0
        a["touch_next"] = True
        touching = [a["id"], b["id"]]

    margin = MARGIN_MM * px_per_mm
    rows: list[list[dict[str, Any]]] = [[]]
    x = 0.0
    for it in order:
        a = np.deg2rad(it["angle"])
        it["bw"] = abs(it["w"] * np.cos(a)) + abs(it["h"] * np.sin(a))
        it["bh"] = abs(it["w"] * np.sin(a)) + abs(it["h"] * np.cos(a))
        prev = rows[-1][-1] if rows[-1] else None
        glued = prev is not None and prev.get("touch_next")
        gap = 0.0 if glued else float(rng.uniform(30, 60)) * px_per_mm
        if rows[-1] and not glued and x + gap + it["bw"] > MAX_ROW_MM * px_per_mm:
            rows.append([])
            x, gap = 0.0, 0.0
        it["x0"] = x + (gap if rows[-1] else 0.0)
        x = it["x0"] + it["bw"]
        rows[-1].append(it)

    placements, row_info = [], []
    y = margin
    width = max(r[-1]["x0"] + r[-1]["bw"] for r in rows) + 2 * margin
    for ri, r in enumerate(rows):
        row_h = max(it["bh"] for it in r)
        for it in r:
            cx, cy = margin + it["x0"] + it["bw"] / 2, y + it["bh"] / 2
            placements.append((it, _rect_corners(cx, cy, it["w"], it["h"], it["angle"])))
        row_info.append((y + row_h / 2, margin + r[0]["x0"], margin + r[-1]["x0"] + r[-1]["bw"]))
        y += row_h
        if ri < len(rows) - 1:
            y += float(rng.uniform(30, 60)) * px_per_mm
    height = y + margin

    W, H = int(np.ceil(width)), int(np.ceil(height))
    bg, kind = make_background(H, W, _rng(spec, "background"))
    texture = np.clip(bg, 0, 255).astype(np.uint8)
    del bg
    table = texture.copy()

    for it, corners in placements:
        _paste(table, it["img"], corners)
    # pre-filter so downscaling in warps doesn't alias
    table = cv2.GaussianBlur(table, (0, 0), 0.6)
    texture = cv2.GaussianBlur(texture, (0, 0), 0.6)

    return Scene(
        table=table,
        texture=texture,
        placements=[Placement(it["id"], it["type"], c) for it, c in placements],
        rows=row_info,
        touching=touching,
        background=kind,
    )


def _paste(table: np.ndarray, img: np.ndarray, corners: np.ndarray) -> None:
    """Warp `img` onto `table` at `corners` (TL, TR, BR, BL), with a soft shadow. In place, ROI only."""
    pad = 30
    x0, y0 = np.floor(corners.min(axis=0)).astype(int) - pad
    x1, y1 = np.ceil(corners.max(axis=0)).astype(int) + pad
    x0, y0 = max(x0, 0), max(y0, 0)
    x1, y1 = min(x1, table.shape[1]), min(y1, table.shape[0])
    ih, iw = img.shape[:2]
    src = np.float32([[0, 0], [iw, 0], [iw, ih]])
    dst = (corners[:3] - [x0, y0]).astype(np.float32)
    M = cv2.getAffineTransform(src, dst)
    size = (x1 - x0, y1 - y0)
    warped = cv2.warpAffine(img, M, size, flags=cv2.INTER_AREA).astype(np.float32)
    mask = cv2.warpAffine(np.ones((ih, iw), np.float32), M, size)[..., None]
    shadow = cv2.GaussianBlur(cv2.warpAffine(mask[..., 0], np.float32([[1, 0, 6], [0, 1, 8]]), size), (0, 0), 7)
    roi = table[y0:y1, x0:x1].astype(np.float32) * (1 - 0.35 * shadow[..., None])
    table[y0:y1, x0:x1] = np.clip(roi * (1 - mask) + warped * mask, 0, 255).astype(np.uint8)


# ---------- camera ----------

def _smoothstep(u: np.ndarray) -> np.ndarray:
    return u * u * (3 - 2 * u)


def camera_homographies(spec: VideoSpec, scene: Scene, px_per_mm: float = PX_PER_MM,
                        fov_w_mm: float = FOV_W_MM) -> list[np.ndarray]:
    """Table->frame homography for every frame of a back-and-forth sweep over the document rows."""
    rng = _rng(spec, "camera")
    fw, fh = spec.size
    view_w = fov_w_mm * px_per_mm
    n = max(2, round(spec.duration_s / spec.speed * spec.fps))
    t = np.arange(n) / spec.fps

    points = []
    for i, (yc, xmin, xmax) in enumerate(scene.rows):
        xa, xb = xmin + 0.35 * view_w, xmax - 0.35 * view_w
        if xa > xb:
            xa = xb = (xmin + xmax) / 2
        points += [(xa, yc), (xb, yc)] if i % 2 == 0 else [(xb, yc), (xa, yc)]
    pts = np.array(points, float)
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    weight = np.maximum(seg, 0.15 * view_w) ** 0.8  # slower per pixel on long segments, pause at ends
    bounds = np.concatenate([[0], np.cumsum(weight) / weight.sum()])

    u = t / t[-1]
    k = np.clip(np.searchsorted(bounds, u, side="right") - 1, 0, len(seg) - 1)
    local = _smoothstep(np.clip((u - bounds[k]) / (bounds[k + 1] - bounds[k]), 0, 1))
    centers = pts[k] + (pts[k + 1] - pts[k]) * local[:, None]

    def wobble(amp: float, fmin: float, fmax: float, parts: int = 3) -> np.ndarray:
        out = np.zeros(n)
        for _ in range(parts):
            out += np.sin(2 * np.pi * rng.uniform(fmin, fmax) * t + rng.uniform(0, 2 * np.pi))
        return amp * out / parts

    centers[:, 0] += wobble(0.012 * view_w, 0.8, 3.5)
    centers[:, 1] += wobble(0.012 * view_w, 0.8, 3.5)
    zoom = 1 + 0.08 * np.sin(2 * np.pi * t / rng.uniform(5, 8) + rng.uniform(0, 2 * np.pi))
    roll = np.deg2rad(2.5 * np.sin(2 * np.pi * t / rng.uniform(7, 11) + rng.uniform(0, 2 * np.pi)) + wobble(0.4, 1, 4))
    keystone = 0.02 + 0.015 * np.sin(2 * np.pi * t / rng.uniform(6, 10) + rng.uniform(0, 2 * np.pi))

    frame_rect = np.float32([[0, 0], [fw, 0], [fw, fh], [0, fh]])
    out = []
    for i in range(n):
        hw = view_w / 2 / zoom[i]
        hh = hw * fh / fw
        kx = keystone[i]
        local_pts = np.array([[-hw * (1 + kx), -hh], [hw * (1 + kx), -hh], [hw * (1 - kx), hh], [-hw * (1 - kx), hh]])
        c, s = np.cos(roll[i]), np.sin(roll[i])
        table_pts = local_pts @ np.array([[c, -s], [s, c]]).T + centers[i]
        out.append(cv2.getPerspectiveTransform(table_pts.astype(np.float32), frame_rect))
    return out


# ---------- frames + truth ----------

def _project(H: np.ndarray, pts: np.ndarray) -> np.ndarray:
    return cv2.perspectiveTransform(pts.reshape(-1, 1, 2).astype(np.float64), H).reshape(-1, 2)


def visible_fraction(corners: np.ndarray, size: tuple[int, int]) -> float:
    """Fraction of the quad's area inside the frame."""
    area = cv2.contourArea(corners.astype(np.float32))
    if area <= 0:
        return 0.0
    w, h = size
    rect = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    inter, _ = cv2.intersectConvexConvex(corners.astype(np.float32), rect)
    return float(np.clip(inter / area, 0, 1))


def warp_view(scene: Scene, H: np.ndarray, size: tuple[int, int], table_ones: np.ndarray | None = None) -> np.ndarray:
    """Camera view through table->frame homography H.

    Inside the table: the table with documents. Beyond its edge: the document-free texture,
    repeated. (Mirroring the table would also mirror documents and create phantom ones.)
    """
    if table_ones is None:
        table_ones = np.ones(scene.table.shape[:2], np.uint8)
    frame = cv2.warpPerspective(scene.table, H, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    inside = cv2.warpPerspective(table_ones, H, size, flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT)
    if inside.all():
        return frame
    beyond = cv2.warpPerspective(scene.texture, H, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
    return np.where(inside[..., None] > 0, frame, beyond)


def iter_frames(spec: VideoSpec, scene: Scene, *, effects: bool = True, px_per_mm: float = PX_PER_MM,
                fov_w_mm: float = FOV_W_MM) -> Iterator[tuple[np.ndarray, dict[str, Any]]]:
    """Yield (BGR frame, truth record) for every frame."""
    rng = _rng(spec, "effects")
    fw, fh = spec.size
    homs = camera_homographies(spec, scene, px_per_mm, fov_w_mm)
    n = len(homs)
    out_of_focus = rng.random(n) < 0.03
    yy, xx = np.mgrid[0:fh, 0:fw].astype(np.float32)
    xx, yy = (xx - fw / 2) / (fh / 2), (yy - fh / 2) / (fh / 2)
    phase = rng.uniform(0, 2 * np.pi, 3)
    table_ones = np.ones(scene.table.shape[:2], np.uint8)

    for i, H in enumerate(homs):
        t = i / spec.fps
        frame = warp_view(scene, H, (fw, fh), table_ones)
        # Camera speed at the frame centre (frame px per frame) -> motion blur length.
        centre = cv2.perspectiveTransform(np.float64([[[fw / 2, fh / 2]]]), np.linalg.inv(H)).reshape(1, 2)
        prev_H = homs[i - 1] if i else H
        v = _project(H, centre)[0] - _project(prev_H, centre)[0]
        blur_px = float(np.linalg.norm(v) * 0.5)  # exposure ~ half the frame interval

        if effects:
            img = frame.astype(np.float32)
            if blur_px >= 1.5:
                length = int(round(min(blur_px, 41))) | 1
                img = cv2.filter2D(img, -1, _motion_kernel(max(length, 3), -np.degrees(np.arctan2(v[1], v[0]))))
            if out_of_focus[i]:
                img = cv2.GaussianBlur(img, (0, 0), float(rng.uniform(3, 5)))
            theta = phase[0] + 0.3 * t
            ramp = xx * np.cos(theta) + yy * np.sin(theta)
            gain = 0.95 + 0.06 * np.sin(2 * np.pi * t / 8 + phase[1])
            strength = 0.14 + 0.06 * np.sin(2 * np.pi * t / 11 + phase[2])
            img *= (gain * (1 + strength * np.clip(ramp, -1.5, 1.5)))[..., None]
            img += rng.normal(0, 2.5, img.shape).astype(np.float32)
            ok, buf = cv2.imencode(".jpg", np.clip(img, 0, 255).astype(np.uint8),
                                   [cv2.IMWRITE_JPEG_QUALITY, int(rng.integers(72, 90))])
            frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)

        docs = {}
        for p in scene.placements:
            corners = _project(H, p.corners)
            vis = visible_fraction(corners, spec.size)
            if vis > 0:
                docs[p.doc_id] = {"corners": np.round(corners, 1).tolist(), "visible": round(vis, 3)}
        yield frame, {
            "i": i, "t": round(t, 4), "blur_px": round(blur_px, 2),
            "out_of_focus": bool(effects and out_of_focus[i]), "docs": docs,
        }


def render_video(spec: VideoSpec, docs: list[tuple[str, str, np.ndarray]], out_dir: Path, *,
                 px_per_mm: float = PX_PER_MM, fov_w_mm: float = FOV_W_MM) -> dict[str, Any]:
    """Write out_dir/sweep.mp4 and out_dir/video_truth.json; return the truth."""
    out_dir.mkdir(parents=True, exist_ok=True)
    scene = build_scene(spec, docs, px_per_mm)
    fw, fh = spec.size
    writer = cv2.VideoWriter(str(out_dir / "sweep.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), spec.fps, (fw, fh))
    if not writer.isOpened():
        raise RuntimeError("OpenCV could not open an mp4v video writer")
    frames = []
    try:
        for frame, record in iter_frames(spec, scene, px_per_mm=px_per_mm, fov_w_mm=fov_w_mm):
            writer.write(frame)
            frames.append(record)
    finally:
        writer.release()

    truth = {
        "video_id": spec.video_id,
        "household": spec.household,
        "seed": spec.seed,
        "fps": spec.fps,
        "width": fw,
        "height": fh,
        "n_frames": len(frames),
        "speed": spec.speed,
        "touching": scene.touching,
        "background": scene.background,
        "px_per_mm": px_per_mm,
        "fov_w_mm": fov_w_mm,
        "documents": [
            {"id": p.doc_id, "type": p.doc_type, "table_corners": np.round(p.corners, 1).tolist()}
            for p in scene.placements
        ],
        "frames": frames,
    }
    (out_dir / "video_truth.json").write_text(json.dumps(truth, ensure_ascii=False), encoding="utf-8")
    return truth


def load_household_docs(household: str) -> list[tuple[str, str, np.ndarray]]:
    gt = json.loads((HOUSEHOLDS / household / "ground_truth.json").read_text(encoding="utf-8"))
    docs = []
    for d in gt["documents"]:
        png = HOUSEHOLDS / household / d["files"]["clean"]
        if not png.exists():
            raise FileNotFoundError(f"{png} missing; run `python -m synthetic.generate` first")
        docs.append((d["id"], d["type"], cv2.imread(str(png), cv2.IMREAD_COLOR)))
    return docs


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic sweep videos")
    parser.add_argument("--video", choices=[s.video_id for s in STANDARD], help="one video (default: all)")
    args = parser.parse_args()
    for spec in STANDARD:
        if args.video and spec.video_id != args.video:
            continue
        truth = render_video(spec, load_household_docs(spec.household), VIDEOS / spec.video_id)
        full = {d["id"]: max((f["docs"].get(d["id"], {}).get("visible", 0) for f in truth["frames"]), default=0)
                for d in truth["documents"]}
        print(f"{spec.video_id}: {truth['n_frames']} frames, {len(full)} documents, "
              f"fully visible at some point: {sum(v >= 0.999 for v in full.values())}/{len(full)}, "
              f"touching: {truth['touching']}")


if __name__ == "__main__":
    main()
