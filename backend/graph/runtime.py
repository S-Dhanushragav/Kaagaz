"""Per-session objects that cannot live in the checkpointed state: the streaming reader (live threads), the
finder's result and the crop images (bytes). One process holds all sessions (the app runs one container).
Nothing here is written to disk; it all goes when the session is deleted (drop)."""

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionRuntime:
    reader: Any = None
    find_result: Any = None
    images: dict[str, list[bytes]] = field(default_factory=dict)  # document id -> crops (best first)
    found: list[str] = field(default_factory=list)  # document ids in the order the finder handed them over
    thumbs: dict[str, bytes] = field(default_factory=dict)  # document id -> small JPEG of the best crop
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add_document(self, document_id: str, images: list[bytes]) -> None:
        with self.lock:
            self.images[document_id] = list(images)
            self.thumbs.pop(document_id, None)
            if document_id not in self.found:
                self.found.append(document_id)

    def found_ids(self) -> list[str]:
        with self.lock:
            return list(self.found)


_RUNTIMES: dict[str, SessionRuntime] = {}
_LOCK = threading.Lock()


def runtime(session_id: str) -> SessionRuntime:
    with _LOCK:
        return _RUNTIMES.setdefault(session_id, SessionRuntime())


def drop(session_id: str) -> None:
    with _LOCK:
        _RUNTIMES.pop(session_id, None)
