"""Login and the family's case file (Phase 9).

POST /auth/start   {phone}               a one-time code (demo mode: returned in the reply; sms mode: sent by SMS)
POST /auth/verify  {phone, code, language} -> {token, user}; send the token as `Authorization: Bearer <token>`
GET  /me                                   the logged-in user (phone shown only as its last 4 digits)
PATCH /me {language}                       change the language
DELETE /me                                 delete the user and everything stored for them
GET  /me/checks                            the stored checks, newest first (summaries)
GET  /me/checks/{id}                       one check in full, with ticked steps
PATCH /me/checks/{id}/steps/{n} {done}     tick a plan step as done (or not)
DELETE /me/checks/{id}                     delete one check
GET  /me/checks/{id}/audio/{n}             a stored plan sentence, spoken again (MMS-TTS)
"""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.auth import AuthError, AuthService
from app.casefile import full, summary
from storage.models import User

router = APIRouter()
Language = Literal["en", "hi", "mr"]


def auth(request: Request) -> AuthService:
    return request.app.state.auth


def _fail(e: AuthError) -> HTTPException:
    return HTTPException(status_code=e.status, detail={"message": e.message, **e.extra} if e.extra else e.message)


def bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    return header[7:].strip() if header.lower().startswith("bearer ") else None


def optional_user(request: Request) -> User | None:
    """The logged-in user, or None for a guest (no header). A bad or expired token is an error, not a guest."""
    token = bearer(request)
    if token is None:
        return None
    user = auth(request).user_for(token)
    if user is None:
        raise HTTPException(401, "Please log in again.")
    return user


def current_user(request: Request) -> User:
    user = optional_user(request)
    if user is None:
        raise HTTPException(401, "Please log in.")
    return user


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def user_view(user: User) -> dict[str, Any]:
    return {"id": user.id, "phone_last4": user.phone_last4, "language": user.language, "created": user.created.isoformat()}


class StartRequest(BaseModel):
    phone: str = Field(max_length=32)


class VerifyRequest(BaseModel):
    phone: str = Field(max_length=32)
    code: str = Field(max_length=12)
    language: Language = "mr"


@router.post("/auth/start")
def auth_start(request: Request, body: StartRequest) -> dict[str, Any]:
    try:
        return auth(request).start(body.phone, client_ip(request))
    except AuthError as e:
        raise _fail(e) from e


@router.post("/auth/verify")
def auth_verify(request: Request, body: VerifyRequest) -> dict[str, Any]:
    try:
        token, user = auth(request).verify(body.phone, body.code, body.language)
    except AuthError as e:
        raise _fail(e) from e
    return {"token": token, "user": user_view(user)}


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict[str, Any]:
    return user_view(user)


class LanguageRequest(BaseModel):
    language: Language


class StepRequest(BaseModel):
    done: bool


def store(request: Request) -> Any:
    return request.app.state.store


@router.patch("/me")
def set_language(request: Request, body: LanguageRequest, user: User = Depends(current_user)) -> dict[str, Any]:
    updated = store(request).set_language(user.id, body.language)
    if updated is None:
        raise HTTPException(404, "No such user.")
    return user_view(updated)


@router.delete("/me", status_code=204)
def delete_me(request: Request, user: User = Depends(current_user)) -> Response:
    """Everything: the user, their checks, ticks and chats (the database cascades). Running sessions stop saving."""
    store(request).delete_user(user.id)
    request.app.state.sessions.forget_user(user.id)
    return Response(status_code=204)


@router.get("/me/checks")
def my_checks(request: Request, user: User = Depends(current_user)) -> list[dict[str, Any]]:
    return [summary(c) for c in store(request).list_checks(user.id)]


def _check(request: Request, user: User, check_id: str) -> Any:
    check = store(request).get_check(user.id, check_id)
    if check is None:
        raise HTTPException(404, "No such check.")
    return check


@router.get("/me/checks/{check_id}")
def my_check(request: Request, check_id: str, user: User = Depends(current_user)) -> dict[str, Any]:
    check = _check(request, user, check_id)
    previous = store(request).get_check(user.id, check.previous_id) if check.previous_id else None
    return full(check, previous)


@router.patch("/me/checks/{check_id}/steps/{step}")
def tick_step(request: Request, check_id: str, step: int, body: StepRequest,
              user: User = Depends(current_user)) -> dict[str, Any]:
    if not store(request).set_step(user.id, check_id, step, body.done):
        raise HTTPException(404, "No such step.")
    return summary(_check(request, user, check_id))


@router.delete("/me/checks/{check_id}", status_code=204)
def delete_check(request: Request, check_id: str, user: User = Depends(current_user)) -> Response:
    if not store(request).delete_check(user.id, check_id):
        raise HTTPException(404, "No such check.")
    return Response(status_code=204)


@router.get("/me/checks/{check_id}/audio/{step}")
def step_audio(request: Request, check_id: str, step: int, user: User = Depends(current_user)) -> FileResponse:
    check = _check(request, user, check_id)
    said = next((s for s in check.data.steps if s.index == step), None)
    if said is None:
        raise HTTPException(404, "No such step.")
    try:
        from clients.tts import TTSError, synthesize
    except ImportError as e:
        raise HTTPException(503, "Speech output is not available on this server.") from e
    try:
        speech = synthesize(said.speech, check.language)
    except TTSError as e:
        raise HTTPException(503, f"Speech output is not available: {e}") from e
    return FileResponse(speech.path, media_type="audio/wav", headers={"Cache-Control": "private, max-age=3600"})
