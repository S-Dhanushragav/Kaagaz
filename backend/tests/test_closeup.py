"""Close-up loop on the fake graph: a clear photo replaces the reading and re-runs household -> plan; an unclear
photo changes nothing; only documents on the close-up list; sample close-ups only for the sample family."""

import time

import cv2
import numpy as np
import pytest

from app.config import get_settings
from app.sessions import SessionError, SessionManager
from clients.llm import TokenUsage
from graph.build import build_graph
from graph.nodes.read_documents import ReadResult
from schemas.documents import DocumentExtraction
from tests.test_fix_planner import _call, _step, _turn
from tests.test_graph import FakeReader, _deps
from tests.test_household import SUNEEL_ID, SUNIL, _card, _id

PHOTO = cv2.imencode(".jpg", np.full((400, 600, 3), 200, np.uint8))[1].tobytes()
SUNIL_ID = _id("id1", "सुनील रमेश पाटील", "Sunil Ramesh Patil", "01/01/1986")  # the clear read: no mismatch


def _read(extraction: DocumentExtraction):
    return lambda doc: ReadResult(extraction=extraction.model_copy(update={"document_id": doc.id}),
                                  usage=TokenUsage(prompt_tokens=7, completion_tokens=3), elapsed_s=0.1, attempts=1,
                                  cached=False)


@pytest.fixture
def manager(monkeypatch, tmp_path) -> SessionManager:
    sample = tmp_path / "sample.mp4"
    sample.write_bytes(b"video")
    s = get_settings()
    monkeypatch.setattr(s, "sample_video", str(sample))
    monkeypatch.setattr(s, "sessions_dir", tmp_path / "sessions")
    deps = _deps([])
    blurry_id = SUNEEL_ID.model_copy(update={"needs_retake": True, "retake_reasons": ["dob missing"]})
    deps.new_reader = lambda: FakeReader({"rc": _card(SUNIL), "id1": blurry_id})
    # After the close-up only the missing income certificate is left (issue i1).
    deps.llm = lambda messages, **kw: _turn(_call("submit_plan", steps=[_step("income_certificate_new", ["i1"], member_id=None)]))
    m = SessionManager(graph=build_graph(deps))
    m.reader = _read(SUNIL_ID)
    return m


def _wait(manager: SessionManager, session_id: str) -> dict:
    end = time.time() + 15
    while time.time() < end:
        v = manager.view(session_id)
        if v["status"] != "running":
            return v
        time.sleep(0.05)
    raise AssertionError("did not settle")


def test_clear_close_up_replaces_the_reading_and_replans(manager) -> None:
    s = manager.start_sample("en")
    before = _wait(manager, s.id)
    assert before["recapture"]["mode"] == "close_ups" and before["recapture"]["documents"] == ["id1"]
    assert before["status"] == "done" and [w["type"] for w in before["waiting"]] == ["name_mismatch"]
    result = manager.closeup(s.id, "id1", PHOTO)
    assert result == {"clear": True, "missing": []}
    after = _wait(manager, s.id)
    assert after["status"] == "done" and after["recapture"]["mode"] == "none" and not after["waiting"]
    assert "name_mismatch" not in [i["type"] for i in after["household"]["issues"]]
    assert [x["procedure_id"] for x in after["plan"]["steps"]] == ["income_certificate_new"]
    assert next(e for e in after["extractions"] if e["document_id"] == "id1")["fields"]["name_en"] == "Sunil Ramesh Patil"
    assert after["usage"]["read_tokens"] == 30 + 10


def test_unclear_close_up_changes_nothing(manager) -> None:
    s = manager.start_sample("en")
    before = _wait(manager, s.id)
    manager.reader = _read(SUNIL_ID.model_copy(update={"fields": SUNIL_ID.fields.model_copy(update={"dob": None})}))
    assert manager.closeup(s.id, "id1", PHOTO) == {"clear": False, "missing": ["dob"]}
    after = manager.view(s.id)
    assert after["status"] == "done" and after["recapture"] == before["recapture"] and after["plan"] == before["plan"]


