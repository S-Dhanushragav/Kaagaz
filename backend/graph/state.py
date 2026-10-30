"""Shared state of the pipeline graph (graph/build.py).

Values are JSON-friendly dicts (Pydantic `model_dump(mode="json")`), so the checkpointer can store them and
the API can return them as partial results. Large or live objects (crop images, the streaming reader, the
finder's result with image bytes) stay out of the state, in graph/runtime.py.
"""

import operator
from typing import Annotated, Any, Literal, TypedDict

Language = Literal["en", "hi", "mr"]
STAGES = ("find_documents", "read_documents", "build_household", "check_rules", "plan_fixes", "speak")


def merge(a: dict, b: dict) -> dict:
    return {**(a or {}), **(b or {})}


def add_counts(a: dict, b: dict) -> dict:
    out = dict(a or {})
    for k, v in (b or {}).items():
        out[k] = out.get(k, 0) + v
    return out


class KaagazState(TypedDict, total=False):
    session_id: str
    language: Language
    video_path: str | None
    delete_video: bool  # uploads are deleted right after finding; the bundled sample is not
    reference_date: str  # ISO date the rules are checked on
    found: list[dict[str, Any]]  # per document: id, frames, fully visible
    extractions: list[dict[str, Any]]
    recapture: dict[str, Any]
    household: dict[str, Any]
    results: list[dict[str, Any]]  # scheme results per member
    issues: list[dict[str, Any]]  # issues as the planner saw them
    waiting: list[dict[str, Any]]  # issues held back until a document on the close-up list is photographed clearly
    plan: dict[str, Any]
    speech: list[dict[str, Any]]  # per plan step: screen text and TTS text
    timings: Annotated[dict[str, float], merge]  # seconds per stage
    usage: Annotated[dict[str, int], add_counts]  # tokens per stage kind
    log: Annotated[list[str], operator.add]
