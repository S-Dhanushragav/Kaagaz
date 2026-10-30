"""Video probing and frame sampling.

`resample_video` decodes the source once and produces both:
- a small, low-fps copy for the segmenter (fewer billed frames, smaller upload), and
- full-resolution JPEGs of the same frames, which crops are later cut from.
Decoding goes through OpenCV's bundled FFmpeg, so H.264 and H.265/HEVC phone videos both work;
rotation metadata (portrait phone videos) is applied automatically by OpenCV.
"""

import shutil
import subprocess
from pathlib import Path

import cv2
from pydantic import BaseModel

UPLOAD_FPS = 30


def normalize_upload(src: Path, dst: Path, max_s: float, long_side: int = 1920) -> float:
    """Browser recordings (WebM from Android Chrome, MP4/HEVC from iPhones) often have a variable frame rate
    and no duration in the header. Re-encode to constant 30 fps H.264, long side at most `long_side` px, no audio,
    cut at `max_s` + 1 s; returns the duration in seconds (frames / 30). Needs ffmpeg on PATH."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is needed to read uploaded videos")
    scale = f"scale='if(gt(iw,ih),min({long_side},iw),-2)':'if(gt(iw,ih),-2,min({long_side},ih))'"
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", str(src), "-t", str(max_s + 1), "-an", "-vf", scale,
           "-r", str(UPLOAD_FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", str(dst)]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if done.returncode != 0 or not dst.exists():
        raise ValueError(f"cannot read this video: {done.stderr.strip()[-300:]}")
    cap = _open(dst)
    try:
        frames = 0
        while cap.grab():
            frames += 1
    finally:
        cap.release()
    if frames == 0:
        raise ValueError("the video has no frames")
    return frames / UPLOAD_FPS


class VideoInfo(BaseModel):
    path: str
    fps: float
    n_frames: int  # as reported by the container; may be approximate
    width: int
    height: int
    codec: str  # FourCC, e.g. 'avc1', 'hev1', 'mp4v'


class ResampledVideo(BaseModel):
    source: VideoInfo
    path: str  # the low-fps copy for the segmenter
    fps: float
    width: int
    height: int
    source_indices: list[int]  # frame i of the copy = source frame source_indices[i]
    frames_dir: str  # full-resolution JPEGs named <source index>.jpg


def _open(path: Path) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {path}")
    return cap


def probe_video(path: Path) -> VideoInfo:
    cap = _open(path)
    try:
        fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
        codec = "".join(chr((fourcc >> (8 * i)) & 0xFF) for i in range(4)).strip("\x00")
        ok, first = cap.read()
        if not ok:
            raise ValueError(f"Cannot decode frames from {path} (codec {codec!r})")
        height, width = first.shape[:2]  # after any rotation metadata
        return VideoInfo(
            path=str(path), fps=float(cap.get(cv2.CAP_PROP_FPS)) or 30.0,
            n_frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), width=width, height=height, codec=codec,
        )
    finally:
        cap.release()


def full_frame_path(frames_dir: Path, source_index: int) -> Path:
    return frames_dir / f"{source_index:06d}.jpg"


def resample_video(
    src: Path, dst: Path, frames_dir: Path, *, target_fps: float = 5.0, long_side: int = 1280
) -> ResampledVideo:
    """Keep about `target_fps` frames per second; write a `long_side`-px copy to `dst` and
    full-resolution JPEGs of the kept frames to `frames_dir`."""
    info = probe_video(src)
    step = max(info.fps / target_fps, 1.0)
    scale = min(1.0, long_side / max(info.width, info.height))
    size = (round(info.width * scale / 2) * 2, round(info.height * scale / 2) * 2)  # even dims for codecs
    out_fps = info.fps / step

    frames_dir.mkdir(parents=True, exist_ok=True)
    dst.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(dst), cv2.VideoWriter_fourcc(*"mp4v"), out_fps, size)
    if not writer.isOpened():
        raise RuntimeError("OpenCV could not open an mp4v video writer")
    cap = _open(src)
    kept: list[int] = []
    next_pick, i = 0.0, 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if i >= round(next_pick):
                writer.write(cv2.resize(frame, size, interpolation=cv2.INTER_AREA) if scale < 1 else frame)
                cv2.imwrite(str(full_frame_path(frames_dir, i)), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                kept.append(i)
                next_pick += step
            i += 1
    finally:
        cap.release()
        writer.release()
    if not kept:
        raise ValueError(f"No frames decoded from {src}")
    return ResampledVideo(
        source=info, path=str(dst), fps=out_fps, width=size[0], height=size[1],
        source_indices=kept, frames_dir=str(frames_dir),
    )
