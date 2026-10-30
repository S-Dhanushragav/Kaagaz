"""Case file: a logged-in session's finished check is saved (allow-listed fields only: no images, no ID numbers,
no dates of birth, no phone), guests are never stored, re-checks link only to the user's own checks, steps can be
ticked, and "Delete my data" removes everything, through the HTTP API."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from app.auth import AuthService
from app.casefile import check_data, summary
from app.config import get_settings
from app.sessions import SessionError, SessionManager
from graph.build import build_graph
from storage.store import MemoryStore
from tests.test_graph import _deps

PHONE = "9876543210"


@pytest.fixture
def setup(monkeypatch, tmp_path):
    sample = tmp_path / "sample.mp4"
    sample.write_bytes(b"video")
    s = get_settings()
    monkeypatch.setattr(s, "sample_video", str(sample))
    monkeypatch.setattr(s, "sessions_dir", tmp_path / "sessions")
    store = MemoryStore()
    manager = SessionManager(graph=build_graph(_deps([])), store=store)
    auth = AuthService(store, "phone-key", "token-key")
    return manager, store, auth


def _finish(manager: SessionManager, session_id: str) -> dict:
    """Run to the end: answer the family question as the fake planner expects (the Sunil Ramesh Patil spelling)."""
    end = time.time() + 15
    while time.time() < end:
        view = manager.view(session_id)
        if view["status"] == "waiting":
            q = view["question"]
            manager.answer_option(session_id, q["question_id"],
                                  next(i for i, o in enumerate(q["options"]) if "Sunil Ramesh Patil" in o))
        elif view["status"] != "running":
            return view
        time.sleep(0.05)
    raise AssertionError("session did not finish")


def _login(auth: AuthService) -> tuple[str, str]:
    token, user = auth.verify(PHONE, auth.start(PHONE, "ip")["demo_code"])
    return token, user.id


def test_a_logged_in_check_is_saved_with_nothing_private(setup) -> None:
    manager, store, auth = setup
    _, user_id = _login(auth)
    view = _finish(manager, manager.start_sample("en", user_id=user_id).id)
    (record,) = store.list_checks(user_id)
    assert view["check_id"] == record.id and record.session_id == view["id"]
    data = record.data
    assert data.members and data.outcomes and data.steps and data.answers
    assert data.documents == ["identity_card", "ration_card"]  # types only
    stored = json.dumps(record.model_dump(mode="json"), ensure_ascii=False)
    for private in ("1234", "XXXX", "1986", PHONE, "jpg", "image", "crop", "video", "evidence"):
        assert private not in stored, private  # ID number (even last 4), date of birth, phone, images
    assert summary(record)["open_steps"] == len(data.steps)


def test_guest_sessions_are_never_stored(setup) -> None:
    manager, store, _ = setup
    view = _finish(manager, manager.start_sample("en").id)
    assert view["status"] == "done" and view["check_id"] is None and store.checks == {}


def test_check_data_redacts_any_id_number_in_text() -> None:
    view = {"household": {"members": [{"member_id": "r1", "name_en": "Savita 1234 5678 9012", "on_ration_card": True}],
                          "documents": {}, "issues": []},
            "plan": {"steps": [{"kind": "fix", "voice": "Correct 1234 5678 9012 at the office.", "visit": 1}]},
            "speech": [{"speech": "Correct 1234 5678 9012.", "display": None}]}
    data = check_data(view)
    assert "5678" not in json.dumps(data.model_dump(mode="json"))


def test_case_file_api_ticks_rechecks_and_deletes_everything(setup, monkeypatch) -> None:
    from app.main import app

    manager, store, auth = setup
    for name, value in (("store", store), ("auth", auth), ("sessions", manager)):
        monkeypatch.setattr(app.state, name, value, raising=False)
    client = TestClient(app)
    token, user_id = _login(auth)
    h = {"Authorization": f"Bearer {token}"}

    first = client.post("/sessions/sample", json={"language": "mr"}, headers=h).json()["id"]
    _finish(manager, first)
    (row,) = client.get("/me/checks", headers=h).json()
    full = client.get(f"/me/checks/{row['id']}", headers=h).json()
    step = full["data"]["steps"][0]["index"]
    ticked = client.patch(f"/me/checks/{row['id']}/steps/{step}", json={"done": True}, headers=h).json()
    assert ticked["open_steps"] == row["open_steps"] - 1
    assert client.get(f"/me/checks/{row['id']}", headers=h).json()["steps_done"] == {str(step): True}
    assert client.patch(f"/me/checks/{row['id']}/steps/99", json={"done": True}, headers=h).status_code == 404

    # a guest cannot re-check, nor re-check someone else's check
    assert client.post("/sessions/sample", json={"recheck_of": row["id"]}).status_code == 404
    other, _ = auth.verify("9123456789", auth.start("9123456789", "ip2")["demo_code"])
    assert client.post("/sessions/sample", json={"recheck_of": row["id"]},
                       headers={"Authorization": f"Bearer {other}"}).status_code == 404
    assert client.get(f"/me/checks/{row['id']}", headers={"Authorization": f"Bearer {other}"}).status_code == 404

    second = client.post("/sessions/sample", json={"language": "mr", "recheck_of": row["id"]}, headers=h).json()["id"]
    _finish(manager, second)
    newest = client.get("/me/checks", headers=h).json()[0]
    assert newest["previous_id"] == row["id"]
    comparison = client.get(f"/me/checks/{newest['id']}", headers=h).json()["comparison"]
    assert comparison["fixed"] == [] and comparison["new"] == [] and comparison["still_open"]  # the same family
    assert client.get(f"/me/checks/{row['id']}", headers=h).json()["comparison"] is None
    assert client.patch("/me", json={"language": "hi"}, headers=h).json()["language"] == "hi"

    assert client.delete("/me", headers=h).status_code == 204
    assert store.get_user(user_id) is None and store.list_checks(user_id) == []
    assert client.get("/me", headers=h).status_code == 401  # the token no longer works
    with pytest.raises(SessionError):
        manager.answer_option(second, "x", 0)  # (the finished sessions themselves expire on their own)
