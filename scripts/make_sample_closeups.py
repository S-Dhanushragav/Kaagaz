"""Bundle clear close-up photos for the sample family, keyed by the finder's document ids.

    python scripts/make_sample_closeups.py [--video HH009]

Runs the finder on the sample sweep (the segmenter call is cached), matches each found document to the video's
ground truth by corner overlap (as in eval/run_finder_eval.py), and writes that document's photo-like SPECIMEN
image to data/sample/closeups/<video>/<found id>.jpg. The app offers these as "Use sample close-up".
"""

import argparse
import json
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]

from clients.segmenter import Sam31ApiSegmenter  # noqa: E402
from eval.run_finder_eval import match_documents  # noqa: E402
from graph.nodes.find_documents import find_documents  # noqa: E402
from vision.images import read_image  # noqa: E402

LONG_SIDE = 1280


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--video", default="HH009")
    args = parser.parse_args()
    video_dir = ROOT / "synthetic" / "videos" / args.video
    truth = json.loads((video_dir / "video_truth.json").read_text(encoding="utf-8"))
    household = ROOT / "synthetic" / "households" / truth["household"]
    gt = json.loads((household / "ground_truth.json").read_text(encoding="utf-8"))
    files = {d["id"]: d["files"]["photo"] for d in gt["documents"]}
    result = find_documents(video_dir / "sweep.mp4", segmenter=Sam31ApiSegmenter())
    out = ROOT / "data" / "sample" / "closeups" / args.video
    out.mkdir(parents=True, exist_ok=True)
    mapping = {}
    for m in match_documents(result, truth):
        if m["truth"] is None:
            continue
        image = read_image(household / files[m["truth"]])
        scale = min(1.0, LONG_SIDE / max(image.shape[:2]))
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else image
        ok, jpg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
        (out / f"{m['found']}.jpg").write_bytes(jpg.tobytes())
        mapping[m["found"]] = m["truth"]
        print(f"{m['found']} -> {m['truth']} (IoU {m['iou']})")
    (out / "mapping.json").write_text(json.dumps(mapping, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
