"""The pipeline as a LangGraph graph:

find_documents -> read_documents -> build_household -> check_rules -> plan_fixes -> speak

- find_documents streams each document to the reader as soon as its crops are ready (reading overlaps finding);
  an uploaded video is deleted as soon as the finder is done.
- read_documents collects the reads (frame agreement) and makes the recapture plan.
- build_household uses the name verifier (re-reads crops) and the adjudicator.
- plan_fixes pauses at each family question (LangGraph interrupt) and resumes with the answer.
- speak prepares the TTS text for every step and synthesizes the first sentence.
Every node records its time in `timings`. Dependencies are injectable (tests use fakes).
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from clients.llm import chat
from graph.nodes.build_household import build_household, llm_adjudicator, llm_name_verifier
from graph.nodes.check_rules import check_rules
from graph.nodes.find_documents import FindResult, FoundDocument, find_documents, plan_recapture
from graph.nodes.plan_fixes import run_planner
from graph.nodes.read_documents import StreamingReader
from graph.nodes.speak import speak
from graph.runtime import runtime
from graph.state import STAGES, KaagazState
from rules.engine import SchemeResult
from schemas.documents import DocumentExtraction
from schemas.household import Household

logger = logging.getLogger(__name__)


def _real_find(video: Path, on_document: Callable[[FoundDocument], None]) -> FindResult:
    from clients.segmenter import Sam31ApiSegmenter

    return find_documents(video, segmenter=Sam31ApiSegmenter(), on_document=on_document)


def _real_tts() -> Callable[[str, str], Any] | None:
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError:
        logger.warning("TTS extra not installed: plans are shown without audio")
        return None
    from clients.tts import synthesize

    return synthesize


@dataclass
class Deps:
    find: Callable[[Path, Callable[[FoundDocument], None]], FindResult] = _real_find
    new_reader: Callable[[], Any] = field(default=lambda: StreamingReader(agreement=True))
    verifier: Callable[[dict[str, list[bytes]]], Any] = llm_name_verifier
    adjudicator: Callable[[date], Any] = llm_adjudicator
    llm: Callable[..., Any] = chat
    tts: Callable[[str, str], Any] | None = None


def default_deps() -> Deps:
    return Deps(tts=_real_tts())


def _timed(name: str, fn: Callable[[KaagazState], dict[str, Any]]) -> Callable[[KaagazState], dict[str, Any]]:
    def node(state: KaagazState) -> dict[str, Any]:
        start = time.perf_counter()
        out = fn(state)
        return {**out, "timings": {name: round(time.perf_counter() - start, 2)}}

    node.__name__ = name
    return node


def build_graph(deps: Deps | None = None, checkpointer: Any = None) -> Any:
    deps = deps or default_deps()

    def find(state: KaagazState) -> dict[str, Any]:
        rt = runtime(state["session_id"])
        rt.reader = deps.new_reader()

        def on_document(d: FoundDocument) -> None:
            rt.images[d.document.id] = list(d.document.images)
            rt.reader.submit(d.document)

        video = Path(state["video_path"])
        try:
            result = deps.find(video, on_document)
        finally:
            if state.get("delete_video"):
                video.unlink(missing_ok=True)  # never keep an uploaded video longer than the run
        rt.find_result = result
        found = [{"id": d.document.id, "frames": d.source_frames, "fully_visible": d.fully_visible}
                 for d in result.documents]
        return {"found": found, "video_path": None if state.get("delete_video") else state["video_path"],
                "log": [f"found {len(found)} documents"]}

    def read(state: KaagazState) -> dict[str, Any]:
        rt = runtime(state["session_id"])
        with rt.reader as reader:
            reads = reader.results()
        extractions = {k: r.extraction for k, r in reads.items()}
        recapture = plan_recapture(rt.find_result, extractions) if rt.find_result else None
        tokens = sum(r.usage.prompt_tokens + r.usage.completion_tokens for r in reads.values())
        return {"extractions": [e.model_dump(mode="json") for e in extractions.values()],
                "recapture": recapture.model_dump(mode="json") if recapture else {"mode": "none"},
                "usage": {"read_tokens": tokens}, "log": [f"read {len(extractions)} documents"]}

    def household(state: KaagazState) -> dict[str, Any]:
        rt = runtime(state["session_id"])
        ref = date.fromisoformat(state["reference_date"])
        extractions = [DocumentExtraction.model_validate(e) for e in state.get("extractions", [])]
        hh = build_household(extractions, ref, adjudicate=deps.adjudicator(ref),
                             verify=deps.verifier(rt.images) if rt.images else None)
        return {"household": hh.model_dump(mode="json"),
                "usage": {"household_tokens": hh.usage.prompt_tokens + hh.usage.completion_tokens},
                "log": [f"household: {len(hh.members)} members, {len(hh.issues)} issues"]}

    def rules(state: KaagazState) -> dict[str, Any]:
        results = check_rules(Household.model_validate(state["household"]))
        return {"results": [r.model_dump(mode="json") for r in results]}

    def plan(state: KaagazState) -> dict[str, Any]:
        from agents.fix_planner import planner_issues

        hh = Household.model_validate(state["household"])
        results = [SchemeResult.model_validate(r) for r in state.get("results", [])]
        fix_plan = run_planner(hh, results, state["language"], deps.llm)
        return {"plan": fix_plan.model_dump(mode="json", exclude={"trace"}),
                "issues": [i.model_dump(mode="json") for i in planner_issues(hh, results)],
                "usage": {"plan_tokens": fix_plan.usage.prompt_tokens + fix_plan.usage.completion_tokens},
                "log": [f"plan: {len(fix_plan.steps)} steps ({fix_plan.source})"]}

    def voice(state: KaagazState) -> dict[str, Any]:
        from schemas.fixes import FixPlan

        return {"speech": speak(FixPlan.model_validate(state["plan"]), state["language"], deps.tts)}

    g = StateGraph(KaagazState)
    for name, fn in zip(STAGES, (find, read, household, rules, plan, voice)):
        g.add_node(name, _timed(name, fn))
    g.add_edge(START, STAGES[0])
    for a, b in zip(STAGES, STAGES[1:]):
        g.add_edge(a, b)
    g.add_edge(STAGES[-1], END)
    return g.compile(checkpointer=checkpointer or InMemorySaver())
