"""The pipeline graph end to end with fakes: streaming find -> read, household, rules, plan with an interrupt
for the family's answer, resume, speech, timings, recapture, and the uploaded video deleted after finding."""

from datetime import date

from langgraph.types import Command

from clients.llm import TokenUsage
from graph.build import Deps, build_graph
from graph.nodes.find_documents import FindResult, FoundDocument
from graph.nodes.read_documents import DocumentInput, ReadResult
from graph.runtime import drop, runtime
from graph.state import STAGES
from schemas.documents import DocumentExtraction
from tests.test_fix_planner import _call, _step, _turn
from tests.test_household import SUNEEL_ID, SUNIL, _card, _no_llm


class FakeReader:
    def __init__(self, extractions: dict[str, DocumentExtraction]) -> None:
        self.extractions, self.submitted = extractions, []

    def submit(self, doc: DocumentInput) -> None:
        self.submitted.append(doc.id)

    def results(self) -> dict[str, ReadResult]:
        return {i: ReadResult(extraction=self.extractions[i], usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
                              elapsed_s=0.1, attempts=1, cached=False) for i in self.submitted}

    def __enter__(self) -> "FakeReader":
        return self

    def __exit__(self, *exc) -> None:
        pass


def _found(doc_id: str) -> FoundDocument:
    return FoundDocument(document=DocumentInput(id=doc_id, images=[b"jpg1", b"jpg2"]), track_id=doc_id,
                         source_frames=[3, 9], quads=[], methods=["mask"], sharpness=[1.0], fully_visible=True)


def _deps(tts_calls: list) -> Deps:
    extractions = {"rc": _card(SUNIL), "id1": SUNEEL_ID}

    def find(video, on_document):
        docs = [_found("rc"), _found("id1")]
        for d in docs:
            on_document(d)  # streamed to the reader as they are found
        return FindResult(documents=docs, tracks_raw=2, dropped={}, segmenter_frames=10, billed_frames=10,
                          masks_decoded=2, timings={})

    turns = [_turn(_call("ask_family", issue_id="i1", kind="which_is_correct")),
             _turn(_call("submit_plan", steps=[_step("aadhaar_name_correction", ["i1"]),
                                               _step("income_certificate_new", ["i2"], member_id=None)]))]

    def llm(messages, **kwargs):  # deterministic per conversation, like the disk cache: replays are identical
        return turns[sum(1 for m in messages if m["role"] == "assistant")]

    return Deps(find=find, new_reader=lambda: FakeReader(extractions), verifier=lambda images: None,
                adjudicator=lambda ref: _no_llm, llm=llm, tts=lambda text, lang: tts_calls.append((lang, text)))


def test_graph_pauses_for_the_family_and_resumes_to_a_spoken_plan(tmp_path) -> None:
    video = tmp_path / "upload.mp4"
    video.write_bytes(b"video")
    tts_calls: list = []
    graph = build_graph(_deps(tts_calls))
    config = {"configurable": {"thread_id": "s1"}}
    state = {"session_id": "s1", "language": "hi", "video_path": str(video), "delete_video": True,
             "reference_date": date(2026, 10, 27).isoformat()}

    paused = graph.invoke(state, config)
    assert not video.exists()  # the upload is gone as soon as the finder is done
    (question,) = paused["__interrupt__"]
    q = question.value
    assert q["question_id"] == "i1:which_is_correct" and q["options"][-1] == "not sure"
    assert "नंबर एक" in q["speech"] and len(q["shown"]) == 3 and q["values"]
    assert runtime("s1").images["rc"] == [b"jpg1", b"jpg2"]  # crops kept for the name verifier
    assert set(paused["timings"]) == set(STAGES[:4])  # plan_fixes is paused
    assert paused["recapture"]["mode"] in ("none", "close_ups", "sweep_again")

    answer = next(i for i, o in enumerate(q["options"]) if "Sunil Ramesh Patil" in o)
    done = graph.invoke(Command(resume=answer), config)
    assert "__interrupt__" not in done
    steps = done["plan"]["steps"]
    assert [s["kind"] for s in steps] == ["question", "fix", "fix"] and steps[0]["answer"] == q["options"][answer]
    assert set(done["timings"]) == set(STAGES)
    assert [s["index"] for s in done["speech"]] == [0, 1, 2]
    assert not any(c.isdigit() for s in done["speech"] for c in s["speech"])  # TTS text has numbers spelled out
    assert tts_calls and tts_calls[0] == ("hi", done["speech"][0]["speech"])  # first sentence synthesized first
    assert done["usage"]["read_tokens"] == 30 and done["issues"]
    drop("s1")


def test_sample_video_is_not_deleted(tmp_path) -> None:
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"video")
    graph = build_graph(_deps([]))
    graph.invoke({"session_id": "s2", "language": "en", "video_path": str(video), "delete_video": False,
                  "reference_date": "2026-10-27"}, {"configurable": {"thread_id": "s2"}})
    assert video.exists()
    drop("s2")


def test_sweep_again_stops_after_reading(tmp_path) -> None:
    """Most documents unreadable: ask for a new sweep; no household, rules, questions or plan."""
    video = tmp_path / "upload.mp4"
    video.write_bytes(b"video")
    deps = _deps([])
    blurry = {"rc": _card(SUNIL).model_copy(update={"needs_retake": True, "retake_reasons": ["blurry"]}),
              "id1": SUNEEL_ID.model_copy(update={"needs_retake": True, "retake_reasons": ["blurry"]})}
    deps.new_reader = lambda: FakeReader(blurry)
    out = build_graph(deps).invoke({"session_id": "s3", "language": "mr", "video_path": str(video), "delete_video": True,
                                    "reference_date": "2026-10-27"}, {"configurable": {"thread_id": "s3"}})
    assert out["recapture"]["mode"] == "sweep_again" and "__interrupt__" not in out
    assert "household" not in out and "plan" not in out and set(out["timings"]) == {"find_documents", "read_documents"}
    drop("s3")
