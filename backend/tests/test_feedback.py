"""Feedback (POST /feedback): one anonymous JSON line per entry; bad input is rejected before anything is stored."""

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import get_settings
from app.feedback import Feedback, record
from app.main import app


def test_entries_are_appended_as_json_lines(tmp_path) -> None:
    path = tmp_path / "var" / "feedback.jsonl"
    record(Feedback(session_id="0123456789ab", target="plan", value="up"), path)
    record(Feedback(session_id="0123456789ab", target="answer:q1", value="down", comment="  wrong office  "), path)
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert [x["value"] for x in lines] == ["up", "down"]
    assert lines[0]["comment"] is None and lines[1]["comment"] == "wrong office"
    assert set(lines[1]) == {"session_id", "target", "value", "comment", "date"}  # nothing else is kept


@pytest.mark.parametrize("bad", [
    {"session_id": "../etc", "target": "plan", "value": "up"},
    {"session_id": "0123456789ab", "target": "everything", "value": "up"},
    {"session_id": "0123456789ab", "target": "plan", "value": "meh"},
    {"session_id": "0123456789ab", "target": "plan", "value": "up", "comment": "x" * 501},
])
def test_bad_feedback_is_rejected(bad: dict) -> None:
    with pytest.raises(ValidationError):
        Feedback.model_validate(bad)


def test_route_stores_feedback(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "feedback_path", tmp_path / "fb.jsonl")
    client = TestClient(app)  # no lifespan: no sessions needed
    ok = client.post("/feedback", json={"session_id": "0123456789ab", "target": "plan", "value": "down"})
    assert ok.status_code == 204
    assert client.post("/feedback", json={"session_id": "x", "target": "plan", "value": "up"}).status_code == 422
    assert len((tmp_path / "fb.jsonl").read_text(encoding="utf-8").splitlines()) == 1
