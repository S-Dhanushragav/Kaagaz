"""Login and the family's case file (Phase 9).

POST /auth/start   {phone}               a one-time code (demo mode: returned in the reply; sms mode: sent by SMS)
POST /auth/verify  {phone, code, language} -> {token, user}; send the token as `Authorization: Bearer <token>`
GET  /me                                   the logged-in user (phone shown only as its last 4 digits)
"""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import AuthError, AuthService
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
