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
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol, Sequence

import numpy as np
from meta_sam_parser import (
    CompletedOutcome,
    SegmentationBoxRecord,
    SegmentationMask,
    SegmentationMaskRecord,
    decode_mask_to_raster,
    video_segmentation_format,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MaskSpec:
    """An undecoded SAM mask: picklable, so masks can be decoded in worker processes."""

    encoding: str  # "one_bit" or "lossless"
    payload: str  # passed to Meta's decoder unchanged
    width: int
    height: int
    left: int  # where the mask's top-left sits in the frame
    top: int
    frame_size: tuple[int, int]  # width, height


def decode_mask_spec(spec: MaskSpec) -> np.ndarray:
    """Full-frame bool mask. Uses Meta's decoder; pure Python, ~0.1-3 s per mask depending on size."""
    raster = decode_mask_to_raster(
        SegmentationMask(encoding=spec.encoding, payload=spec.payload, width=spec.width, height=spec.height)
    )
    local = np.frombuffer(raster, np.uint8).reshape(spec.height, spec.width).astype(bool)
    fw, fh = spec.frame_size
    full = np.zeros((fh, fw), bool)
    h, w = min(spec.height, fh - spec.top), min(spec.width, fw - spec.left)
    full[spec.top : spec.top + h, spec.left : spec.left + w] = local[:h, :w]
    return full


@dataclass
class TrackFrame:
    frame: int  # index in the video that was sent to the segmenter
    box: tuple[float, float, float, float]  # x1, y1, x2, y2 (half-open) in that video's pixels
    score: float | None
    decode_mask: Callable[[], np.ndarray] | None = None  # -> bool array (H, W), for non-SAM backends
    mask_spec: MaskSpec | None = None  # SAM masks: decoded only when needed

    def mask(self) -> np.ndarray:
        if self.mask_spec is not None:
            return decode_mask_spec(self.mask_spec)
        if self.decode_mask is None:
            raise ValueError("track frame has no mask")
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


# Wire grammar from Meta's meta-sam-parser README ("Parsing behavior"): one line per frame,
#   <Nf>id<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..[;c=..]|><|mask;x=0;y=0;[c=..;]data=H,W,<enc>payload|>,id<|box..
# Fields are ';'-separated key=value pairs read by name; x2/y2 are inclusive; the mask payload never
# contains '|'. Meta's parser decodes every mask while parsing (minutes per video in pure Python), so
# we read the tokens here and decode only the masks the finder needs, with Meta's decoder.
# tests/test_segmenter.py checks this against the official parser on the probe fixture.
_FRAME = re.compile(r"^<(\d+)f>")
_RECORD = re.compile(r"(\d+)<\|box;([^|]*)\|><\|mask;([^|]*)\|>")


def _fields(token: str) -> dict[str, str]:
    out = {}
    for part in token.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def parse_sam_output(text: str, prompt: str, size: tuple[int, int]) -> list[Track]:
    """Parse SAM 3.1 video output text into tracks without decoding masks.

    `size` is the (width, height) of the video that was sent.
    """
    tracks: dict[str, Track] = {}
    for line in text.splitlines():
        m = _FRAME.match(line.strip())
        if not m:
            continue
        frame = int(m.group(1))
        for rec in _RECORD.finditer(line):
            obj, box, mask = rec.group(1), _fields(rec.group(2)), _fields(rec.group(3))
            try:
                x1, y1, x2, y2 = (int(box[k]) for k in ("x1", "y1", "x2", "y2"))
                h, w, payload = mask["data"].split(",", 2)
            except (KeyError, ValueError):
                logger.warning("Malformed SAM record on frame %d: %.80s", frame, rec.group(0))
                continue
            encoding = {"~": "lossless", "!": "one_bit"}.get(payload[:1])
            if encoding is None:
                logger.warning("Unknown SAM mask encoding on frame %d", frame)
                continue
            score = float(box["c"]) if "c" in box else None
            track = tracks.setdefault(obj, Track(f"{prompt}:{obj}", prompt))
            # Later lines for the same frame and object replace earlier ones, like the official parser.
            track.frames[frame] = TrackFrame(
                frame=frame,
                box=(float(x1), float(y1), float(x2 + 1), float(y2 + 1)),
                score=score if score is not None and 0 <= score <= 1 else None,
                mask_spec=MaskSpec(encoding, payload, int(w), int(h),
                                   x1 + int(mask.get("x", 0)), y1 + int(mask.get("y", 0)), size),
            )
    return list(tracks.values())


def parse_sam_output_official(text: str) -> list[tuple[int, str, tuple[int, int, int, int], SegmentationMask]]:
    """Meta's parser (strict, decodes every mask). Used in tests to check `parse_sam_output`."""
    parser = video_segmentation_format().create_parser()
    parser.push(text)
    result = parser.finish(CompletedOutcome()).result
    boxes = {(r.frame.frame_index, r.object_id): r for r in result.records if isinstance(r, SegmentationBoxRecord)}
    out = []
    for r in result.records:
        if isinstance(r, SegmentationMaskRecord):
            b = boxes[(r.frame.frame_index, r.object_id)]
            out.append((r.frame.frame_index, r.object_id, (b.left, b.top, b.right, b.bottom), r.mask))
    return out


class Sam3ModalSegmenter:
    """SAM 3 open weights on a Modal GPU. Not built yet; same interface as the API backend."""

    name = "sam3_modal"

    def segment_video(self, path: Path, prompts: Sequence[str]) -> SegmentResult:
        raise NotImplementedError("sam3_modal is a placeholder; set SEGMENTER=sam31_api")
