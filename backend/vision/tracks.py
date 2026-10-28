"""Track cleanup: drop tiny or short tracks, remove heavy duplicates.

Merging tracks of the same document that was lost and found again is deliberately not done yet;
it is added only if the finder eval shows split tracks.
"""

from dataclasses import dataclass, field

import numpy as np

from clients.segmenter import Track

Box = tuple[float, float, float, float]


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
    dropped_short: list[str] = field(default_factory=list)
    dropped_small: list[str] = field(default_factory=list)
    dropped_duplicate: list[str] = field(default_factory=list)  # "<dropped> ~ <kept>"


def clean_tracks(
    tracks: list[Track],
    frame_size: tuple[int, int],
    *,
    min_frames: int = 3,
    min_area_frac: float = 0.005,
    duplicate_iou: float = 0.7,
    min_shared_frames: int = 2,
) -> CleanupReport:
    report = CleanupReport(kept=[])
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
