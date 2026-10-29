"""Sessions: one pipeline run per family, in a background thread, on the shared graph (in-memory checkpointer;
the app runs as one process/container).

- An uploaded video is normalized (constant 30 fps), checked against the size and length caps, and deleted
  by the graph as soon as the finder is done. The bundled sample is never deleted.
- The graph pauses at a family question; `answer` resumes it with an option index (spoken answers are matched
  to an option first; only a match resumes).
- Everything a session holds (folder, crops, checkpoint, results) is deleted `session_ttl_s` after it started.
- Uploads are rate-limited per hour; the sample is not counted (its model calls are cached).
"""

import logging
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal

from langgraph.types import Command

from agents.answers import AnswerResult, Prompt, answer_from_audio
from app.config import REPO_ROOT, get_settings
from graph.build import build_graph
from graph.runtime import drop
from graph.state import STAGES

logger = logging.getLogger(__name__)

Status = Literal["running", "waiting", "done", "error"]


class SessionError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status, self.message = status, message


@dataclass
class Session:
    id: str
    language: str
    sample: bool
    created: float = field(default_factory=time.time)
    status: Status = "running"
    error: str | None = None
    question: dict[str, Any] | None = None  # the pending family question
    heard: list[str] = field(default_factory=list)  # transcripts of spoken tries for the pending question
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def config(self) -> dict[str, Any]:
        return {"configurable": {"thread_id": self.id}}


