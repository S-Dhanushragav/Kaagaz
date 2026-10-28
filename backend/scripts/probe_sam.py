"""One SAM 3.1 probe call on a 50-frame clip (the billing minimum: 50 frames = $0.01).

Usage (from backend/):
    python scripts/probe_sam.py                  # HH008 sweep, first 10 s at 5 fps, 720p, prompt "document"

Prints latency and the output shape, saves the raw output to tmp/sam_probe_raw.txt (gitignored)
and a 2-frame fixture to tests/fixtures/sam31_video_output.txt for parser tests.
"""

import argparse
import re
import shutil
import sys
import time
from pathlib import Path

import cv2

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path[:0] = [str(BACKEND)]

from clients.segmenter import Sam31ApiSegmenter  # noqa: E402
from vision.frames import resample_video  # noqa: E402

FIXTURE = BACKEND / "tests" / "fixtures" / "sam31_video_output.txt"


def make_clip(src: Path, dst: Path, n_frames: int = 50) -> tuple[int, tuple[int, int]]:
    work = ROOT / "tmp" / "probe"
    rs = resample_video(src, work / "all.mp4", work / "frames", target_fps=5, long_side=1280)
    cap = cv2.VideoCapture(rs.path)
    writer = cv2.VideoWriter(str(dst), cv2.VideoWriter_fourcc(*"mp4v"), rs.fps, (rs.width, rs.height))
    n = 0
    while n < n_frames:
        ok, frame = cap.read()
        if not ok:
            break
        writer.write(frame)
        n += 1
    cap.release()
    writer.release()
    shutil.rmtree(work, ignore_errors=True)
    return n, (rs.width, rs.height)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--video", type=Path, default=ROOT / "synthetic" / "videos" / "HH008" / "sweep.mp4")
    parser.add_argument("--prompt", default="document")
    args = parser.parse_args()

    clip = ROOT / "tmp" / "sam_probe_clip.mp4"
    clip.parent.mkdir(exist_ok=True)
    n, size = make_clip(args.video, clip)
    print(f"Clip: {n} frames at 5 fps, {size[0]}x{size[1]}, {clip.stat().st_size / 1e6:.1f} MB")

    start = time.perf_counter()
    raw = Sam31ApiSegmenter().raw_segment(clip, args.prompt)
    total = time.perf_counter() - start
    print(f"Cached: {raw.cached}  upload {raw.timings['upload_s']} s, segment {raw.timings['segment_s']} s, "
          f"total {total:.1f} s")

    lines = [ln for ln in raw.text.splitlines() if ln.strip()]
    frames = [int(m.group(1)) for ln in lines if (m := re.match(r"<(\d+)f>", ln))]
    objects = sorted({int(i) for ln in lines for i in re.findall(r"(?:^<\d+f>|,)(\d+)<\|box", ln)})
    print(f"Output: {len(raw.text)} chars, {len(lines)} lines, frames {frames[:5]}...{frames[-3:] if frames else []}, "
          f"object ids {objects}")
    print("First 400 chars:", raw.text[:400])

    (ROOT / "tmp" / "sam_probe_raw.txt").write_text(raw.text, encoding="utf-8")
    FIXTURE.parent.mkdir(exist_ok=True)
    FIXTURE.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")
    print(f"Saved fixture ({len(lines[:2])} frame lines) to {FIXTURE.relative_to(ROOT)}")
    clip.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
