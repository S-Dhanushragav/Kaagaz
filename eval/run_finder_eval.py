"""Evaluate the document finder (and optionally end-to-end reading) on the synthetic sweep videos.

Usage (from the repo root, with the backend venv):
    python eval/run_finder_eval.py --prompts document paper card --videos HH008 --no-read   # prompt comparison
    python eval/run_finder_eval.py --prompts document                                      # all videos, end to end
    python eval/run_finder_eval.py --dry-run

Finder metrics against video_truth.json: documents found / present, duplicates, false detections,
crop accuracy (IoU of the found corners with the true corners on the chosen frames).
End to end: read_documents (muse-spark-1.3, effort low) on the found crops, scored against
ground_truth.json with the reader eval's correct / wrong / null split; documents never found
count all their fields as null. Reports time per stage and cost.
"""

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]

from clients.segmenter import Sam31ApiSegmenter  # noqa: E402
from eval.run_reader_eval import expected_fields  # noqa: E402
from graph.nodes.find_documents import FindResult, find_documents  # noqa: E402
from graph.nodes.read_documents import read_documents  # noqa: E402
from synthetic.scoring import FieldScore, score_fields  # noqa: E402

VIDEOS = ROOT / "synthetic" / "videos"
HOUSEHOLDS = ROOT / "synthetic" / "households"
RESULTS = ROOT / "eval" / "results"
ALL_VIDEOS = ["HH001", "HH008", "HH009", "HH008_hard"]
MATCH_IOU = 0.5

# Prices from https://dev.meta.ai/docs/pricing-rate-limits (checked 2026-10-29).
SAM_PER_FRAME = 0.20 / 1000
LLM_INPUT_PER_TOKEN = 1.25 / 1e6
LLM_OUTPUT_PER_TOKEN = 4.25 / 1e6
READ_OVERRIDES = {"provider": "meta", "model": "muse-spark-1.3", "reasoning_effort": "low"}


