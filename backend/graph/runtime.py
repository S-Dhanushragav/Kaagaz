"""Per-session objects that cannot live in the checkpointed state: the streaming reader (live threads), the
finder's result and the crop images (bytes). One process holds all sessions (the app runs one container)."""

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionRuntime:
    reader: Any = None
    find_result: Any = None
    images: dict[str, list[bytes]] = field(default_factory=dict)  # document id -> crops (best first)


_RUNTIMES: dict[str, SessionRuntime] = {}
_LOCK = threading.Lock()


def runtime(session_id: str) -> SessionRuntime:
    with _LOCK:
        return _RUNTIMES.setdefault(session_id, SessionRuntime())


def drop(session_id: str) -> None:
    with _LOCK:
        _RUNTIMES.pop(session_id, None)
