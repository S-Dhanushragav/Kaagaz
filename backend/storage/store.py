"""Case-file storage behind one interface: `MemoryStore` (tests, and local runs without DATABASE_URL) and
`PostgresStore` (Neon, storage/postgres.py). Every method that touches a check takes the user id, so one user
can never read or change another's checks."""

import threading
import uuid
from datetime import date, datetime, timezone
from typing import Protocol

from storage.models import CheckData, CheckRecord, FeedbackEntry, User


def now() -> datetime:
    return datetime.now(timezone.utc)


class Store(Protocol):
    def init(self) -> None: ...

    # users
    def user_by_phone_hash(self, phone_hash: str) -> User | None: ...
    def create_user(self, phone_hash: str, phone_last4: str, language: str) -> User: ...
    def get_user(self, user_id: str) -> User | None: ...
    def set_language(self, user_id: str, language: str) -> User | None: ...
    def delete_user(self, user_id: str) -> bool: ...  # and everything that belongs to them

    # checks
    def save_check(self, user_id: str, session_id: str, language: str, data: CheckData,
                   previous_id: str | None = None) -> CheckRecord: ...  # insert, or update by session id
    def list_checks(self, user_id: str) -> list[CheckRecord]: ...  # newest first
    def get_check(self, user_id: str, check_id: str) -> CheckRecord | None: ...
    def delete_check(self, user_id: str, check_id: str) -> bool: ...
    def set_step(self, user_id: str, check_id: str, step: int, done: bool) -> bool: ...

    # feedback and retention
    def add_feedback(self, entry: FeedbackEntry) -> None: ...
    def purge_checks(self, older_than: datetime) -> int: ...


class MemoryStore:
    """Everything in dicts; for tests and for local runs without a database (nothing survives a restart)."""

    def __init__(self) -> None:
        self.users: dict[str, User] = {}
        self.checks: dict[str, CheckRecord] = {}
        self.feedback: list[FeedbackEntry] = []
        self._lock = threading.Lock()

    def init(self) -> None:
        pass

    def user_by_phone_hash(self, phone_hash: str) -> User | None:
        with self._lock:
            return next((u for u in self.users.values() if u.phone_hash == phone_hash), None)

    def create_user(self, phone_hash: str, phone_last4: str, language: str) -> User:
        with self._lock:
            existing = next((u for u in self.users.values() if u.phone_hash == phone_hash), None)
            if existing is not None:  # the same number twice: one user (like the unique index in Postgres)
                return existing
            user = User(id=str(uuid.uuid4()), phone_hash=phone_hash, phone_last4=phone_last4, language=language,
                        created=date.today())
            self.users[user.id] = user
            return user

    def get_user(self, user_id: str) -> User | None:
        return self.users.get(user_id)

    def set_language(self, user_id: str, language: str) -> User | None:
        with self._lock:
            user = self.users.get(user_id)
            if user is None:
                return None
            self.users[user_id] = user.model_copy(update={"language": language})
            return self.users[user_id]

    def delete_user(self, user_id: str) -> bool:
        with self._lock:
            if self.users.pop(user_id, None) is None:
                return False
            self.checks = {k: c for k, c in self.checks.items() if c.user_id != user_id}
            return True

    def save_check(self, user_id: str, session_id: str, language: str, data: CheckData,
                   previous_id: str | None = None) -> CheckRecord:
        with self._lock:
            existing = next((c for c in self.checks.values() if c.session_id == session_id), None)
            if existing is not None:
                if existing.user_id != user_id:
                    raise PermissionError("session belongs to another user")
                # A re-plan can renumber steps: ticks are kept only while the steps are the same.
                same = [s.voice for s in existing.data.steps] == [s.voice for s in data.steps]
                record = existing.model_copy(update={"data": data, "updated": now(), "language": language,
                                                     "steps_done": existing.steps_done if same else {}})
            else:
                stamp = now()
                record = CheckRecord(id=str(uuid.uuid4()), user_id=user_id, session_id=session_id,
                                     previous_id=previous_id, language=language, created=stamp, updated=stamp,
                                     data=data)
            self.checks[record.id] = record
            return record

    def list_checks(self, user_id: str) -> list[CheckRecord]:
        with self._lock:
            mine = [c for c in self.checks.values() if c.user_id == user_id]
        return sorted(mine, key=lambda c: c.created, reverse=True)

    def get_check(self, user_id: str, check_id: str) -> CheckRecord | None:
        c = self.checks.get(check_id)
        return c if c is not None and c.user_id == user_id else None

    def delete_check(self, user_id: str, check_id: str) -> bool:
        with self._lock:
            c = self.checks.get(check_id)
            if c is None or c.user_id != user_id:
                return False
            del self.checks[check_id]
            for k, other in self.checks.items():
                if other.previous_id == check_id:
                    self.checks[k] = other.model_copy(update={"previous_id": None})
            return True

    def set_step(self, user_id: str, check_id: str, step: int, done: bool) -> bool:
        with self._lock:
            c = self.checks.get(check_id)
            if c is None or c.user_id != user_id or not any(s.index == step for s in c.data.steps):
                return False
            self.checks[check_id] = c.model_copy(update={"steps_done": {**c.steps_done, step: done}})
            return True

    def add_feedback(self, entry: FeedbackEntry) -> None:
        with self._lock:
            self.feedback.append(entry)

    def purge_checks(self, older_than: datetime) -> int:
        with self._lock:
            old = [k for k, c in self.checks.items() if c.created < older_than]
            for k in old:
                del self.checks[k]
            return len(old)
