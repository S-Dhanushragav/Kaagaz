"""Segmenter clients (one place for SAM calls). Backend chosen by SEGMENTER in .env.

- sam31_api: SAM 3.1 on the Meta Model API (Files API upload + Responses API). Built after the probe call.
- sam3_modal: SAM 3 open weights on Modal. Stub for later, behind the same interface.

A segmenter takes a video and short noun-phrase prompts (one concept per request) and returns
tracks: a stable id and, per frame, a box, an optional score, and a lazily decoded mask.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol, Sequence

import numpy as np


@dataclass
class TrackFrame:
    frame: int  # index in the video that was sent to the segmenter
    box: tuple[float, float, float, float]  # x1, y1, x2, y2 in that video's pixels
    score: float | None
    decode_mask: Callable[[], np.ndarray]  # -> bool array (H, W); masks are decoded only when needed

    def mask(self) -> np.ndarray:
        return self.decode_mask()


@dataclass
class Track:
    track_id: str  # "<prompt>:<object id>"
    prompt: str
    frames: dict[int, TrackFrame] = field(default_factory=dict)


@dataclass
class SegmentResult:
    tracks: list[Track]
    frame_size: tuple[int, int]  # width, height of the video sent to the segmenter
    billed_frames: int = 0
    timings: dict[str, float] = field(default_factory=dict)  # e.g. upload_s, segment_s


class Segmenter(Protocol):
    name: str

    def segment_video(self, path: Path, prompts: Sequence[str]) -> SegmentResult: ...


class Sam3ModalSegmenter:
    """SAM 3 open weights on a Modal GPU. Not built yet; same interface as the API backend."""

    name = "sam3_modal"

    def segment_video(self, path: Path, prompts: Sequence[str]) -> SegmentResult:
        raise NotImplementedError("sam3_modal is a placeholder; set SEGMENTER=sam31_api")
