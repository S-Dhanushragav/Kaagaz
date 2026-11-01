"""Ask Kaagaz API (agents/ask.py).

POST /ask               {question, language, session_id? | check_id?, voice_ticket?} -> a checked answer (never an
                        error: if the model is slow or down, a friendly fallback). A finished live session, or a saved
                        check of the logged-in user, is attached as the family's context; otherwise only scheme questions.
POST /ask/transcribe    a spoken question (form: audio, language, session_id? | check_id?) -> {text, voice_ticket,
                        timings}: the text goes into the box for the family to check; nothing is sent automatically.
                        It counts as a question; the ticket lets the /ask that follows go uncounted. The audio is
                        converted in memory and a temporary file deleted at once; the transcript is neither cached nor
                        logged.
GET  /ask/suggestions   ?language=&session_id=|check_id= -> up to 3 questions about this family (templates, no model)
GET  /ask/audio/{id}    an answer read aloud (MMS-TTS); answers are kept in memory for an hour. Speech starts being made
                        as soon as the answer exists (when the TTS model is loaded), so Listen does not wait for it.

Limits (typed and spoken questions alike): ASK_PER_SESSION_HOUR questions per session or saved check, ASK_PER_IP_HOUR per client IP (the last
X-Forwarded-For entry, as for login). Question text and names are never logged; agents/ask.py logs token counts.
"""

import logging
import secrets
import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.account import client_ip, optional_user
from app.config import get_settings
from app.sessions import SessionError

logger = logging.getLogger(__name__)
router = APIRouter()
Language = Literal["en", "hi", "mr"]
ANSWER_TTL_S = 3600
MAX_ANSWERS = 2000
TICKET_TTL_S = 600
MAX_QUESTION_AUDIO_BYTES = 4 * 1024 * 1024  # 30 s of AAC or Opus is well under 1 MB


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    language: Language = "mr"
    session_id: str | None = Field(None, max_length=64)
    check_id: str | None = Field(None, max_length=64)
    voice_ticket: str | None = Field(None, max_length=64)  # from POST /ask/transcribe: already counted


def speak(text: str, language: str) -> Path:
    """The WAV of an answer (MMS-TTS, cached on disk by text)."""
    from agents.ask import answer_speech
    from clients.tts import synthesize

    return synthesize(answer_speech(text, language), language).path


def _tts_ready() -> bool:
    """Speak ahead only where the TTS models are loaded (the server preloads them; tests and dev may not)."""
    try:
        from clients.tts import _load
    except ImportError:
        return False
    return _load.cache_info().currsize > 0