class SessionManager:
    def __init__(self, graph: Any = None) -> None:
        self.graph = graph or build_graph()
        self.sessions: dict[str, Session] = {}
        self.uploads: list[float] = []  # start times of upload sessions (rate limit)
        self._lock = threading.Lock()

    # ---------- paths ----------

    @staticmethod
    def root() -> Path:
        d = get_settings().sessions_dir
        return d if d.is_absolute() else REPO_ROOT / d

    def folder(self, session_id: str) -> Path:
        return self.root() / session_id

    # ---------- start ----------

    def check_rate(self) -> None:
        limit = get_settings().max_sessions_per_hour
        now = time.time()
        with self._lock:
            self.uploads = [t for t in self.uploads if now - t < 3600]
            if len(self.uploads) >= limit:
                raise SessionError(429, "Too many sessions this hour. Please try the sample family.")
            self.uploads.append(now)

    def start_upload(self, video: Path, language: str) -> Session:
        """`video` is the saved upload inside this session's folder (already size-checked)."""
        from vision.frames import normalize_upload

        settings = get_settings()
        session_id = video.parent.name
        normalized = video.with_name("video.mp4")
        try:
            seconds = normalize_upload(video, normalized, settings.max_video_s)
        except (ValueError, RuntimeError) as e:
            shutil.rmtree(video.parent, ignore_errors=True)
            raise SessionError(422, str(e)) from e
        finally:
            video.unlink(missing_ok=True)
        if seconds > settings.max_video_s + 0.5:
            shutil.rmtree(video.parent, ignore_errors=True)
            raise SessionError(413, f"The video is longer than {settings.max_video_s:.0f} seconds.")
        return self._start(session_id, normalized, language, sample=False)

    def start_sample(self, language: str) -> Session:
        video = REPO_ROOT / get_settings().sample_video
        if not video.exists():
            raise SessionError(503, "The sample video is not available on this server.")
        session_id = uuid.uuid4().hex[:12]
        self.folder(session_id).mkdir(parents=True, exist_ok=True)
        return self._start(session_id, video, language, sample=True)

    def new_upload_folder(self) -> Path:
        folder = self.folder(uuid.uuid4().hex[:12])
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _start(self, session_id: str, video: Path, language: str, sample: bool) -> Session:
        session = Session(id=session_id, language=language, sample=sample)
        with self._lock:
            self.sessions[session_id] = session
        state = {"session_id": session_id, "language": language, "video_path": str(video), "delete_video": not sample,
                 "reference_date": date.today().isoformat()}
        self._run(session, state)
        return session

    def _run(self, session: Session, graph_input: Any) -> None:
        def work() -> None:
            try:
                out = self.graph.invoke(graph_input, session.config)
                interrupts = out.get("__interrupt__") if isinstance(out, dict) else None
                with session.lock:
                    if interrupts:
                        session.status, session.question, session.heard = "waiting", interrupts[0].value, []
                    else:
                        session.status, session.question = "done", None
            except Exception as e:  # noqa: BLE001 - reported to the client
                logger.exception("session %s failed", session.id)
                with session.lock:
                    session.status, session.error = "error", f"{type(e).__name__}: {e}"

        session.status = "running"
        threading.Thread(target=work, daemon=True, name=f"session-{session.id}").start()

    # ---------- read ----------

    def get(self, session_id: str) -> Session:
        session = self.sessions.get(session_id)
        if session is None:
            raise SessionError(404, "No such session (sessions are deleted after an hour).")
        return session

    def view(self, session_id: str) -> dict[str, Any]:
        session = self.get(session_id)
        values = self.graph.get_state(session.config).values or {}
        timings = values.get("timings", {})
        stages = [{"stage": s, "done": s in timings, "seconds": timings.get(s)} for s in STAGES]
        current = next((s["stage"] for s in stages if not s["done"]), None) if session.status == "running" else None
        keys = ("found", "recapture", "household", "results", "issues", "plan", "speech", "usage")
        return {"id": session.id, "language": session.language, "sample": session.sample, "status": session.status,
                "error": session.error, "stage": current, "stages": stages, "question": session.question,
                "elapsed_s": round(time.time() - session.created, 1),
                **{k: values.get(k) for k in keys}}

    def speech_text(self, session_id: str, key: str) -> str:
        """TTS input for 'question' (the pending question) or 'step-<n>' (a plan step)."""
        session = self.get(session_id)
        if key == "question":
            if not session.question:
                raise SessionError(404, "No question is waiting.")
            return session.question["speech"]
        values = self.graph.get_state(session.config).values or {}
        try:
            return values.get("speech", [])[int(key.removeprefix("step-"))]["speech"]
        except (ValueError, IndexError) as e:
            raise SessionError(404, f"No such step: {key}") from e

    # ---------- answer ----------

    def _pending(self, session: Session, question_id: str) -> dict[str, Any]:
        if session.status != "waiting" or not session.question:
            raise SessionError(409, "No question is waiting.")
        if question_id != session.question["question_id"]:
            raise SessionError(409, "That question has already been answered.")
        return session.question

    def answer_option(self, session_id: str, question_id: str, option: int) -> dict[str, Any]:
        session = self.get(session_id)
        with session.lock:
            question = self._pending(session, question_id)
            if not 0 <= option < len(question["options"]):
                raise SessionError(422, "No such option.")
            session.question = None
        self._run(session, Command(resume=option))
        return {"action": "answered", "option": option}

    def answer_audio(self, session_id: str, question_id: str, audio: bytes) -> dict[str, Any]:
        session = self.get(session_id)
        with session.lock:
            question = self._pending(session, question_id)
            heard = list(session.heard)
        prompt = Prompt(options=question["options"], shown=question["shown"], screen=question["screen"],
                        speech=question["speech"], english_only=question["english_only"])
        result: AnswerResult = answer_from_audio(audio, prompt, session.language, earlier=heard)
        with session.lock:
            session.heard = [m.heard for m in result.attempts]
        if result.action == "answered" and result.option is not None:
            self.answer_option(session_id, question_id, result.option)
        return {"action": result.action, "option": result.option, "say": result.say,
                "heard": result.attempts[-1].heard if result.attempts else None}

    # ---------- cleanup ----------

    def cleanup(self, now: float | None = None) -> list[str]:
        now = now or time.time()
        ttl = get_settings().session_ttl_s
        expired = [s.id for s in list(self.sessions.values()) if now - s.created >= ttl]
        for session_id in expired:
            self.delete(session_id)
        return expired

    def delete(self, session_id: str) -> None:
        with self._lock:
            self.sessions.pop(session_id, None)
        drop(session_id)
        shutil.rmtree(self.folder(session_id), ignore_errors=True)
        try:
            self.graph.checkpointer.delete_thread(session_id)
        except (AttributeError, NotImplementedError):
            pass

    def start_cleanup_loop(self, every_s: int = 300) -> None:
        def loop() -> None:
            while True:
                time.sleep(every_s)
                try:
                    self.cleanup()
                except Exception:  # noqa: BLE001
                    logger.exception("cleanup failed")

        threading.Thread(target=loop, daemon=True, name="session-cleanup").start()
