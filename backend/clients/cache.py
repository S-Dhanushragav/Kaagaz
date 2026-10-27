"""Disk cache for model calls: one JSON file per request, keyed by a hash of the full input.

Callers decide what goes into the key; they must include everything that can change
the output (provider, model, prompts, image bytes, sampling params, response format).
Only successful responses should ever be passed to `set`.
"""

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping


def _json_default(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        # Hash raw bytes (e.g. images) instead of embedding them in the key material.
        return {"__bytes_sha256__": hashlib.sha256(value).hexdigest()}
    raise TypeError(f"Cannot use {type(value).__name__} in a cache key")


def make_key(fields: Mapping[str, Any]) -> str:
    """Stable SHA-256 hex key for a mapping of request fields."""
    canonical = json.dumps(
        fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_json_default
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class DiskCache:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        try:
            with path.open(encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, UnicodeDecodeError):
            path.unlink(missing_ok=True)  # corrupt entry: treat as a miss
            return None

    def set(self, key: str, value: dict[str, Any]) -> None:
        # Write to a temp file and rename, so a crash never leaves a half-written entry.
        fd, tmp = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(value, f, ensure_ascii=False)
            os.replace(tmp, self._path(key))
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
