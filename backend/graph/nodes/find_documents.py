"""Document finder: video -> segmenter tracks -> best 2-3 upright crops per document.

Plain function for now; it becomes a LangGraph node later. Steps:
1. resample: low-fps 720p copy for the segmenter + full-resolution JPEGs of the same frames (tmp/)
2. segment: tracks from the segmenter (one request per prompt)
3. clean: drop tiny/short tracks, remove heavy duplicates
4. select: per track, frames where the document is fully in view; sharpness is measured on the
   box region of the full-resolution frame, so no mask is decoded yet; keep the sharpest 2-3,
   spread apart in time
5. deskew: decode only the chosen masks (in parallel processes; SAM mask decoding is slow pure
   Python), mask -> 4 corners -> upright crop from full resolution -> DocumentInput
Frames are deleted after the run. With debug=True a contact sheet of the chosen crops is kept in tmp/.
"""

import os
import shutil
import time
import uuid
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Sequence

import cv2
import numpy as np
from pydantic import BaseModel

from clients.segmenter import Segmenter, Track, TrackFrame, decode_mask_spec
from graph.nodes.read_documents import DocumentInput
from vision.deskew import deskew
from vision.frames import full_frame_path, resample_video
from vision.images import encode_for_llm
from vision.quality import Candidate, select_frames, sharpness, touches_edge, visible_estimate
from vision.tracks import box_area, clean_tracks

TMP = Path(__file__).resolve().parents[3] / "tmp"
MAX_CANDIDATES_PER_TRACK = 12
PARALLEL_DECODE_MIN = 4  # below this, process start-up costs more than it saves


class FoundDocument(BaseModel):
    document: DocumentInput
    track_id: str
    source_frames: list[int]  # chosen frames, best first
    quads: list[list[list[float]]]  # document corners (TL, TR, BR, BL) in each chosen source frame
    methods: list[str]  # deskew method per chosen frame
    sharpness: list[float]
    fully_visible: bool  # False if the document was never seen without touching the frame edge


class FindResult(BaseModel):
    documents: list[FoundDocument]
    tracks_raw: int
    dropped: dict[str, list[str]]
    segmenter_frames: int
    billed_frames: int
    masks_decoded: int
    timings: dict[str, float]
    contact_sheet: str | None = None


def _candidates(track: Track, size: tuple[int, int]) -> tuple[list[int], bool]:
    """Frames worth considering: not touching the edge and near the track's largest unclipped size."""
    inside = [f for f, tf in track.frames.items() if not touches_edge(tf.box, size)]
    fully_visible = bool(inside)
    pool = inside or list(track.frames)
    ref = max(box_area(track.frames[f].box) for f in pool)
    pool = [f for f in pool if visible_estimate(box_area(track.frames[f].box), ref) >= 0.9]
    pool.sort(key=lambda f: box_area(track.frames[f].box), reverse=True)
    return pool[:MAX_CANDIDATES_PER_TRACK], fully_visible


def _box_crop(image: np.ndarray, box: tuple[float, float, float, float], scale: tuple[float, float]) -> np.ndarray:
    x1, y1, x2, y2 = box
    sx, sy = scale
    return image[int(y1 * sy) : int(np.ceil(y2 * sy)), int(x1 * sx) : int(np.ceil(x2 * sx))]


def _decode_masks(frames: list[TrackFrame]) -> list[np.ndarray]:
    specs = [f.mask_spec for f in frames]
    if len(frames) >= PARALLEL_DECODE_MIN and all(s is not None for s in specs):
        with ProcessPoolExecutor(max_workers=min(len(frames), os.cpu_count() or 2)) as pool:
            return list(pool.map(decode_mask_spec, specs))
    return [f.mask() for f in frames]


def _contact_sheet(crops: list[list[np.ndarray]], path: Path, height: int = 320) -> None:
    rows = []
    for doc_crops in crops:
        tiles = [cv2.resize(c, (max(1, round(c.shape[1] * height / c.shape[0])), height)) for c in doc_crops]
        rows.append(np.hstack(tiles))
    width = max(r.shape[1] for r in rows)
    sheet = np.vstack([np.pad(r, ((0, 8), (0, width - r.shape[1]), (0, 0)), constant_values=255) for r in rows])
    cv2.imwrite(str(path), sheet, [cv2.IMWRITE_JPEG_QUALITY, 85])


