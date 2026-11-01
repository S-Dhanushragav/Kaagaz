"""A daily token budget for Baseten (Muse Spark Open), and counts of fallbacks to Muse Spark.

Every Baseten call that reaches the provider (cache hits are free) adds its total tokens to today's count; once
BASETEN_DAILY_TOKENS is used up, `clients/llm.py` stops calling Baseten until the next day (IST): Ask shows its
friendly "unavailable" reply, and tasks that may fall back (BASETEN_FALLBACK_TASKS) are read by Muse Spark instead.
The count is kept in memory and in a small JSON file under the cache directory, so a restart does not reset it.
Only numbers are stored or logged: no prompts, no replies.
"""

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
_lock = threading.Lock()
_state: dict[str, Any] = {}


def today() -> str:
    return datetime.now(IST).date().isoformat()


def _path(day: str) -> Path:
    return get_settings().cache_path / "budget" / f"baseten-{day}.json"


def _load(day: str) -> dict[str, Any]:
    """Today's counters (from memory, else from disk, else zero). Call with the lock held."""
    if _state.get("day") != day:
        _state.clear()
        _state.update({"day": day, "tokens": 0, "calls": 0, "fallbacks": {}, "refused": 0})
        try:
            saved = json.loads(_path(day).read_text(encoding="utf-8"))
            _state.update({k: saved[k] for k in ("tokens", "calls", "fallbacks", "refused") if k in saved})
        except (OSError, ValueError):
            pass
    return _state


def _save(state: dict[str, Any]) -> None:
    path = _path(state["day"])
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        tmp.replace(path)
    except OSError as e:  # the budget still works in memory
        logger.warning("budget: could not save the count: %s", type(e).__name__)


def remaining() -> int:
    with _lock:
        return max(0, get_settings().baseten_daily_tokens - _load(today())["tokens"])


def exhausted() -> bool:
    return remaining() <= 0


def add(tokens: int) -> None:
    """A Baseten call that reached the provider used `tokens` (prompt + completion)."""
    with _lock:
        state = _load(today())
        state["tokens"] += max(0, tokens)
        state["calls"] += 1
        _save(state)


def refused(task: str) -> None:
    """A Baseten call was not made because today's budget is used up (and the task has no fallback)."""
    with _lock:
        state = _load(today())
        state["refused"] += 1
        _save(state)
    logger.warning("budget: Baseten daily budget used up; %s call refused", task)


def fallback(task: str, reason: str) -> None:
    """A Baseten call went to Muse Spark instead (reason: budget | error). Counts only."""
    with _lock:
        state = _load(today())
        key = f"{task}:{reason}"
        state["fallbacks"][key] = state["fallbacks"].get(key, 0) + 1
        _save(state)
        n = state["fallbacks"][key]
    logger.warning("budget: Baseten -> Muse Spark fallback (%s, %s), %d today", task, reason, n)


def status() -> dict[str, Any]:
    """Today's numbers, for /health and the logs."""
    with _lock:
        state = dict(_load(today()))
    limit = get_settings().baseten_daily_tokens
    return {"day": state["day"], "tokens": state["tokens"], "limit": limit, "remaining": max(0, limit - state["tokens"]),
            "calls": state["calls"], "refused": state["refused"], "fallbacks": dict(state["fallbacks"])}


def reset_for_tests() -> None:
    with _lock:
        _state.clear()
