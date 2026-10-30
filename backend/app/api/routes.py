"""HTTP API for the mobile web app.

POST /sessions                  video upload + language -> session (videos capped at 45 s and ~60 MB)
POST /sessions/sample           the bundled sample family's sweep video, no upload
GET  /sessions/{id}             stage progress, partial results, the pending question
POST /sessions/{id}/answer      {question_id, option} (JSON) or a short WAV clip (form: question_id, audio)
GET  /sessions/{id}/audio/{key} TTS WAV for 'question' or 'step-<n>'
GET  /sessions/{id}/crops/{doc}  thumbnail of a found document's best crop (from memory; gone with the session)
POST /sessions/{id}/closeup     a clearer photo of one document on the close-up list (form: document_id, photo|sample)
POST /feedback                  {session_id, target, value, comment}: thumbs up/down, stored anonymously
GET  /schemes?lang=             the scheme catalog: each scheme's rules as lines, with status and sources (YAML only)
"""

from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from app.api.account import optional_user
from app.config import get_settings
from app.feedback import Feedback, record
from app.sessions import SessionError, SessionManager

router = APIRouter()
Language = Literal["en", "hi", "mr"]
CHUNK = 1024 * 1024
MAX_AUDIO_BYTES = 2 * 1024 * 1024  # ~60 s of 16 kHz mono WAV; answers are a few seconds
MAX_PHOTO_BYTES = 15 * 1024 * 1024


def manager(request: Request) -> SessionManager:
    return request.app.state.sessions


def _fail(e: SessionError) -> HTTPException:
    return HTTPException(status_code=e.status, detail=e.message)


class SampleRequest(BaseModel):
    language: Language = "mr"
    recheck_of: str | None = None  # "Check again" on a stored check (logged in only)


def _recheck(request: Request, user: Any, recheck_of: str | None) -> str | None:
    """A re-check links to one of the user's own stored checks; guests cannot re-check."""
    if not recheck_of:
        return None
    if user is None or request.app.state.store.get_check(user.id, recheck_of) is None:
        raise HTTPException(404, "No such check.")
    return recheck_of


class OptionAnswer(BaseModel):
    question_id: str
    option: int


@router.post("/sessions")
async def create_session(request: Request, video: UploadFile = File(...), language: Language = Form("mr"),
                         recheck_of: str | None = Form(None), user: Any = Depends(optional_user)) -> dict[str, Any]:
    sessions = manager(request)
    previous = _recheck(request, user, recheck_of)
    try:
        sessions.check_rate()
    except SessionError as e:
        raise _fail(e) from e
    limit = int(get_settings().max_video_mb * CHUNK)
    folder = sessions.new_upload_folder()
    raw = folder / "upload.bin"
    size = 0
    with raw.open("wb") as f:
        while chunk := await video.read(CHUNK):
            size += len(chunk)
            if size > limit:
                f.close()
                sessions.delete(folder.name)
                raise HTTPException(413, f"The video is larger than {get_settings().max_video_mb:.0f} MB.")
            f.write(chunk)
    try:
        session = sessions.start_upload(raw, language, user_id=user.id if user else None, recheck_of=previous)
    except SessionError as e:
        raise _fail(e) from e
    return {"id": session.id}


@router.post("/sessions/sample")
def create_sample(request: Request, body: SampleRequest, user: Any = Depends(optional_user)) -> dict[str, Any]:
    previous = _recheck(request, user, body.recheck_of)
    try:
        return {"id": manager(request).start_sample(body.language, user_id=user.id if user else None,
                                                    recheck_of=previous).id}
    except SessionError as e:
        raise _fail(e) from e


@router.get("/sessions/{session_id}")
def get_session(request: Request, session_id: str) -> dict[str, Any]:
    try:
        return manager(request).view(session_id)
    except SessionError as e:
        raise _fail(e) from e


@router.post("/sessions/{session_id}/answer")
async def answer(request: Request, session_id: str) -> dict[str, Any]:
    sessions = manager(request)
    try:
        if request.headers.get("content-type", "").startswith("application/json"):
            body = OptionAnswer.model_validate(await request.json())
            return sessions.answer_option(session_id, body.question_id, body.option)
        form = await request.form()
        audio, question_id = form.get("audio"), form.get("question_id")
        if audio is None or not hasattr(audio, "read") or not question_id:
            raise HTTPException(422, "Send {question_id, option} as JSON, or question_id and audio as a form.")
        data = await audio.read(MAX_AUDIO_BYTES + 1)
        if len(data) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "The recording is too long.")
        return sessions.answer_audio(session_id, str(question_id), data)
    except SessionError as e:
        raise _fail(e) from e


@router.post("/sessions/{session_id}/closeup")
async def closeup(request: Request, session_id: str, document_id: str = Form(...), sample: bool = Form(False),
                  photo: UploadFile | None = File(None)) -> dict[str, Any]:
    """A clearer photo of one document on the close-up list (or, for the sample family, its bundled photo)."""
    sessions = manager(request)
    try:
        if sample:
            data = sessions.sample_closeup(session_id, document_id)
        elif photo is not None:
            data = await photo.read(MAX_PHOTO_BYTES + 1)
            if len(data) > MAX_PHOTO_BYTES:
                raise HTTPException(413, "The photo is too large.")
        else:
            raise HTTPException(422, "Send a photo, or sample=true for the sample family.")
        return sessions.closeup(session_id, document_id, data)
    except SessionError as e:
        raise _fail(e) from e


@router.get("/sessions/{session_id}/audio/{key}")
def audio(request: Request, session_id: str, key: str) -> FileResponse:
    sessions = manager(request)
    try:
        text = sessions.speech_text(session_id, key)
    except SessionError as e:
        raise _fail(e) from e
    try:
        from clients.tts import TTSError, synthesize
    except ImportError as e:
        raise HTTPException(503, "Speech output is not available on this server.") from e
    try:
        speech = synthesize(text, sessions.get(session_id).language)
    except TTSError as e:
        raise HTTPException(503, f"Speech output is not available: {e}") from e
    return FileResponse(speech.path, media_type="audio/wav", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/sessions/{session_id}/crops/{document_id}")
def crop(request: Request, session_id: str, document_id: str) -> Response:
    try:
        jpeg = manager(request).thumbnail(session_id, document_id)
    except SessionError as e:
        raise _fail(e) from e
    # no-store: a close-up replaces the crop, and nothing of a document should outlive the session in a cache
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})


@router.post("/feedback", status_code=204)
def feedback(request: Request, body: Feedback) -> Response:
    record(body, request.app.state.store)
    return Response(status_code=204)


@router.get("/schemes")
def schemes(lang: Language = "mr") -> list[dict[str, Any]]:
    from agents.catalog import catalog

    return [s.model_dump() for s in catalog(lang)]
