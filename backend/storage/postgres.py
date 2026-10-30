"""The Store on Postgres (Neon, DATABASE_URL). One connection, reused behind a lock and reopened once if it was
dropped (Neon closes idle connections). `prepare_threshold=None`: Neon's pooled endpoint (PgBouncer, transaction
mode) does not keep server-side prepared statements.

When the database cannot be reached, every call raises StoreUnavailable quickly: a 5 s connect timeout, then for
RETRY_AFTER_S calls fail at once instead of waiting again (guests never wait on the database). The schema is
created on the first connection that works, so the app also starts while the database is down."""

import logging
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, TypeVar

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from storage.models import CheckData, CheckRecord, FeedbackEntry, User
from storage.store import StoreUnavailable

SCHEMA = (Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8")
T = TypeVar("T")
CONNECT_TIMEOUT_S = 5
RETRY_AFTER_S = 30.0
logger = logging.getLogger(__name__)


class PostgresStore:
    def __init__(self, url: str, clock: Callable[[], float] = time.monotonic) -> None:
        self.url = url
        self.clock = clock
        self._conn: psycopg.Connection | None = None
        self._lock = threading.Lock()
        self._schema_ready = False
        self._down_until = 0.0  # after a failure: fail fast until then

    # ---------- connection ----------

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.url, autocommit=True, row_factory=dict_row, prepare_threshold=None,
                               connect_timeout=CONNECT_TIMEOUT_S)

    def _run(self, fn: Callable[[psycopg.Connection], T]) -> T:
        with self._lock:
            if self.clock() < self._down_until:
                raise StoreUnavailable("the case-file database was unreachable a moment ago")
            for attempt in (1, 2):
                try:
                    if self._conn is None or self._conn.closed:
                        self._conn = self._connect()
                        if not self._schema_ready:
                            self._conn.execute(SCHEMA)
                            self._schema_ready = True
                    return fn(self._conn)
                except psycopg.OperationalError as e:  # refused, timed out, dropped
                    self._conn = None
                    if attempt == 2:
                        self._down_until = self.clock() + RETRY_AFTER_S
                        logger.warning("case-file database unreachable: %s", type(e).__name__)
                        raise StoreUnavailable("the case-file database is unreachable") from e
            raise AssertionError("unreachable")

    def _one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        return self._run(lambda c: c.execute(sql, params).fetchone())

    def _all(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        return self._run(lambda c: c.execute(sql, params).fetchall())

    def _exec(self, sql: str, params: tuple = ()) -> int:
        return self._run(lambda c: c.execute(sql, params).rowcount)

    def init(self) -> None:
        """Create the schema now if the database is reachable; otherwise on the first connection that works."""
        try:
            self._run(lambda c: None)
        except StoreUnavailable:
            logger.warning("case-file database unreachable at start-up: guests still work")

    # ---------- users ----------

    @staticmethod
    def _user(row: dict[str, Any] | None) -> User | None:
        return None if row is None else User(id=str(row["id"]), phone_hash=row["phone_hash"],
                                            phone_last4=row["phone_last4"], language=row["language"],
                                            created=row["created"])

    def user_by_phone_hash(self, phone_hash: str) -> User | None:
        return self._user(self._one("SELECT * FROM users WHERE phone_hash = %s", (phone_hash,)))

    def create_user(self, phone_hash: str, phone_last4: str, language: str) -> User:
        row = self._one("INSERT INTO users (id, phone_hash, phone_last4, language) VALUES (%s, %s, %s, %s) "
                        "ON CONFLICT (phone_hash) DO UPDATE SET phone_hash = EXCLUDED.phone_hash RETURNING *",
                        (uuid.uuid4(), phone_hash, phone_last4, language))
        return self._user(row)  # type: ignore[return-value]

    def get_user(self, user_id: str) -> User | None:
        return self._user(self._one("SELECT * FROM users WHERE id = %s", (_uuid(user_id),))) if _uuid(user_id) else None

    def set_language(self, user_id: str, language: str) -> User | None:
        if not _uuid(user_id):
            return None
        return self._user(self._one("UPDATE users SET language = %s WHERE id = %s RETURNING *", (language, _uuid(user_id))))

    def delete_user(self, user_id: str) -> bool:
        return bool(_uuid(user_id)) and self._exec("DELETE FROM users WHERE id = %s", (_uuid(user_id),)) > 0

    # ---------- checks ----------

    def _record(self, row: dict[str, Any], progress: dict[int, bool]) -> CheckRecord:
        return CheckRecord(id=str(row["id"]), user_id=str(row["user_id"]), session_id=row["session_id"],
                           previous_id=str(row["previous_id"]) if row["previous_id"] else None,
                           language=row["language"], created=row["created"], updated=row["updated"],
                           data=CheckData.model_validate(row["data"]), steps_done=progress)

    def _progress(self, check_ids: list[str]) -> dict[str, dict[int, bool]]:
        out: dict[str, dict[int, bool]] = {i: {} for i in check_ids}
        if check_ids:
            for r in self._all("SELECT check_id, step, done FROM step_progress WHERE check_id = ANY(%s)",
                               ([uuid.UUID(i) for i in check_ids],)):
                out[str(r["check_id"])][r["step"]] = r["done"]
        return out

    def save_check(self, user_id: str, session_id: str, language: str, data: CheckData,
                   previous_id: str | None = None) -> CheckRecord:
        def tx(c: psycopg.Connection) -> dict[str, Any]:
            with c.transaction():
                old = c.execute("SELECT id, user_id, data FROM checks WHERE session_id = %s FOR UPDATE",
                                (session_id,)).fetchone()
                if old is not None:
                    if str(old["user_id"]) != user_id:
                        raise PermissionError("session belongs to another user")
                    same = [s["voice"] for s in old["data"]["steps"]] == [s.voice for s in data.steps]
                    if not same:  # a re-plan renumbered the steps: old ticks no longer apply
                        c.execute("DELETE FROM step_progress WHERE check_id = %s", (old["id"],))
                    return c.execute("UPDATE checks SET data = %s, language = %s, updated = now() WHERE id = %s "
                                     "RETURNING *", (Jsonb(data.model_dump(mode="json")), language, old["id"])).fetchone()
                return c.execute(
                    "INSERT INTO checks (id, user_id, session_id, previous_id, language, data) "
                    "VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
                    (uuid.uuid4(), uuid.UUID(user_id), session_id, _uuid(previous_id) if previous_id else None,
                     language, Jsonb(data.model_dump(mode="json")))).fetchone()

        row = self._run(tx)
        return self._record(row, self._progress([str(row["id"])])[str(row["id"])])

    def list_checks(self, user_id: str) -> list[CheckRecord]:
        if not _uuid(user_id):
            return []
        rows = self._all("SELECT * FROM checks WHERE user_id = %s ORDER BY created DESC", (_uuid(user_id),))
        progress = self._progress([str(r["id"]) for r in rows])
        return [self._record(r, progress[str(r["id"])]) for r in rows]

    def get_check(self, user_id: str, check_id: str) -> CheckRecord | None:
        if not (_uuid(user_id) and _uuid(check_id)):
            return None
        row = self._one("SELECT * FROM checks WHERE id = %s AND user_id = %s", (_uuid(check_id), _uuid(user_id)))
        return None if row is None else self._record(row, self._progress([check_id])[check_id])

    def delete_check(self, user_id: str, check_id: str) -> bool:
        if not (_uuid(user_id) and _uuid(check_id)):
            return False
        return self._exec("DELETE FROM checks WHERE id = %s AND user_id = %s", (_uuid(check_id), _uuid(user_id))) > 0

    def set_step(self, user_id: str, check_id: str, step: int, done: bool) -> bool:
        check = self.get_check(user_id, check_id)
        if check is None or not any(s.index == step for s in check.data.steps):
            return False
        self._exec("INSERT INTO step_progress (check_id, step, done) VALUES (%s, %s, %s) ON CONFLICT (check_id, step) "
                   "DO UPDATE SET done = EXCLUDED.done, updated = now()", (_uuid(check_id), step, done))
        return True

    # ---------- feedback and retention ----------

    def add_feedback(self, entry: FeedbackEntry) -> None:
        self._exec("INSERT INTO feedback (session_id, target, value, comment) VALUES (%s, %s, %s, %s)",
                   (entry.session_id, entry.target, entry.value, entry.comment))

    def purge_checks(self, older_than: datetime) -> int:
        return self._exec("DELETE FROM checks WHERE created < %s", (older_than,))


def _uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None
