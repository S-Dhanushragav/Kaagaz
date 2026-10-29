"""speak node: for every plan step, the screen details in the family's language, the TTS input (numbers spelled
out), and the first sentence synthesized right away so it can play as soon as the plan is ready. The rest are
synthesized in the background (and on demand by the API); each is cached by (model, text)."""

import logging
import threading
from typing import Any, Callable

from agents.speech import speech_text
from agents.tools import load_fixes
from agents.voice import load_voice, say
from schemas.fixes import FixPlan, FixStep

logger = logging.getLogger(__name__)


def step_display(step: FixStep, language: str) -> dict[str, Any] | None:
    """Office, documents to bring, fee and time limit as the family reads them (each with its status)."""
    p = load_fixes().get(step.procedure_id or "")
    if step.kind != "fix" or p is None:
        return None
    t = load_voice(language)

    def show(fact: Any) -> dict[str, Any] | None:
        return None if fact is None else {"text": say(t, fact), "verified": fact.status == "verified"}

    return {
        "office": show(p.office) if step.office else None,
        "bring": [show(f) for f in p.bring if f.value in step.bring],
        "fee": show(p.fee) if step.fee else None,
        "time_limit": show(p.time_limit) if step.time_limit else None,
    }


def step_speech(plan: FixPlan, language: str) -> list[dict[str, Any]]:
    return [{"index": i, "kind": s.kind, "text": s.voice, "speech": speech_text(s.voice, language),
             "display": step_display(s, language)} for i, s in enumerate(plan.steps)]


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
