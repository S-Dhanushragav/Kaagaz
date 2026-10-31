"""Photo mode on the evaluation set: each household's photo-like document images go through the app's photo path.

Usage (from the repo root, with the backend venv):
    python eval/run_photo_eval.py --households 10          # EV001-EV010, one photo per document
    python eval/run_photo_eval.py --households 10 --pairs  # two documents side by side in each photo
    python eval/run_photo_eval.py --dry-run

Per household: find_in_photos (SAM 3.1 on each photo, upright crops) -> two reads per document that must agree
(StreamingReader with agreement) -> triage (duplicates merged, background dropped) -> scored against
ground_truth.json with the reader eval's correct / wrong / null split.

A document counts as a success when it is found, read as the right type, not put on the clearer-photo list, and none
of its fields is read wrong. Wrong values are misreads that passed agreement (the number that must not grow).
Reports the time per household (photos on disk -> all documents read; upload time not included).
Results -> eval/results/photos_<timestamp>.json.
"""

import argparse
import json
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]

from clients.segmenter import Sam31ApiSegmenter  # noqa: E402
from eval.run_reader_eval import expected_fields  # noqa: E402
from graph.nodes.find_photos import find_in_photos  # noqa: E402
from graph.nodes.read_documents import StreamingReader  # noqa: E402
from graph.nodes.triage import seen_from, triage  # noqa: E402
from synthetic.scoring import FieldScore, score_fields  # noqa: E402

EVAL = ROOT / "synthetic" / "eval_households"
RESULTS = ROOT / "eval" / "results"


def side_by_side(a: Path, b: Path, out: Path) -> None:
    """Two document photos next to each other on a plain background, as one photo."""
    ia, ib = cv2.imread(str(a)), cv2.imread(str(b))
    h = max(ia.shape[0], ib.shape[0])
    pad = 60
    canvas = np.full((h + 2 * pad, ia.shape[1] + ib.shape[1] + 3 * pad, 3), (120, 128, 136), np.uint8)
    canvas[pad:pad + ia.shape[0], pad:pad + ia.shape[1]] = ia
    canvas[pad:pad + ib.shape[0], 2 * pad + ia.shape[1]:2 * pad + ia.shape[1] + ib.shape[1]] = ib
    cv2.imwrite(str(out), canvas, [cv2.IMWRITE_JPEG_QUALITY, 92])


def run_household(folder: Path, pairs: bool, tmp: Path) -> dict[str, Any]:
    gt = json.loads((folder / "ground_truth.json").read_text(encoding="utf-8"))
    docs = gt["documents"]
    if pairs:
        photos, owners = [], []
        for i in range(0, len(docs), 2):
            group = docs[i:i + 2]
            if len(group) == 2:
                path = tmp / f"{folder.name}_{i}.jpg"
                side_by_side(folder / group[0]["files"]["photo"], folder / group[1]["files"]["photo"], path)
            else:
                path = folder / group[0]["files"]["photo"]
            photos.append(path)
            owners.append([d["id"] for d in group])
    else:
        photos = [folder / d["files"]["photo"] for d in docs]
        owners = [[d["id"]] for d in docs]

    t0 = time.perf_counter()
    with StreamingReader(agreement=True) as reader:
        result = find_in_photos(photos, segmenter=Sam31ApiSegmenter(), on_document=lambda d: reader.submit(d.document))
        find_s = time.perf_counter() - t0
        reads = reader.results()
    total_s = time.perf_counter() - t0
    sorted_reads = triage(seen_from(result), reads)

    # Match: each kept document belongs to its photo (doc<photo><letter>); within a photo, by type and fields.
    by_photo: dict[int, list[str]] = {}
    for doc_id in sorted_reads.extractions:
        by_photo.setdefault(int(doc_id[3:5]) - 1, []).append(doc_id)
    gt_docs = {d["id"]: d for d in docs}
    details, fields, success = [], FieldScore(), 0
    used: set[str] = set()
    for p, ids in enumerate(owners):
        for truth_id in ids:
            truth = gt_docs[truth_id]
            candidates = [d for d in by_photo.get(p, []) if d not in used]
            # Same type in one photo (two Aadhaar cards side by side): the read that agrees with this document best.
            same = [d for d in candidates if sorted_reads.extractions[d].doc_type == truth["type"]]
            match = max(same, key=lambda d: score_fields(expected_fields(truth), (sorted_reads.extractions[d].fields.model_dump()
                        if sorted_reads.extractions[d].fields is not None else None)).correct, default=None)
            ex = sorted_reads.extractions[match] if match else None
            if match:
                used.add(match)
            predicted = ex.fields.model_dump() if ex is not None and ex.fields is not None else None
            s = score_fields(expected_fields(truth), predicted)
            fields.add(s)
            ok = ex is not None and not ex.needs_retake and not s.wrong
            success += ok
            details.append({"truth": truth_id, "found": match, "type_ok": ex is not None, "clear": ex is not None and not ex.needs_retake,
                            "retake_reasons": ex.retake_reasons if ex else [], "success": ok,
                            "wrong": [{"field": f, "expected": e, "got": g} for f, e, g in s.wrong],
                            "null": [f for f, _ in s.null]})
    extra = [d for d in sorted_reads.extractions if d not in used]
    return {"household": folder.name, "photos": len(photos), "documents": len(docs), "success": success,
            "found_docs": len(result.documents), "extra": extra, "dropped": sorted_reads.dropped,
            "unidentified": sorted_reads.plan.unidentified, "mode": sorted_reads.plan.mode,
            "correct": fields.correct, "wrong": len(fields.wrong), "null": len(fields.null),
            "timings": {"find_s": round(find_s, 2), "total_s": round(total_s, 2), **result.timings},
            "model_calls": sum(len(r.frame_reads) or 1 for r in reads.values()), "details": details}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--households", type=int, default=10)
    parser.add_argument("--pairs", action="store_true", help="two documents per photo")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    folders = sorted(EVAL.glob("EV*"))[: args.households]
    if args.dry_run:
        n = sum(len(json.loads((f / "ground_truth.json").read_text(encoding="utf-8"))["documents"]) for f in folders)
        print(f"{len(folders)} households, {n} documents: ~{n if not args.pairs else (n + 1) // 2} SAM images, ~{2 * n} reads")
        return
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for f in folders:
            row = run_household(f, args.pairs, Path(tmp))
            rows.append(row)
            print(f"{row['household']}: {row['success']}/{row['documents']} success, wrong {row['wrong']}, "
                  f"null {row['null']}, extra {row['extra']}, mode {row['mode']}, {row['timings']['total_s']} s "
                  f"({row['photos']} photos)")
    docs = sum(r["documents"] for r in rows)
    ok = sum(r["success"] for r in rows)
    times = [r["timings"]["total_s"] for r in rows]
    summary = {"households": len(rows), "documents": docs, "success": ok, "success_rate": round(ok / docs, 3) if docs else None,
               "correct": sum(r["correct"] for r in rows), "wrong": sum(r["wrong"] for r in rows),
               "null": sum(r["null"] for r in rows), "extra": sum(len(r["extra"]) for r in rows),
               "time_s": {"mean": round(float(np.mean(times)), 1), "max": round(max(times), 1)}, "pairs": args.pairs}
    print(json.dumps(summary, indent=2))
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"photos{'_pairs' if args.pairs else ''}_{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
