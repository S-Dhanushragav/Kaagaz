"""Feedback on the plan and on answers: thumbs up/down and an optional comment, stored anonymously.

One JSON line per entry in `feedback_path` (Phase 9 moves this to the database). Nothing identifying is kept:
no IP address, no user agent, no names; only the session id (random, deleted with the session's data after an
hour), what the feedback is about, the value, the comment and the date.
"""

import json
import threading
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.config import REPO_ROOT, get_settings

_LOCK = threading.Lock()


class Feedback(BaseModel):
    session_id: str = Field(pattern=r"^[0-9a-f]{12}$")
    target: str = Field(pattern=r"^(plan|answer:[A-Za-z0-9_-]{1,40})$")  # the plan, or one answer (Phase 10)
    value: Literal["up", "down"]
    comment: str | None = Field(None, max_length=500)


def feedback_path() -> Path:
    p = get_settings().feedback_path
    return p if p.is_absolute() else REPO_ROOT / p


def record(entry: Feedback, path: Path | None = None) -> None:
    path = path or feedback_path()
    line = {**entry.model_dump(), "comment": (entry.comment or "").strip() or None, "date": date.today().isoformat()}
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
