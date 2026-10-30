"""Case-file store contract, run on MemoryStore (always) and on Postgres only when asked for:
`KAAGAZ_LIVE_DB=1 pytest -m live_db` (DATABASE_URL_TEST if set, else DATABASE_URL; a throwaway user, deleted). Users, checks (save, re-save by session, list, get, delete),
step ticks, ownership, delete-everything, retention purge, feedback."""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.config import get_settings
from storage.models import CheckData, FeedbackEntry, StoredFact, StoredMember, StoredStep
from storage.store import MemoryStore


def _data(voices: tuple[str, ...] = ("Go to the Tahsil office.", "Ask at the office.")) -> CheckData:
    return CheckData(
        members=[StoredMember(member_id="r1", name_mr="सविता", name_en="Savita", relation_en="Wife", age=46,
                              on_ration_card=True)],
        documents=["ration_card", "identity_card"], problems=[], outcomes=[],
        steps=[StoredStep(index=i, kind="fix", visit=1, office=StoredFact(text="Tahsil office", verified=True), voice=v, speech=v, bring=[], fee=None,
                          time_limit=None, member_id="r1") for i, v in enumerate(voices)],
        answers=[])


def _postgres():
    if os.environ.get("KAAGAZ_LIVE_DB") != "1":
        pytest.skip("live database tests run only with KAAGAZ_LIVE_DB=1")
    s = get_settings()
    url = s.database_url_test.get_secret_value() or s.database_url.get_secret_value()
    if not url:
        pytest.skip("neither DATABASE_URL_TEST nor DATABASE_URL is set")
    from storage.postgres import PostgresStore

    store = PostgresStore(url)
    store.init()
    return store


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.live_db)])
def store(request):
    return MemoryStore() if request.param == "memory" else _postgres()


@pytest.fixture
def user(store):
    u = store.create_user(f"test-{uuid.uuid4().hex}", "3210", "mr")
    yield u
    store.delete_user(u.id)


def test_users_by_hash_language_and_delete(store, user) -> None:
    assert store.user_by_phone_hash(user.phone_hash).id == user.id
    assert store.create_user(user.phone_hash, "3210", "en").id == user.id  # the same number twice: one user
    assert store.set_language(user.id, "hi").language == "hi"
    assert store.get_user(user.id).language == "hi"
    assert store.get_user("not-a-uuid") is None and store.user_by_phone_hash("nope") is None


def test_checks_save_list_get_and_ticks(store, user) -> None:
    session = uuid.uuid4().hex[:12]
    first = store.save_check(user.id, session, "mr", _data())
    assert store.set_step(user.id, first.id, 1, True) and not store.set_step(user.id, first.id, 9, True)
    again = store.save_check(user.id, session, "mr", _data())  # same steps (e.g. saved twice): ticks kept
    assert again.id == first.id and again.steps_done == {1: True}
    replanned = store.save_check(user.id, session, "mr", _data(("A new first step.",)))  # a close-up re-plan
    assert replanned.id == first.id and replanned.steps_done == {}
    second = store.save_check(user.id, uuid.uuid4().hex[:12], "mr", _data(), previous_id=first.id)
    assert [c.id for c in store.list_checks(user.id)] == [second.id, first.id]  # newest first
    assert store.get_check(user.id, second.id).previous_id == first.id
    assert store.delete_check(user.id, first.id)
    assert store.get_check(user.id, first.id) is None and store.get_check(user.id, second.id).previous_id is None


def test_one_user_cannot_touch_another_users_checks(store, user) -> None:
    other = store.create_user(f"test-{uuid.uuid4().hex}", "0000", "en")
    try:
        check = store.save_check(user.id, uuid.uuid4().hex[:12], "mr", _data())
        assert store.get_check(other.id, check.id) is None and store.list_checks(other.id) == []
        assert not store.set_step(other.id, check.id, 0, True) and not store.delete_check(other.id, check.id)
        with pytest.raises(PermissionError):
            store.save_check(other.id, check.session_id, "mr", _data())
    finally:
        store.delete_user(other.id)


def test_deleting_a_user_deletes_everything(store) -> None:
    u = store.create_user(f"test-{uuid.uuid4().hex}", "1111", "mr")
    check = store.save_check(u.id, uuid.uuid4().hex[:12], "mr", _data())
    store.set_step(u.id, check.id, 0, True)
    assert store.delete_user(u.id)
    assert store.get_user(u.id) is None and store.user_by_phone_hash(u.phone_hash) is None
    assert store.get_check(u.id, check.id) is None and store.list_checks(u.id) == []
    assert not store.delete_user(u.id)


def test_retention_purge_and_feedback(store, user) -> None:
    check = store.save_check(user.id, uuid.uuid4().hex[:12], "mr", _data())
    store.purge_checks(datetime.now(timezone.utc) - timedelta(days=365))
    assert store.get_check(user.id, check.id) is not None  # a new check survives the 365-day purge
    if isinstance(store, MemoryStore):  # never on the live database: it would purge every user's checks
        store.purge_checks(datetime.now(timezone.utc) + timedelta(seconds=5))  # everything older than "soon"
        assert store.get_check(user.id, check.id) is None
    marker = f"store test {uuid.uuid4().hex}"
    store.add_feedback(FeedbackEntry(session_id="0123456789ab", target="plan", value="up", comment=marker))
    if not isinstance(store, MemoryStore):  # the live database: leave no test row behind
        assert store._exec("DELETE FROM feedback WHERE comment = %s", (marker,)) == 1