def test_close_ups_only_for_listed_documents_and_real_photos(manager) -> None:
    s = manager.start_sample("en")
    _wait(manager, s.id)
    for doc, photo in (("rc", PHOTO), ("id1", b"not an image")):
        with pytest.raises(SessionError) as e:
            manager.closeup(s.id, doc, photo)
        assert e.value.status == 422
    assert manager.view(s.id)["status"] == "done"


def test_sample_close_ups_are_bundled_for_the_sample_only(manager, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "sample_video", "synthetic/videos/HH009/sweep.mp4")
    s = manager.start_sample("en")
    _wait(manager, s.id)
    assert manager.sample_closeup(s.id, "doc02")[:2] == b"\xff\xd8"  # the bundled JPEG
    with pytest.raises(SessionError):
        manager.sample_closeup(s.id, "doc99")
    manager.sessions[s.id].sample = False
    with pytest.raises(SessionError) as e:
        manager.sample_closeup(s.id, "doc02")
    assert e.value.status == 409


def test_answers_are_kept_when_a_close_up_re_runs_the_plan(monkeypatch, tmp_path) -> None:
    """The name question is answered once; a close-up of another member's document re-plans without asking again."""
    import json as _json

    from tests.test_household import _row

    sample = tmp_path / "sample.mp4"
    sample.write_bytes(b"video")
    s = get_settings()
    monkeypatch.setattr(s, "sample_video", str(sample))
    monkeypatch.setattr(s, "sessions_dir", tmp_path / "sessions")
    deps = _deps([])
    rekha = _id("id2", "रेखा सुनील पाटील", "Rekha Sunil Patil", "01/01/1990", "F", "5555")
    blurry_rekha = rekha.model_copy(update={"needs_retake": True, "retake_reasons": ["dob missing"]})
    card = _card(SUNIL, _row("रेखा सुनील पाटील", "Rekha Sunil Patil", "F", 36, "Wife"))
    deps.new_reader = lambda: FakeReader({"rc": card, "id1": SUNEEL_ID, "id2": blurry_rekha})
    deps.find = _found_three(deps.find)

    def llm(messages, **kw):
        issues = _json.loads(messages[1]["content"].split("Issues:\n", 1)[1])
        asked = sum(1 for m in messages if m["role"] == "assistant")
        mismatch = next(i["id"] for i in issues if i["type"] == "name_mismatch")
        if asked == 0:
            return _turn(_call("ask_family", issue_id=mismatch, kind="which_is_correct"))
        steps = [_step("aadhaar_name_correction", [mismatch])]
        steps += [_step("income_certificate_new", [i["id"]], member_id=None) for i in issues if i["type"] in ("missing_document", "expired")]
        return _turn(_call("submit_plan", steps=steps))

    deps.llm = llm
    m = SessionManager(graph=build_graph(deps))
    m.reader = _read(rekha)
    session = m.start_sample("en")
    view = _wait(m, session.id)
    assert view["question"], (view["status"], view["error"], view["recapture"], view["issues"])
    q = view["question"]
    m.answer_option(session.id, q["question_id"], next(i for i, o in enumerate(q["options"]) if "Sunil Ramesh Patil" in o))
    first = _wait(m, session.id)
    assert first["status"] == "done" and first["recapture"]["documents"] == ["id2"]
    assert m.closeup(session.id, "id2", PHOTO)["clear"]
    again = _wait(m, session.id)
    assert again["status"] == "done" and again["question"] is None  # not asked again
    assert [s["answer"] for s in again["plan"]["steps"] if s["kind"] == "question"] == [q["options"][
        next(i for i, o in enumerate(q["options"]) if "Sunil Ramesh Patil" in o)]]


def _found_three(find):
    from tests.test_graph import _found

    def wrapped(video, on_document):
        result = find(video, on_document)
        extra = _found("id2")
        on_document(extra)
        return result.model_copy(update={"documents": [*result.documents, extra]})

    return wrapped
