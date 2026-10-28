"""Segmenter clients (one place for SAM calls). Backend chosen by SEGMENTER in .env.

- sam31_api: SAM 3.1 on the Meta Model API (Files API upload + Responses API).
- sam3_modal: SAM 3 open weights on Modal. Stub for later, behind the same interface.

A segmenter takes a video and short noun-phrase prompts (one concept per request) and returns
tracks: a stable id and, per frame, a box, an optional score, and a lazily decoded mask.

SAM 3.1 output is special-token text, one line per frame (parsed with Meta's meta-sam-parser):
    <Nf>id<|box;x1;y1;x2;y2;w;h;c|><|mask;x=0;y=0;c;data=H,W,<enc>payload|>,id<|box..|><|mask..|>
Each mask covers its box (H x W of the box), placed at the box's top-left corner.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol, Sequence

import numpy as np
from meta_sam_parser import (
    CompletedOutcome,
    SegmentationBoxRecord,
    SegmentationMaskRecord,
    decode_mask_to_raster,
    video_segmentation_format,
)

logger = logging.getLogger(__name__)


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


MIN_BILLED_FRAMES = 50  # each SAM 3.1 video request is billed for at least 50 frames
SAM_METADATA = {"include_confidence": "true", "mask_encoding": "one_bit"}


@dataclass
class RawSegmentation:
    """SAM 3.1 output text for one prompt, exactly as returned, plus latency."""

    text: str
    prompt: str
    timings: dict[str, float]  # upload_s, segment_s (from the original call when cached)
    cached: bool = False


class Sam31ApiSegmenter:
    """SAM 3.1 on the Meta Model API: upload with the Files API, segment with the Responses API."""

    name = "sam31_api"

    def __init__(self) -> None:
        from app.config import get_settings  # local import keeps the interface importable in tests

        s = get_settings()
        missing = [n for n, v in (("META_BASE_URL", s.meta_base_url), ("META_API_KEY", s.meta_api_key.get_secret_value()),
                                  ("META_SEGMENT_MODEL", s.meta_segment_model)) if not v]
        if missing:
            raise ValueError(f"Segmenter sam31_api needs these in .env: {', '.join(missing)}")
        self.base_url, self.api_key, self.model = s.meta_base_url, s.meta_api_key, s.meta_segment_model
        self.cache_dir = s.cache_path

    def raw_segment(self, path: Path, prompt: str) -> RawSegmentation:
        """One request for one noun-phrase prompt. Cached by model + video bytes + prompt + metadata."""
        import time

        from openai import OpenAI

        from clients.cache import DiskCache, make_key

        video = path.read_bytes()
        cache = DiskCache(self.cache_dir)
        key = make_key({"provider": "meta", "model": self.model, "video": video, "prompt": prompt, "metadata": SAM_METADATA})
        hit = cache.get(key)
        if hit is not None:
            return RawSegmentation(text=hit["text"], prompt=prompt, timings=hit["timings"], cached=True)

        client = OpenAI(base_url=self.base_url, api_key=self.api_key.get_secret_value())
        t0 = time.perf_counter()
        uploaded = client.files.create(file=(path.name, video, "video/mp4"), purpose="user_data")
        upload_s = time.perf_counter() - t0
        try:
            t1 = time.perf_counter()
            resp = client.responses.create(
                model=self.model,
                input=[{"role": "user", "content": [
                    {"type": "input_video", "file_id": uploaded.id},
                    {"type": "input_text", "text": prompt},
                ]}],
                metadata=SAM_METADATA,
            )
            segment_s = time.perf_counter() - t1
        finally:
            try:  # never leave the user's video on the server
                client.files.delete(uploaded.id)
            except Exception:  # noqa: BLE001 - deletion is best effort; the result matters more
                pass
        timings = {"upload_s": round(upload_s, 3), "segment_s": round(segment_s, 3)}
        cache.set(key, {"text": resp.output_text, "timings": timings})
        return RawSegmentation(text=resp.output_text, prompt=prompt, timings=timings)

    def segment_video(self, path: Path, prompts: Sequence[str]) -> SegmentResult:
        """One request per prompt (SAM has no multi-concept syntax); tracks from all prompts together."""
        from vision.frames import probe_video

        info = probe_video(path)
        size = (info.width, info.height)
        tracks: list[Track] = []
        timings = {"upload_s": 0.0, "segment_s": 0.0}
        for prompt in prompts:
            raw = self.raw_segment(path, prompt)
            tracks += parse_sam_output(raw.text, prompt, size)
            for k in timings:
                timings[k] += raw.timings.get(k, 0.0)
        billed = len(prompts) * max(info.n_frames, MIN_BILLED_FRAMES)
        return SegmentResult(tracks=tracks, frame_size=size, billed_frames=billed, timings=timings)


def _mask_decoder(record: SegmentationMaskRecord, size: tuple[int, int]) -> Callable[[], np.ndarray]:
    def decode() -> np.ndarray:
        m = record.mask
        local = np.frombuffer(decode_mask_to_raster(m), np.uint8).reshape(m.height, m.width).astype(bool)
        full = np.zeros((size[1], size[0]), bool)
        x0, y0 = record.bounds.left, record.bounds.top
        h = min(m.height, size[1] - y0)
        w = min(m.width, size[0] - x0)
        full[y0 : y0 + h, x0 : x0 + w] = local[:h, :w]
        return full

    return decode


def parse_sam_output(text: str, prompt: str, size: tuple[int, int]) -> list[Track]:
    """Parse SAM 3.1 video output text into tracks. `size` is the (width, height) of the video sent."""
    parser = video_segmentation_format().create_parser()
    parser.push(text)
    result = parser.finish(CompletedOutcome()).result
    for d in result.diagnostics:
        logger.warning("SAM output diagnostic: %s", d)

    boxes: dict[tuple[int, str], SegmentationBoxRecord] = {}
    tracks: dict[str, Track] = {}
    for r in result.records:
        if isinstance(r, SegmentationBoxRecord):
            boxes[(r.frame.frame_index, r.object_id)] = r
        elif isinstance(r, SegmentationMaskRecord):
            frame = r.frame.frame_index
            box = boxes.get((frame, r.object_id))
            if box is None:
                continue
            track = tracks.setdefault(r.object_id, Track(f"{prompt}:{r.object_id}", prompt))
            track.frames[frame] = TrackFrame(
                frame=frame,
                box=(float(box.left), float(box.top), float(box.right), float(box.bottom)),
                score=box.confidence,
                decode_mask=_mask_decoder(r, size),
            )
    return list(tracks.values())


class Sam3ModalSegmenter:
    """SAM 3 open weights on a Modal GPU. Not built yet; same interface as the API backend."""

    name = "sam3_modal"

    def segment_video(self, path: Path, prompts: Sequence[str]) -> SegmentResult:
        raise NotImplementedError("sam3_modal is a placeholder; set SEGMENTER=sam31_api")