def find_documents(
    video: Path,
    *,
    segmenter: Segmenter,
    prompts: Sequence[str] = ("document",),
    segmenter_fps: float = 5.0,
    segmenter_long_side: int = 1280,
    frames_per_doc: int = 3,
    min_gap_s: float = 0.5,
    debug: bool = False,
    tmp_root: Path = TMP,
) -> FindResult:
    run_dir = tmp_root / f"find_{uuid.uuid4().hex[:8]}"
    frames_dir = run_dir / "frames"
    timings: dict[str, float] = {}
    try:
        t0 = time.perf_counter()
        rs = resample_video(video, run_dir / "segmenter.mp4", frames_dir,
                            target_fps=segmenter_fps, long_side=segmenter_long_side)
        timings["resample_s"] = time.perf_counter() - t0

        seg = segmenter.segment_video(Path(rs.path), prompts)
        timings.update(seg.timings)

        t0 = time.perf_counter()
        report = clean_tracks(seg.tracks, seg.frame_size)
        timings["cleanup_s"] = time.perf_counter() - t0

        # Select frames by box-region sharpness (no mask decoding).
        t0 = time.perf_counter()
        scale = (rs.source.width / seg.frame_size[0], rs.source.height / seg.frame_size[1])
        images: dict[int, np.ndarray] = {}

        def image(src: int) -> np.ndarray:
            if src not in images:
                images[src] = cv2.imread(str(full_frame_path(frames_dir, src)), cv2.IMREAD_COLOR)
            return images[src]

        plans = []  # (track, fully_visible, [(Candidate, TrackFrame)])
        partial = []
        for track in report.kept:
            frames, fully_visible = _candidates(track, seg.frame_size)
            if not fully_visible:  # only ever seen cut off by the frame edge: can't be read completely
                partial.append(track.track_id)
                continue
            by_src: dict[int, TrackFrame] = {}
            cands = []
            for f in frames:
                if f >= len(rs.source_indices):
                    continue
                src = rs.source_indices[f]
                crop = _box_crop(image(src), track.frames[f].box, scale)
                if crop.size == 0:
                    continue
                by_src[src] = track.frames[f]
                cands.append(Candidate(frame=src, time_s=src / rs.source.fps, sharpness=sharpness(crop)))
            chosen = select_frames(cands, k=frames_per_doc, min_gap_s=min_gap_s)
            if chosen:
                plans.append((track, fully_visible, [(c, by_src[c.frame]) for c in chosen]))
        timings["select_s"] = time.perf_counter() - t0

        # Decode only the chosen masks, then deskew from full resolution.
        t0 = time.perf_counter()
        chosen_frames = [tf for _, _, picks in plans for _, tf in picks]
        masks = iter(_decode_masks(chosen_frames))
        timings["mask_decode_s"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        found, sheet_crops = [], []
        for track, fully_visible, picks in plans:
            kept = []
            for cand, _ in picks:
                mask = next(masks)
                try:
                    kept.append((cand, deskew(image(cand.frame), mask)))
                except ValueError:
                    continue
            if not kept:
                continue
            crops = [res.crop for _, res in kept]
            found.append(FoundDocument(
                document=DocumentInput(id=f"doc{len(found) + 1:02d}", images=[encode_for_llm(c) for c in crops]),
                track_id=track.track_id,
                source_frames=[c.frame for c, _ in kept],
                quads=[np.round(res.quad, 1).tolist() for _, res in kept],
                methods=[res.method for _, res in kept],
                sharpness=[round(c.sharpness, 1) for c, _ in kept],
                fully_visible=fully_visible,
            ))
            sheet_crops.append(crops)
        timings["deskew_s"] = time.perf_counter() - t0

        sheet = None
        if debug and sheet_crops:
            sheet = run_dir / "contact_sheet.jpg"
            _contact_sheet(sheet_crops, sheet)
        return FindResult(
            documents=found,
            tracks_raw=len(seg.tracks),
            dropped={"split": report.split, "short": report.dropped_short, "small": report.dropped_small,
                     "duplicate": report.dropped_duplicate, "partial": partial},
            segmenter_frames=len(rs.source_indices),
            billed_frames=seg.billed_frames,
            masks_decoded=len(chosen_frames),
            timings={k: round(v, 3) for k, v in timings.items()},
            contact_sheet=str(sheet) if sheet else None,
        )
    finally:
        # Never keep raw frames. Keep only the debug contact sheet when asked for.
        shutil.rmtree(frames_dir, ignore_errors=True)
        (run_dir / "segmenter.mp4").unlink(missing_ok=True)
        if not debug:
            shutil.rmtree(run_dir, ignore_errors=True)
