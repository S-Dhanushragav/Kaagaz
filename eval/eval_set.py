"""The evaluation households, minus the held-out ones.

EV012 is the app's sample family (data/sample/EV012, "Try with a sample family"), so it is no longer scored: the
demo household is not also a test household. Every eval that walks synthetic/eval_households uses `folders()`.
"""

from pathlib import Path

EVAL = Path(__file__).resolve().parents[1] / "synthetic" / "eval_households"
HELD_OUT = {"EV012": "the app's sample family (data/sample/EV012)"}


def folders() -> list[Path]:
    return [f for f in sorted(EVAL.glob("EV*")) if f.is_dir() and f.name not in HELD_OUT]
