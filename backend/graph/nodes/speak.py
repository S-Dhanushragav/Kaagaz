"""speak node: the TTS input for every plan step (numbers spelled out), and the first sentence synthesized
right away so it can play as soon as the plan is ready. The rest are synthesized in the background (and on
demand by the API); each is cached by (model, text)."""

import logging
import threading
from typing import Any, Callable

from agents.speech import speech_text
from schemas.fixes import FixPlan

logger = logging.getLogger(__name__)


def step_speech(plan: FixPlan, language: str) -> list[dict[str, Any]]:
    return [{"index": i, "kind": s.kind, "text": s.voice, "speech": speech_text(s.voice, language)}
            for i, s in enumerate(plan.steps)]


def speak(plan: FixPlan, language: str, tts: Callable[[str, str], Any] | None) -> list[dict[str, Any]]:
    items = step_speech(plan, language)
    if tts is None or not items:
        return items
    try:
        tts(items[0]["speech"], language)
    except Exception as e:  # noqa: BLE001 - speech is optional; the plan is still shown
        logger.warning("TTS failed: %s", e)
        return items

    def rest() -> None:
        for item in items[1:]:
            try:
                tts(item["speech"], language)
            except Exception as e:  # noqa: BLE001
                logger.warning("TTS failed: %s", e)

    threading.Thread(target=rest, daemon=True, name="tts-rest").start()
    return items