class AskService:
    """Rate limits (sliding hour), the answers kept for Listen, and their speech made ahead. One process: in memory."""

    def __init__(self, speaker: Callable[[str, str], Path] | None = speak, ready: Callable[[], bool] = _tts_ready) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}
        self._answers: dict[str, tuple[float, str, str]] = {}  # id -> (created, text to speak, language)
        self._speech: dict[str, Future[Path]] = {}  # id -> speech being made (or made) ahead of Listen
        self._speaker, self._ready = speaker, ready
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ask-tts")
        self._tickets: dict[str, tuple[float, str]] = {}  # voice ticket -> (created, limit key it was counted under)

    def take(self, limits: list[tuple[str, int]], now: float | None = None) -> bool:
        """Count one question against every (key, limit), or none if any is used up."""
        now = time.time() if now is None else now
        with self._lock:
            windows = []
            for key, limit in limits:
                hits = self._hits.setdefault(key, deque())
                while hits and now - hits[0] >= 3600:
                    hits.popleft()
                if len(hits) >= limit:
                    return False
                windows.append(hits)
            for hits in windows:
                hits.append(now)
            return True

    def ticket(self, key: str) -> str:
        """A spoken question was counted when it was transcribed: the ask that follows is not counted again."""
        t = secrets.token_urlsafe(16)
        with self._lock:
            now = time.time()
            self._tickets = {k: v for k, v in self._tickets.items() if now - v[0] < TICKET_TTL_S}
            self._tickets[t] = (now, key)
        return t

    def use_ticket(self, ticket: str | None, key: str) -> bool:
        """One use, for the same session or check, within 10 minutes."""
        if not ticket:
            return False
        with self._lock:
            entry = self._tickets.pop(ticket, None)
        return entry is not None and entry[1] == key and time.time() - entry[0] < TICKET_TTL_S

    def remember(self, text: str, language: str) -> str:
        answer_id = secrets.token_urlsafe(12)
        with self._lock:
            now = time.time()
            if len(self._answers) >= MAX_ANSWERS:
                self._answers = {k: v for k, v in self._answers.items() if now - v[0] < ANSWER_TTL_S}
                self._speech = {k: v for k, v in self._speech.items() if k in self._answers}
            self._answers[answer_id] = (now, text, language)
            if self._speaker is not None and text and self._ready():
                self._speech[answer_id] = self._pool.submit(self._speaker, text, language)
        return answer_id

    def speech(self, answer_id: str) -> Path | None:
        """The answer's WAV if it was made ahead (waits for it if it is still being made); None: make it now.
        Raises what making it raised."""
        with self._lock:
            future = self._speech.get(answer_id)
        return None if future is None else future.result()

    def recall(self, answer_id: str) -> tuple[str, str] | None:
        with self._lock:
            entry = self._answers.get(answer_id)
        if entry is None or time.time() - entry[0] >= ANSWER_TTL_S:
            return None
        return entry[1], entry[2]


def service(request: Request) -> AskService:
    if not hasattr(request.app.state, "ask"):
        request.app.state.ask = AskService()
    return request.app.state.ask


def context(request: Request, user: Any, session_id: str | None, check_id: str | None) -> tuple[Any, str]:
    """(FamilyContext or None, rate-limit key). A saved check needs its owner's login; a live session is attached once
    it has finished (a running one answers scheme questions only)."""
    from agents.ask_tools import FamilyContext

    if check_id:
        record = request.app.state.store.get_check(user.id, check_id) if user is not None else None
        if record is None:
            raise HTTPException(404, "No such check.")
        return FamilyContext.from_check(record), f"check:{check_id}"
    if session_id:
        sessions = request.app.state.sessions
        try:
            session = sessions.get(session_id)
        except SessionError as e:
            raise HTTPException(e.status, e.message) from e
        if session.status != "done":
            return None, f"session:{session_id}"
        view = sessions.view(session_id)
        if not (view.get("household") or view.get("recapture")):
            return None, f"session:{session_id}"
        return FamilyContext.from_view(view), f"session:{session_id}"
    return None, ""


def limits(request: Request, key: str) -> list[tuple[str, int]]:
    s = get_settings()
    out = [(f"ip:{client_ip(request)}", s.ask_per_ip_hour)]
    if key:
        out.append((key, s.ask_per_session_hour))
    return out


@router.post("/ask")
def ask_question(request: Request, body: AskRequest, user: Any = Depends(optional_user)) -> dict[str, Any]:
    from agents.ask import AskAnswer, ask
    from agents.ask_tools import load_ask

    ctx, key = context(request, user, body.session_id, body.check_id)
    asks = service(request)
    if not asks.use_ticket(body.voice_ticket, key) and not asks.take(limits(request, key)):
        raise HTTPException(429, load_ask(body.language).replies["limit"])
    try:
        answer = ask(body.question, body.language, ctx)
    except Exception:  # noqa: BLE001 - the app keeps working whatever happens here
        logger.exception("ask failed")
        answer = AskAnswer(kind="unavailable", text=load_ask(body.language).replies["unavailable"])
    spoken = " ".join(x for x in (answer.text, answer.note) if x)
    return {"id": asks.remember(spoken, body.language), "kind": answer.kind, "text": answer.text, "note": answer.note,
            "sources": [s.model_dump() for s in answer.sources], "chips": [c.model_dump() for c in answer.chips]}


