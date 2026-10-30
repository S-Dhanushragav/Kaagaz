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


def test_a_guest_check_is_saved_when_the_family_logs_in_afterwards(setup) -> None:
    manager, store, auth = setup
    guest = manager.start_sample("en")
    _finish(manager, guest.id)
    assert store.checks == {}  # nothing stored for a guest
    _, user_id = _login(auth)
    check_id = manager.claim(guest.id, user_id, guest.guest_secret)
    (record,) = store.list_checks(user_id)
    assert record.id == check_id and record.session_id == guest.id
    assert manager.claim(guest.id, user_id, guest.guest_secret) == check_id  # claiming twice changes nothing
    with pytest.raises(SessionError) as e:
        manager.claim(guest.id, "someone-else", guest.guest_secret)
    assert e.value.status == 409
    with pytest.raises(SessionError) as e:
        manager.claim("gone", user_id, guest.guest_secret)
    assert e.value.status == 404


def test_knowing_another_sessions_id_is_not_enough_to_claim_it(setup) -> None:
    """Session ids appear in API paths (and so in access logs); only the starting browser has the guest secret."""
    manager, store, auth = setup
    theirs = manager.start_sample("en")
    _finish(manager, theirs.id)
    _, intruder = _login(auth)
    for wrong in ("", "guess", manager.start_sample("en").guest_secret):  # even a real secret of another session
        with pytest.raises(SessionError) as e:
            manager.claim(theirs.id, intruder, wrong)
        assert e.value.status == 403
    assert store.list_checks(intruder) == [] and manager.get(theirs.id).user_id is None  # still unclaimed


def test_claim_route_needs_a_login(setup, monkeypatch) -> None:
    from app.main import app

    manager, store, auth = setup
    for name, value in (("store", store), ("auth", auth), ("sessions", manager)):
        monkeypatch.setattr(app.state, name, value, raising=False)
    client = TestClient(app)
    started = client.post("/sessions/sample", json={"language": "mr"}).json()
    guest, secret = started["id"], started["guest_secret"]
    _finish(manager, guest)
    assert client.post(f"/sessions/{guest}/claim", json={"guest_secret": secret}).status_code == 401
    token, user_id = _login(auth)
    h = {"Authorization": f"Bearer {token}"}
    assert client.post(f"/sessions/{guest}/claim", json={"guest_secret": "wrong"}, headers=h).status_code == 403
    saved = client.post(f"/sessions/{guest}/claim", json={"guest_secret": secret}, headers=h).json()
    assert saved["check_id"] == store.list_checks(user_id)[0].id


def test_could_not_read_names_whose_document_it_is() -> None:
    view = {
        "household": {
            "members": [{"member_id": "r2", "name_en": "Savita Aditya Bhosale", "name_mr": "सविता आदित्य भोसले",
                         "on_ration_card": True, "documents": {"identity_card": ["d2"]}}],
            "documents": {"d2": {"doc_type": "identity_card"}, "d5": {"doc_type": "identity_card"},
                          "d9": {"doc_type": "caste_certificate"}},
            "issues": [{"type": "unreadable", "severity": "blocker", "documents": ["d2", "d5", "d9"]}]},
        "extractions": [{"document_id": "d5", "fields": {"name_en": "Aditya Yogesh Bhosale", "name_mr": None}},
                        {"document_id": "d9", "fields": None}],
    }
    unread = [p for p in check_data(view).problems if p.type == "unreadable"]
    assert [(p.member_id, p.member_name, p.document_types) for p in unread] == [
        ("r2", "Savita Aditya Bhosale", ["identity_card"]),  # linked to the member
        (None, "Aditya Yogesh Bhosale", ["identity_card"]),  # the name read on it
        (None, None, ["caste_certificate"]),  # nobody known: the document only
    ]
