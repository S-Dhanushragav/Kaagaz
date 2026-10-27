"""2x2 vision comparison on one photo-like synthetic document: model x reasoning effort.

Usage (from backend/):
    python scripts/compare_vision.py                      # ration card of the largest household
    python scripts/compare_vision.py --household HH008 --doc ration_card

Scores each reply field by field against ground_truth.json (synthetic/scoring.py).
Each cell uses resolve() overrides, so the cells never share a cached reply.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BACKEND), str(BACKEND.parent)]

from clients.llm import LLMError, complete  # noqa: E402
from synthetic.scoring import score  # noqa: E402
from vision.images import encode_for_llm, read_image  # noqa: E402

HOUSEHOLDS = BACKEND.parent / "synthetic" / "households"
PROMPT = (BACKEND / "prompts" / "smoke_extract.md").read_text(encoding="utf-8")
CELLS = [
    ("muse-spark-1.3", None),
    ("muse-spark-1.3", "low"),
    ("muse-spark-1.1", None),
    ("muse-spark-1.1", "low"),
]


def skeleton(value: Any) -> Any:
    """Same shape as the ground-truth fields, values blanked; lists show one example row."""
    if isinstance(value, dict):
        return {k: skeleton(v) for k, v in value.items()}
    if isinstance(value, list):
        return [skeleton(value[0])] if value else []
    return ""


def parse_json(text: str) -> dict[str, Any] | None:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def default_household() -> str:
    def rows(p: Path) -> int:
        gt = json.loads(p.read_text(encoding="utf-8"))
        card = next(d for d in gt["documents"] if d["type"] == "ration_card")
        return len(card["fields"]["members"])

    paths = sorted(HOUSEHOLDS.glob("HH*/ground_truth.json"))
    return max(paths, key=lambda p: (rows(p), -paths.index(p))).parent.name


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--household")
    parser.add_argument("--doc", default="ration_card")
    parser.add_argument("--max-tokens", type=int, default=8000)
    args = parser.parse_args()

    hh_id = args.household or default_household()
    gt = json.loads((HOUSEHOLDS / hh_id / "ground_truth.json").read_text(encoding="utf-8"))
    doc = next(d for d in gt["documents"] if d["id"] == args.doc)
    photo = HOUSEHOLDS / hh_id / doc["files"]["photo"]
    image = encode_for_llm(read_image(photo))
    prompt = PROMPT.replace("{schema}", json.dumps(skeleton(doc["fields"]), ensure_ascii=False, indent=2))
    print(f"Document: {hh_id}/{photo.name}  ({len(image) / 1024:.0f} KB sent)  photo: {doc['photo']}\n")

    results = []
    for model, effort in CELLS:
        overrides = {"provider": "meta", "model": model, "reasoning_effort": effort}
        start = time.perf_counter()
        try:
            resp = complete(prompt, task="vision", image=image, max_tokens=args.max_tokens, overrides=overrides)
        except LLMError as e:
            results.append((model, effort, None, None, time.perf_counter() - start, str(e)))
            continue
        elapsed = time.perf_counter() - start
        predicted = parse_json(resp.text)
        scored = score(doc["fields"], predicted or {})
        results.append((model, effort, scored, resp, elapsed, None if predicted else "reply was not JSON"))

    print("| Model | Effort | Accuracy | Completion tokens | Time (s) |")
    print("|---|---|---|---|---|")
    for model, effort, scored, resp, elapsed, error in results:
        if scored is None:
            print(f"| {model} | {effort or 'default'} | ERROR | - | {elapsed:.1f} |")
            continue
        correct, total, _ = scored
        t = "cached" if resp.cached else f"{elapsed:.1f}"
        print(
            f"| {model} | {effort or 'default'} | {correct}/{total} ({100 * correct / total:.0f}%) "
            f"| {resp.usage.completion_tokens} | {t} |"
        )

    for model, effort, scored, _, _, error in results:
        print(f"\n## {model} / {effort or 'default'}")
        if error:
            print(f"  {error}")
        for path, expected, got in (scored[2] if scored else []):
            print(f"  {path}: expected {expected!r}, got {got!r}")
        if scored and not scored[2]:
            print("  all fields correct")


if __name__ == "__main__":
    main()