@router.get("/ask/suggestions")
def ask_suggestions(request: Request, language: Language = "mr", session_id: str | None = None,
                    check_id: str | None = None, user: Any = Depends(optional_user)) -> list[str]:
    from agents.ask_tools import suggestions

    ctx, _ = context(request, user, session_id, check_id)
    return suggestions(ctx, language) if ctx is not None else []


@router.get("/ask/audio/{answer_id}")
def ask_audio(request: Request, answer_id: str) -> FileResponse:
    asks = service(request)
    found = asks.recall(answer_id)
    if found is None:
        raise HTTPException(404, "No such answer (answers are kept for an hour).")
    text, language = found
    try:
        from clients.tts import TTSError
    except ImportError as e:
        raise HTTPException(503, "Speech output is not available on this server.") from e
    try:
        path = asks.speech(answer_id) or speak(text, language)
    except TTSError as e:
        raise HTTPException(503, f"Speech output is not available: {e}") from e
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "private, max-age=3600"})


def _keywords(language: str, ctx: Any) -> list[str] | None:
    """Words to bias recognition toward (scheme and family names), only for ASR_KEYWORD_LANGUAGES (it hurt hi/mr)."""
    from rules.loader import load_schemes

    if language not in {x.strip() for x in get_settings().asr_keyword_languages.split(",")}:
        return None
    words = [s.short.get(language) or s.short["en"] for s in load_schemes()]
    if ctx is not None:
        names = [(m.name_en if language == "en" else m.name_mr) or m.name_en for m in ctx.data.members]  # its own script
        words += [n.split()[0] for n in names if n and n.split()]
    return list(dict.fromkeys(words))


@router.post("/ask/transcribe")
async def ask_transcribe(request: Request, audio: UploadFile = File(...), language: str = Form("mr"),
                         session_id: str | None = Form(None), check_id: str | None = Form(None),
                         user: Any = Depends(optional_user)) -> dict[str, Any]:
    from starlette.concurrency import run_in_threadpool

    from app.audio import AudioError, to_wav16k
    from clients.transcribe import TranscribeError, transcribe

    settings = get_settings()
    if language not in settings.asr_language_names:
        raise HTTPException(422, {"code": "language", "message": "Speech input is not available in this language."})
    data = await audio.read(MAX_QUESTION_AUDIO_BYTES + 1)
    if len(data) > MAX_QUESTION_AUDIO_BYTES:
        raise HTTPException(413, {"code": "too_long", "message": "The recording is too long."})
    ctx, key = context(request, user, session_id, check_id)
    asks = service(request)
    if not asks.take(limits(request, key)):
        from agents.ask_tools import load_ask

        raise HTTPException(429, {"code": "limit", "message": load_ask(language).replies["limit"]
                                  if language in ("en", "hi", "mr") else "Too many questions this hour."})
    start = time.perf_counter()
    try:
        wav, seconds = await run_in_threadpool(to_wav16k, data, settings.max_question_audio_s)
    except AudioError as e:
        raise HTTPException(422, {"code": e.code, "message": str(e)}) from e
    finally:
        del data
    converted = time.perf_counter()
    try:
        heard = await run_in_threadpool(lambda: transcribe(wav, language, _keywords(language, ctx), cache=False))
    except TranscribeError as e:
        logger.warning("question transcription failed: %s", type(e).__name__)
        raise HTTPException(503, {"code": "unavailable", "message": "Speech input is not available right now."}) from e
    done = time.perf_counter()
    text = heard.text.strip()
    if not text:
        raise HTTPException(422, {"code": "silent", "message": "nothing was heard"})
    logger.info("question transcribed [%s]: %.1f s audio, convert %.2f s, transcribe %.2f s", language, seconds,
                converted - start, done - converted)
    return {"text": text, "voice_ticket": asks.ticket(key),
            "timings": {"audio_s": round(seconds, 2), "convert_s": round(converted - start, 2),
                        "transcribe_s": round(done - converted, 2)}}