def quad_iou(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a.astype(np.float32), b.astype(np.float32)
    inter, _ = cv2.intersectConvexConvex(a, b)
    union = cv2.contourArea(a) + cv2.contourArea(b) - inter
    return float(inter / union) if union > 0 else 0.0


def match_documents(result: FindResult, truth: dict[str, Any]) -> list[dict[str, Any]]:
    """For each found document: the true document it overlaps best on its chosen frames, and the IoU."""
    frames = truth["frames"]
    out = []
    for f in result.documents:
        per_doc: dict[str, list[float]] = defaultdict(list)
        for frame, quad in zip(f.source_frames, f.quads):
            visible = frames[frame]["docs"]
            for doc_id in {d["id"] for d in truth["documents"]}:
                true = visible.get(doc_id)
                per_doc[doc_id].append(quad_iou(np.array(quad), np.array(true["corners"])) if true else 0.0)
        best = max(per_doc, key=lambda d: np.mean(per_doc[d]))
        iou = float(np.mean(per_doc[best]))
        out.append({"found": f.document.id, "track": f.track_id, "truth": best if iou >= MATCH_IOU else None,
                    "iou": round(iou, 3), "frames": f.source_frames, "methods": f.methods,
                    "fully_visible": f.fully_visible})
    # Several found documents on one true document: the best match counts, the rest are duplicates.
    by_truth: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for m in out:
        if m["truth"]:
            by_truth[m["truth"]].append(m)
    for ms in by_truth.values():
        ms.sort(key=lambda m: m["iou"], reverse=True)
        for dup in ms[1:]:
            dup["duplicate_of"] = ms[0]["found"]
    return out


def evaluate_video(video_id: str, prompts: list[str], read: bool, debug: bool) -> dict[str, Any]:
    truth = json.loads((VIDEOS / video_id / "video_truth.json").read_text(encoding="utf-8"))
    gt = json.loads((HOUSEHOLDS / truth["household"] / "ground_truth.json").read_text(encoding="utf-8"))
    gt_docs = {d["id"]: d for d in gt["documents"]}
    present = [d["id"] for d in truth["documents"]
               if any(fr["docs"].get(d["id"], {}).get("visible", 0) >= 0.999 for fr in truth["frames"])]

    t0 = time.perf_counter()
    result = find_documents(VIDEOS / video_id / "sweep.mp4", segmenter=Sam31ApiSegmenter(), prompts=prompts, debug=debug)
    find_s = time.perf_counter() - t0
    matches = match_documents(result, truth)
    primary = {m["truth"]: m for m in matches if m["truth"] and "duplicate_of" not in m}

    row: dict[str, Any] = {
        "video": video_id,
        "prompts": prompts,
        "present": len(present),
        "found": len(primary),
        "duplicates": sum("duplicate_of" in m for m in matches),
        "false_detections": sum(m["truth"] is None for m in matches),
        "crop_iou_mean": round(float(np.mean([m["iou"] for m in primary.values()])), 3) if primary else None,
        "crop_iou_min": round(min(m["iou"] for m in primary.values()), 3) if primary else None,
        "missed": sorted(set(present) - set(primary)),
        "tracks_raw": result.tracks_raw,
        "dropped": {k: len(v) for k, v in result.dropped.items()},
        "deskew_methods": dict(Counter(mth for m in matches for mth in m["methods"])),
        "billed_frames": result.billed_frames,
        "timings": {**result.timings, "find_total_s": round(find_s, 2)},
        "matches": matches,
    }
    cost = result.billed_frames * SAM_PER_FRAME

    if read:
        t0 = time.perf_counter()
        reads = read_documents([f.document for f in result.documents], overrides=READ_OVERRIDES)
        row["timings"]["read_s"] = round(time.perf_counter() - t0, 2)
        by_found = {f.document.id: r for f, r in zip(result.documents, reads)}
        fields, per_type, classified, details = FieldScore(), defaultdict(FieldScore), 0, []
        for doc_id in present:
            doc = gt_docs[doc_id]
            m = primary.get(doc_id)
            ex = by_found[m["found"]].extraction if m else None
            ok_type = ex is not None and ex.doc_type == doc["type"]
            classified += ok_type
            predicted = ex.fields.model_dump() if (ok_type and ex.fields is not None) else None
            s = score_fields(expected_fields(doc), predicted)
            fields.add(s)
            per_type[doc["type"]].add(s)
            details.append({"doc": doc_id, "found": m["found"] if m else None,
                            "predicted_type": ex.doc_type if ex else None,
                            "wrong": [{"field": p, "expected": e, "got": g} for p, e, g in s.wrong],
                            "null": [p for p, _ in s.null]})
        tokens_in = sum(r.usage.prompt_tokens for r in reads)
        tokens_out = sum(r.usage.completion_tokens for r in reads)
        cost += tokens_in * LLM_INPUT_PER_TOKEN + tokens_out * LLM_OUTPUT_PER_TOKEN
        row["reading"] = {
            "classified": classified,
            "fields": {"correct": fields.correct, "wrong": len(fields.wrong), "null": len(fields.null), "total": fields.total},
            "per_type": {t: {"correct": s.correct, "wrong": len(s.wrong), "null": len(s.null), "total": s.total}
                         for t, s in sorted(per_type.items())},
            "tokens": {"prompt": tokens_in, "completion": tokens_out},
            "details": details,
        }
    t = row["timings"]
    row["timings"]["upload_to_answer_s"] = round(sum(t.get(k, 0.0) for k in ("upload_s", "segment_s", "cleanup_s", "select_s", "mask_decode_s", "deskew_s", "read_s")), 2)
    row["cost_usd"] = round(cost, 4)
    return row


def _pct(n: int, total: int) -> str:
    return f"{n} ({100 * n / total:.1f}%)" if total else "-"


def print_rows(rows: list[dict[str, Any]]) -> None:
    print("\n| Video | Prompt | Found / present | Duplicates | False | Crop IoU mean / min | Raw tracks | Deskew |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['video']} | {'+'.join(r['prompts'])} | {r['found']}/{r['present']} | {r['duplicates']} | "
              f"{r['false_detections']} | {r['crop_iou_mean']} / {r['crop_iou_min']} | {r['tracks_raw']} | {r['deskew_methods']} |")
    print("\n| Video | Resample | Upload | SAM | Select | Mask decode | Deskew | Read | Upload->answer | Cost |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        t = r["timings"]
        print(f"| {r['video']} | {t.get('resample_s', 0):.1f} | {t.get('upload_s', 0):.1f} | {t.get('segment_s', 0):.1f} | "
              f"{t.get('select_s', 0):.1f} | {t.get('mask_decode_s', 0):.1f} | {t.get('deskew_s', 0):.1f} | {t.get('read_s', 0):.1f} | "
              f"{t['upload_to_answer_s']:.1f} | ${r['cost_usd']:.3f} |")
    reading = [r for r in rows if "reading" in r]
    if reading:
        print("\n| Video | Classified | Correct | Wrong value | Null |")
        print("|---|---|---|---|---|")
        for r in reading:
            f = r["reading"]["fields"]
            print(f"| {r['video']} | {r['reading']['classified']}/{r['present']} | {_pct(f['correct'], f['total'])} | "
                  f"{_pct(f['wrong'], f['total'])} | {_pct(f['null'], f['total'])} |")
    for r in rows:
        if r["missed"] or r["duplicates"] or r["false_detections"]:
            print(f"\n{r['video']} ({'+'.join(r['prompts'])}): missed {r['missed']}; "
                  + "; ".join(f"{m['found']} {m['track']} -> {m['truth']} (IoU {m['iou']})"
                              + (f" duplicate of {m['duplicate_of']}" if "duplicate_of" in m else "")
                              for m in r["matches"] if m["truth"] is None or "duplicate_of" in m))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--videos", nargs="+", default=ALL_VIDEOS, choices=ALL_VIDEOS)
    parser.add_argument("--prompts", nargs="+", default=["document"],
                        help="each prompt is evaluated separately (one SAM request each)")
    parser.add_argument("--no-read", action="store_true", help="finder metrics only; no LLM calls")
    parser.add_argument("--debug", action="store_true", help="keep a contact sheet of chosen crops in tmp/")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        for v in args.videos:
            t = json.loads((VIDEOS / v / "video_truth.json").read_text(encoding="utf-8"))
            frames = max(round(t["n_frames"] / t["fps"] * 5), 50)
            print(f"{v}: ~{frames} SAM frames per prompt (${frames * SAM_PER_FRAME:.3f}), {len(t['documents'])} documents")
        print(f"prompts: {args.prompts}; reading: {not args.no_read}")
        return

    rows = [evaluate_video(v, [p], read=not args.no_read, debug=args.debug) for p in args.prompts for v in args.videos]
    print_rows(rows)
    total = sum(r["cost_usd"] for r in rows)
    print(f"\nTotal cost: ${total:.3f} (cached calls are counted at their original cost)")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"finder_{'-'.join(args.prompts)}_{stamp}"
    (RESULTS / "raw").mkdir(parents=True, exist_ok=True)
    (RESULTS / "raw" / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = [{k: v for k, v in r.items() if k != "matches"} | (
        {"reading": {k: v for k, v in r["reading"].items() if k != "details"}} if "reading" in r else {})
        for r in rows]
    (RESULTS / f"{name}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved eval/results/{name}.json (details in eval/results/raw/)")


if __name__ == "__main__":
    main()
