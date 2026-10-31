"""Track cleanup: split tracks at time gaps and where the document in the box changes, drop tiny or short
tracks, remove heavy duplicates.

The same document found twice (lost and found again, or shown twice) is merged after reading, by its fields
(graph/nodes/read_documents.py `merge_duplicate_reads`).
"""

from dataclasses import dataclass, field
from typing import Mapping

import cv2
import numpy as np

from clients.segmenter import Track

Box = tuple[float, float, float, float]
SIGNATURE_SIZE = 32
APPEARANCE_SPLIT = 0.75  # see split_on_appearance; measured on the real and synthetic sweeps (Phase 9c)
APPEARANCE_STEADY = 0.9
MIN_SIGNATURE_STD = 4.0  # grey levels


def box_signature(gray: np.ndarray, box: Box, scale: tuple[float, float] = (1.0, 1.0)) -> np.ndarray | None:
    """The box region of a grey frame as a small zero-mean, unit-variance picture (None if the box is empty)."""
    x1, y1, x2, y2 = box
    sx, sy = scale
    region = gray[int(y1 * sy):int(np.ceil(y2 * sy)), int(x1 * sx):int(np.ceil(x2 * sx))]
    if min(region.shape[:2]) < SIGNATURE_SIZE:  # too small to compare reliably
        return None
    small = cv2.resize(region, (SIGNATURE_SIZE, SIGNATURE_SIZE), interpolation=cv2.INTER_AREA).astype(np.float32)
    if small.std() < MIN_SIGNATURE_STD:  # featureless (blank or one colour): nothing to compare
        return None
    return (small - small.mean()) / small.std()


def box_area(b: Box) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def box_iou(a: Box, b: Box) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = box_area(a) + box_area(b) - inter
    return inter / union if union > 0 else 0.0


def _mean_score(t: Track) -> float:
    scores = [f.score for f in t.frames.values() if f.score is not None]
    return float(np.mean(scores)) if scores else 0.0


@dataclass
class CleanupReport:
    kept: list[Track]
    split: list[str] = field(default_factory=list)  # tracks cut at time gaps
    dropped_short: list[str] = field(default_factory=list)
    dropped_small: list[str] = field(default_factory=list)
    dropped_duplicate: list[str] = field(default_factory=list)  # "<dropped> ~ <kept>"


def split_on_gaps(tracks: list[Track], max_gap: int = 3) -> tuple[list[Track], list[str]]:
    """Cut a track wherever it has no frames for more than `max_gap` frames.

    SAM can reuse an object id for a different document after the first one leaves the view;
    the gap is where that happens. Pieces are named '<track_id>#<n>'.
    """
    out, split = [], []
    for t in tracks:
        frames = sorted(t.frames)
        pieces, current = [], [frames[0]] if frames else []
        for prev, f in zip(frames, frames[1:]):
            if f - prev > max_gap:
                pieces.append(current)
                current = []
            current.append(f)
        if current:
            pieces.append(current)
        if len(pieces) <= 1:
            out.append(t)
            continue
        split.append(t.track_id)
        for n, piece in enumerate(pieces, 1):
            out.append(Track(f"{t.track_id}#{n}", t.prompt, {f: t.frames[f] for f in piece}))
    return out, split


def appearance_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Normalized correlation of two same-size signatures (1 = same picture)."""
    return float((a * b).mean())


def split_on_appearance(
    tracks: list[Track], signatures: Mapping[str, Mapping[int, np.ndarray]], min_similarity: float = APPEARANCE_SPLIT,
    steady: float = APPEARANCE_STEADY,
) -> tuple[list[Track], list[str]]:
    """Cut a track where what is inside its box changes abruptly between consecutive frames.

    When documents are shown one at a time in the same spot (e.g. on a laptop screen), SAM keeps one object id
    for all of them and the track has no time gap. `signatures[track_id][frame]` is a small normalized grey
    picture of the box region; consecutive frames of the same document stay above `min_similarity` while the
    camera moves, a swap to another document falls below it. A drop only counts as a swap when the frames on
    both sides are steady (>= `steady`): while a document slides in or out of view during a sweep the box
    content changes for several frames in a row. Pieces are named '<track_id>~<n>'.
    """
    out, split = [], []
    for t in tracks:
        sig = signatures.get(t.track_id, {})
        frames = sorted(t.frames)
        steps = [appearance_similarity(sig[a], sig[b]) if a in sig and b in sig else None
                 for a, b in zip(frames, frames[1:])]
        pieces, current = [], [frames[0]] if frames else []
        for i, f in enumerate(frames[1:]):
            before = steps[i - 1] if i > 0 else None
            after = steps[i + 1] if i + 1 < len(steps) else None
            if (steps[i] is not None and steps[i] < min_similarity
                    and (before is None or before >= steady) and (after is None or after >= steady)):
                pieces.append(current)
                current = []
            current.append(f)
        if current:
            pieces.append(current)
        if len(pieces) <= 1:
            out.append(t)
            continue
        split.append(t.track_id)
        for n, piece in enumerate(pieces, 1):
            out.append(Track(f"{t.track_id}~{n}", t.prompt, {f: t.frames[f] for f in piece}))
    return out, split


def clean_tracks(
    tracks: list[Track],
    frame_size: tuple[int, int],
    *,
    max_gap: int = 3,
    min_frames: int = 3,
    min_area_frac: float = 0.005,
    duplicate_iou: float = 0.7,
    min_shared_frames: int = 2,
    signatures: Mapping[str, Mapping[int, np.ndarray]] | None = None,
) -> CleanupReport:
    tracks, split = split_on_gaps(tracks, max_gap)
    if signatures:
        # Pieces after a gap keep their frames, so they look up the signatures of the track they came from.
        by_piece = {t.track_id: signatures.get(t.track_id.split("#")[0], {}) for t in tracks}
        tracks, swapped = split_on_appearance(tracks, by_piece)
        split += swapped
    report = CleanupReport(kept=[], split=split)
    frame_area = frame_size[0] * frame_size[1]

    survivors = []
    for t in tracks:
        if len(t.frames) < min_frames:
            report.dropped_short.append(t.track_id)
        elif np.median([box_area(f.box) for f in t.frames.values()]) < min_area_frac * frame_area:
            report.dropped_small.append(t.track_id)
        else:
            survivors.append(t)

    # Longest (then most confident) first; a later track overlapping a kept one heavily is a duplicate.
    for t in sorted(survivors, key=lambda t: (len(t.frames), _mean_score(t)), reverse=True):
        duplicate_of = None
        for k in report.kept:
            shared = t.frames.keys() & k.frames.keys()
            if len(shared) >= min_shared_frames:
                iou = np.mean([box_iou(t.frames[f].box, k.frames[f].box) for f in shared])
                if iou >= duplicate_iou:
                    duplicate_of = k
                    break
        if duplicate_of is None:
            report.kept.append(t)
        else:
            report.dropped_duplicate.append(f"{t.track_id} ~ {duplicate_of.track_id}")
    report.kept.sort(key=lambda t: min(t.frames))
    return report
