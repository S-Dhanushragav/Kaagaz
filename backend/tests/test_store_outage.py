"""The case-file database is down (refuses connections or times out): a guest check still runs end to end
(question, plan, plan audio text, close-up), a logged-in family continues as a guest, and only login, saving and the
case file fail, with a friendly 503. The Postgres store fails fast instead of waiting on every call."""

import time

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.auth import AuthService
from storage.models import FeedbackEntry
from storage.postgres import PostgresStore
from storage.store import MemoryStore, StoreUnavailable
from tests.test_closeup import PHOTO, _wait, manager  # noqa: F401 - the close-up fixture (a guest family)


class DownStore:
    """Every call fails the way PostgresStore does when the database cannot be reached."""

    def __getattr__(self, name: str):
        def fail(*args, **kwargs):
            raise StoreUnavailable("down")
        return fail


def test_a_guest_check_finishes_normally_while_the_database_is_down(manager) -> None:  # noqa: F811
    manager.store = DownStore()
    s = manager.start_sample("en")
    view = _wait(manager, s.id)
    assert view["status"] == "done" and view["plan"]["steps"] and view["check_id"] is None
    assert manager.speech_text(s.id, "step-0")  # Listen
    assert manager.closeup(s.id, "id1", PHOTO) == {"clear": True, "missing": []}  # close-up and re-plan
    after = _wait(manager, s.id)
    assert after["status"] == "done" and after["recapture"]["mode"] == "none"


def test_saving_a_check_fails_politely_and_the_run_does_not(manager) -> None:  # noqa: F811
    s = manager.start_sample("en")
    _wait(manager, s.id)
    manager.store = DownStore()
    with pytest.raises(StoreUnavailable):
        manager.claim(s.id, "someone", s.guest_secret)  # the route turns this into a friendly 503
    assert manager.view(s.id)["status"] == "done"


def _client(monkeypatch, store):
    from app.main import app

    auth = AuthService(store, "phone-key", "token-key")
    monkeypatch.setattr(app.state, "store", store, raising=False)
    monkeypatch.setattr(app.state, "auth", auth, raising=False)
    return TestClient(app), auth


def test_routes_while_the_database_is_down(monkeypatch, manager) -> None:  # noqa: F811
    from app.main import app

    up = MemoryStore()
    client, auth = _client(monkeypatch, up)
    monkeypatch.setattr(app.state, "sessions", manager, raising=False)
    code = client.post("/auth/start", json={"phone": "9876543210"}).json()["demo_code"]  # no database needed
    token = auth.issue(up.create_user("h", "0000", "en").id)

    monkeypatch.setattr(auth, "store", DownStore())
    monkeypatch.setattr(app.state, "store", DownStore())
    login = client.post("/auth/verify", json={"phone": "9876543210", "code": code})
    assert login.status_code == 503 and "not available right now" in login.json()["detail"]
    h = {"Authorization": f"Bearer {token}"}
    assert client.get("/me", headers=h).status_code == 503  # the app shows the guest welcome instead
    started = client.post("/sessions/sample", json={"language": "en"}, headers=h)
    assert started.status_code == 200  # a logged-in family continues as a guest
    sid = started.json()["id"]
    _wait(manager, sid)
    assert manager.get(sid).user_id is None
    claim = client.post(f"/sessions/{sid}/claim", json={"guest_secret": started.json()["guest_secret"]}, headers=h)
    assert claim.status_code == 503
    assert client.post("/feedback", json={"session_id": sid, "target": "plan", "value": "up"}).status_code == 503

    monkeypatch.setattr(auth, "store", up)  # the database is back: the same code still works
    assert client.post("/auth/verify", json={"phone": "9876543210", "code": code}).status_code == 200


def test_postgres_store_refused_fails_fast_and_recovers(monkeypatch) -> None:
    now = [100.0]
    store = PostgresStore("postgresql://kaagaz:x@127.0.0.1:1/none", clock=lambda: now[0])  # nothing listens on port 1
    store.init()  # start-up does not fail
    calls = []
    real_connect = store._connect
    monkeypatch.setattr(store, "_connect", lambda: calls.append(1) or real_connect())
    with pytest.raises(StoreUnavailable):
        store.get_user("00000000-0000-0000-0000-000000000000")
    tried = len(calls)
    start = time.perf_counter()
    with pytest.raises(StoreUnavailable):
        store.list_checks("00000000-0000-0000-0000-000000000000")
    assert len(calls) == tried and time.perf_counter() - start < 0.05  # failed at once, no new connection
    now[0] += 31
    with pytest.raises(StoreUnavailable):
        store.get_user("00000000-0000-0000-0000-000000000000")
    assert len(calls) > tried  # tried again after the pause


def test_postgres_store_timeout_becomes_unavailable(monkeypatch) -> None:
    store = PostgresStore("postgresql://kaagaz:x@db.invalid/none")

    def timeout():
        raise psycopg.OperationalError("connection timeout expired")
    monkeypatch.setattr(store, "_connect", timeout)
    with pytest.raises(StoreUnavailable):
        store.add_feedback(FeedbackEntry(session_id="0123456789ab", target="plan", value="up", comment=None))
