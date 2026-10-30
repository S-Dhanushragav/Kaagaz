"""Feedback on the plan and on answers: thumbs up/down and an optional comment, stored anonymously in the case-file
store (the `feedback` table). Nothing identifying is kept: no IP address, no user agent, no user, no names; only the
session id (random), what the feedback is about, the value, the comment and the date.
"""

from typing import Literal

from pydantic import BaseModel, Field

from storage.models import FeedbackEntry
from storage.store import Store


class Feedback(BaseModel):
    session_id: str = Field(pattern=r"^[0-9a-f]{12}$")
    target: str = Field(pattern=r"^(plan|answer:[A-Za-z0-9_-]{1,40})$")  # the plan, or one answer (Phase 10)
    value: Literal["up", "down"]
    comment: str | None = Field(None, max_length=500)


def record(entry: Feedback, store: Store) -> None:
    store.add_feedback(FeedbackEntry(session_id=entry.session_id, target=entry.target, value=entry.value,
                                     comment=(entry.comment or "").strip() or None))
