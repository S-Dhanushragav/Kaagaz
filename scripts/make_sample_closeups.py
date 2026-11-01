"""Bundle the sample family: its photos, and clear close-up photos keyed by the finder's document ids.

    python scripts/make_sample_closeups.py --photos EV012 --unclear caste_certificate_m1   # the sample family
    python scripts/make_sample_closeups.py [--video HH009]    # the sample sweep video (testing)

--photos: copies the household's photo-like SPECIMEN images (one document each) to data/sample/<id>/photoNN.jpg,
in a fixed order (ration card first), and its clean renders to data/sample/closeups/<id>/docNNa.jpg: photo mode names
the only document in photo NN "docNNa" (graph/nodes/find_photos.py). Nothing is read or segmented here; the app
runs the photos through the real pipeline. --unclear blurs one document's photo (a shaky hand-held shot) so the
demo shows the close-up loop; the reader then decides, as for any photo, whether it needs a clearer one.

--video: runs the finder on the sample sweep (the segmenter call is cached), matches each found document to the video's
ground truth by corner overlap (as in eval/run_finder_eval.py), and writes that document's photo-like SPECIMEN
image to data/sample/closeups/<video>/<found id>.jpg. The app offers these as "Use sample close-up".
"""

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]

from clients.segmenter import Sam31ApiSegmenter  # noqa: E402
from eval.run_finder_eval import match_documents  # noqa: E402
from graph.nodes.find_documents import find_documents  # noqa: E402
from vision.images import read_image  # noqa: E402

LONG_SIDE = 1280
UNCLEAR_BLUR_PX = 21
ORDER = ("ration_card", "identity_card", "income_certificate", "caste_certificate")


def _jpeg(image, quality: int = 85, long_side: int | None = LONG_SIDE) -> bytes:
    scale = min(1.0, long_side / max(image.shape[:2])) if long_side else 1.0
    image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else image
    ok, jpg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return jpg.tobytes()


def shaky(image, length: int = UNCLEAR_BLUR_PX):
    """Motion blur along a slight diagonal, like a hand moving during the shot."""
    kernel = np.zeros((length, length), np.float32)
    cv2.line(kernel, (0, length // 3), (length - 1, 2 * length // 3), 1.0, 1)
    return cv2.filter2D(image, -1, kernel / kernel.sum())


def bundle_photos(household_id: str, unclear: str | None = None, blur: int = UNCLEAR_BLUR_PX) -> None:
    household = ROOT / "synthetic" / "eval_households" / household_id
    gt = json.loads((household / "ground_truth.json").read_text(encoding="utf-8"))
    documents = sorted(gt["documents"], key=lambda d: (ORDER.index(d["type"]), d["id"]))
    photos = ROOT / "data" / "sample" / household_id
    closeups = ROOT / "data" / "sample" / "closeups" / household_id
    photos.mkdir(parents=True, exist_ok=True)
    closeups.mkdir(parents=True, exist_ok=True)
    mapping = {}
    for n, d in enumerate(documents, start=1):
        if d["id"] == unclear:
            (photos / f"photo{n:02d}.jpg").write_bytes(_jpeg(shaky(read_image(household / d["files"]["photo"]), blur),
                                                             long_side=None, quality=70))
        else:
            (photos / f"photo{n:02d}.jpg").write_bytes((household / d["files"]["photo"]).read_bytes())
        (closeups / f"doc{n:02d}a.jpg").write_bytes(_jpeg(read_image(household / d["files"]["clean"])))
        mapping[f"doc{n:02d}a"] = d["id"]
        print(f"photo{n:02d}.jpg / doc{n:02d}a -> {d['id']}")
    (closeups / "mapping.json").write_text(json.dumps(mapping, indent=2) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--video", default="HH009")
    parser.add_argument("--photos", help="an evaluation household (e.g. EV012): bundle its photos as the sample")
    parser.add_argument("--unclear", help="with --photos: the document whose photo is blurred (e.g. caste_certificate_m1)")
    parser.add_argument("--blur", type=int, default=UNCLEAR_BLUR_PX, help="motion blur length in px")
    args = parser.parse_args()
    if args.photos:
        bundle_photos(args.photos, args.unclear, args.blur)
        return
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
