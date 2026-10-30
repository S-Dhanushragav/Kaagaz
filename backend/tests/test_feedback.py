"""Feedback (POST /feedback): stored anonymously in the case-file store; bad input is rejected before anything is
stored."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.feedback import Feedback, record
from app.main import app
from storage.store import MemoryStore


def test_entries_are_stored_with_nothing_identifying() -> None:
    store = MemoryStore()
    record(Feedback(session_id="0123456789ab", target="plan", value="up"), store)
    record(Feedback(session_id="0123456789ab", target="answer:q1", value="down", comment="  wrong office  "), store)
    assert [x.value for x in store.feedback] == ["up", "down"]
    assert store.feedback[0].comment is None and store.feedback[1].comment == "wrong office"
    assert set(store.feedback[1].model_dump()) == {"session_id", "target", "value", "comment"}  # nothing else


@pytest.mark.parametrize("bad", [
    {"session_id": "../etc", "target": "plan", "value": "up"},
    {"session_id": "0123456789ab", "target": "everything", "value": "up"},
    {"session_id": "0123456789ab", "target": "plan", "value": "meh"},
    {"session_id": "0123456789ab", "target": "plan", "value": "up", "comment": "x" * 501},
])
def test_bad_feedback_is_rejected(bad: dict) -> None:
    with pytest.raises(ValidationError):
        Feedback.model_validate(bad)


def test_route_stores_feedback(monkeypatch) -> None:
    store = MemoryStore()
    monkeypatch.setattr(app.state, "store", store, raising=False)
    client = TestClient(app)  # no lifespan: no sessions needed
    ok = client.post("/feedback", json={"session_id": "0123456789ab", "target": "plan", "value": "down"})
    assert ok.status_code == 204
    assert client.post("/feedback", json={"session_id": "x", "target": "plan", "value": "up"}).status_code == 422
    assert len(store.feedback) == 1
