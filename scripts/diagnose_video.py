"""Dump every finder/reader stage for one video, to see where a real phone video fails.

Usage (from the repo root, with the backend venv):
    python scripts/diagnose_video.py <video> <out dir> [--no-read] [--raw]

Steps, as the server runs them: normalize the upload (constant 30 fps H.264, rotation applied) -> sample frames
-> SAM tracks -> cleanup -> chosen frames and sharpness -> crops exactly as sent to the reader -> per-frame reads
-> frame agreement -> the recapture rule behind the final message. --raw skips the upload normalization (the
bundled sample video is used as is by the server). Writes <out>/report.json, crops/ and frames/ (synthetic
SPECIMEN documents only).
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend")]

from app.config import get_settings  # noqa: E402
from clients.segmenter import Sam31ApiSegmenter, SegmentResult  # noqa: E402
from graph.build import no_documents  # noqa: E402
from graph.nodes.find_documents import RecapturePlan, find_documents  # noqa: E402
from graph.nodes.read_documents import StreamingReader  # noqa: E402
from graph.nodes.triage import seen_from, triage  # noqa: E402
from vision.frames import normalize_upload, probe_video  # noqa: E402
from vision.tracks import box_area  # noqa: E402


def ffprobe(path: Path) -> dict[str, Any]:
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
           "stream=codec_name,width,height,r_frame_rate,avg_frame_rate,nb_frames,bit_rate:stream_side_data=rotation",
           "-of", "json", str(path)]
    try:
        return json.loads(subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout)["streams"][0]
    except Exception as e:  # noqa: BLE001 - diagnostic only
        return {"error": str(e)}


def sample_frames(video: Path, out: Path, every_s: float = 2.0) -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step, i, saved = max(1, round(fps * every_s)), 0, []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % step == 0:
            p = out / f"{i:05d}.jpg"
            cv2.imwrite(str(p), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            saved.append(f"{p.name} {frame.shape[1]}x{frame.shape[0]}")
        i += 1
    cap.release()
    return saved


class RecordingSegmenter:
    def __init__(self) -> None:
        self.inner = Sam31ApiSegmenter()
        self.result: SegmentResult | None = None

    def segment_video(self, path: Path, prompts: Any) -> SegmentResult:
        self.result = self.inner.segment_video(path, prompts)
        return self.result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--no-read", action="store_true")
    ap.add_argument("--raw", action="store_true", help="skip upload normalization (as for the bundled sample)")
    args = ap.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    report: dict[str, Any] = {"video": str(args.video), "source": ffprobe(args.video), "timings": {}}

    video = args.video
    if not args.raw:
        t0 = time.perf_counter()
        video = out / "normalized.mp4"
        seconds = normalize_upload(args.video, video, settings.max_video_s, settings.upload_long_side)
        report["timings"]["normalize_s"] = round(time.perf_counter() - t0, 2)
        report["normalized"] = {"seconds": round(seconds, 2), **probe_video(video).model_dump()}
    report["sampled_frames"] = sample_frames(video, out / "frames")

    seg = RecordingSegmenter()
    t0 = time.perf_counter()
    found_docs = []
    reader = None if args.no_read else StreamingReader(agreement=True)

    def on_document(d: Any) -> None:
        found_docs.append(d)
        if reader is not None:
            reader.submit(d.document)

    result = find_documents(video, segmenter=seg, on_document=on_document, debug=True, tmp_root=out)
    report["timings"]["find_s"] = round(time.perf_counter() - t0, 2)
    report["find"] = result.model_dump(mode="json", exclude={"documents"})

    s = seg.result
    if s is not None:
        report["tracks"] = [{
            "id": t.track_id, "frames": len(t.frames), "first": min(t.frames), "last": max(t.frames),
            "mean_score": round(sum(f.score or 0 for f in t.frames.values()) / len(t.frames), 3),
            "median_area_frac": round(sorted(box_area(f.box) for f in t.frames.values())[len(t.frames) // 2]
                                      / (s.frame_size[0] * s.frame_size[1]), 4),
        } for t in s.tracks]

    crops = out / "crops"
    crops.mkdir(exist_ok=True)
    docs = []
    for d in result.documents:
        names = []
        for i, img in enumerate(d.document.images):
            p = crops / f"{d.document.id}_f{i + 1}.jpg"
            p.write_bytes(img)
            im = cv2.imread(str(p))
            names.append(f"{p.name} {im.shape[1]}x{im.shape[0]}")
        docs.append({"id": d.document.id, "track": d.track_id, "frames": d.source_frames, "methods": d.methods,
                     "sharpness": d.sharpness, "quads": d.quads, "relaxed": d.relaxed_selection,
                     "fully_visible": d.fully_visible, "crops": names})
    report["documents"] = docs

    if reader is not None:
        t0 = time.perf_counter()
        with reader:
            reads = reader.results()
        report["timings"]["read_wait_s"] = round(time.perf_counter() - t0, 2)
        sorted_reads = triage(seen_from(result), reads)
        extractions = sorted_reads.extractions
        report["dropped_after_reading"] = sorted_reads.dropped
        report["duplicates"] = sorted_reads.duplicates
        for doc in docs:
            r = reads.get(doc["id"])
            if r is None:
                continue
            doc["frame_reads"] = [{"doc_type": e.doc_type, "unreadable": e.unreadable, "error": e.error,
                                   "fields": e.fields.model_dump() if e.fields else None} for e in r.frame_reads]
            e = extractions.get(doc["id"], r.extraction)
            doc["kept"] = doc["id"] in extractions
            doc["agreed"] = {"doc_type": e.doc_type, "unreadable": e.unreadable, "error": e.error,
                             "needs_retake": e.needs_retake, "retake_reasons": e.retake_reasons,
                             "disagreed": e.disagreed_fields, "strength": e.agreement_strength}
        plan = sorted_reads.plan
        if no_documents(list(extractions.values())):
            plan = RecapturePlan(mode="no_documents", read=plan.read)
        report["recapture"] = plan.model_dump(mode="json")
        report["usage_tokens"] = sum(r.usage.total_tokens for r in reads.values())

    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({k: report.get(k) for k in ("timings", "recapture", "usage_tokens", "duplicates")}, indent=2))
    for doc in docs:
        print(doc["id"], "kept" if doc.get("kept") else "DROPPED", doc["track"], doc["fully_visible"], doc["methods"], doc["sharpness"], doc["crops"],
              (doc.get("agreed") or {}).get("doc_type"), (doc.get("agreed") or {}).get("retake_reasons"),
              [f["doc_type"] for f in doc.get("frame_reads", [])])


if __name__ == "__main__":
    main()
