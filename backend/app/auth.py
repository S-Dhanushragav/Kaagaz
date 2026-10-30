"""Phone login with a one-time code, and signed tokens.

- A phone number is normalized to 10 digits and stored only as HMAC-SHA256(PHONE_HASH_KEY, number), plus its last
  4 digits for display. The raw number is never stored or logged.
- POST /auth/start makes a 6-digit code (in memory only, 10 minutes, 5 attempts) and sends it with an SmsSender.
  AUTH_MODE=demo sends nothing and returns the code so the app can show it; AUTH_MODE=sms needs a real sender
  (none yet: start fails with 503). Rate-limited per number and per IP.
- POST /auth/verify returns a token: base64url(JSON {u: user id, exp}) "." base64url(HMAC-SHA256(TOKEN_SIGNING_KEY)),
  valid 30 days, sent back as `Authorization: Bearer <token>` (the app and API are on different domains: no cookies).
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

from storage.models import User
from storage.store import Store

CODE_TTL_S = 600
MAX_ATTEMPTS = 5
TOKEN_TTL_S = 30 * 24 * 3600
STARTS_PER_NUMBER = (3, 600)  # at most 3 codes per number per 10 minutes
STARTS_PER_IP = (30, 3600)  # at most 30 codes per IP per hour (a shared phone or office network)


class AuthError(Exception):
    def __init__(self, status: int, message: str, **extra: object) -> None:
        super().__init__(message)
        self.status, self.message, self.extra = status, message, extra


MIN_KEY_BYTES = 32
# Only for KAAGAZ_ENV=local / test: clearly not a secret, never accepted in production.
DEV_PHONE_KEY = "dev-only-insecure-phone-hash-key-local-runs-only"
DEV_TOKEN_KEY = "dev-only-insecure-token-signing-key-local-runs-only"


def auth_keys(env: str, phone_key: str, token_key: str) -> tuple[str, str]:
    """The keys to use. Outside local and test runs, both must be set and at least 32 bytes long, or the app
    refuses to start: there is no default in production."""
    if env in ("local", "test"):
        return phone_key or DEV_PHONE_KEY, token_key or DEV_TOKEN_KEY
    problems = [name for name, key in (("PHONE_HASH_KEY", phone_key), ("TOKEN_SIGNING_KEY", token_key))
                if len(key.encode()) < MIN_KEY_BYTES]
    if problems:
        raise RuntimeError(f"{' and '.join(problems)} must be set and at least {MIN_KEY_BYTES} bytes long "
                           f"(KAAGAZ_ENV={env}). Set KAAGAZ_ENV=local for a local run with development keys.")
    return phone_key, token_key


def normalize_phone(raw: str) -> str:
    """An Indian mobile number as 10 digits: '+91 98765-43210', '098765 43210' and '9876543210' are the same."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if not re.fullmatch(r"[6-9]\d{9}", digits):
        raise AuthError(422, "Please enter a 10-digit mobile number.")
    return digits


def phone_hash(number: str, key: str) -> str:
    return hmac.new(key.encode(), number.encode(), hashlib.sha256).hexdigest()


class SmsSender(Protocol):
    def send(self, number: str, text: str) -> None: ...


class DemoSender:
    """AUTH_MODE=demo: nothing is sent; the code goes back to the app."""

    def send(self, number: str, text: str) -> None:
        pass


class NoSmsProvider:
    """AUTH_MODE=sms before a provider is configured."""

    def send(self, number: str, text: str) -> None:
        raise AuthError(503, "SMS is not available yet. Please use the demo or continue as a guest.")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass
class _Pending:
    code: str
    expires: float
    attempts_left: int
    last4: str


@dataclass
class AuthService:
    store: Store
    phone_key: str
    token_key: str
    mode: str = "demo"
    sender: SmsSender | None = None
    clock: Callable[[], float] = time.time
    _pending: dict[str, _Pending] = field(default_factory=dict)  # phone hash -> code
    _starts: dict[str, list[float]] = field(default_factory=dict)  # 'n:<hash>' / 'ip:<ip>' -> start times
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        if self.sender is None:
            self.sender = DemoSender() if self.mode == "demo" else NoSmsProvider()

    def _ready(self) -> None:
        if not (self.phone_key and self.token_key):
            raise AuthError(503, "Login is not configured on this server. Please continue as a guest.")

    def _limit(self, key: str, rule: tuple[int, int]) -> None:
        limit, window = rule
        now = self.clock()
        recent = [t for t in self._starts.get(key, []) if now - t < window]
        if len(recent) >= limit:
            raise AuthError(429, "Too many codes requested. Please wait a few minutes.")
        self._starts[key] = recent + [now]

    def start(self, phone: str, ip: str) -> dict[str, object]:
        self._ready()
        number = normalize_phone(phone)
        h = phone_hash(number, self.phone_key)
        with self._lock:
            self._limit(f"ip:{ip}", STARTS_PER_IP)
            self._limit(f"n:{h}", STARTS_PER_NUMBER)
            code = f"{secrets.randbelow(10**6):06d}"
            self._pending[h] = _Pending(code=code, expires=self.clock() + CODE_TTL_S, attempts_left=MAX_ATTEMPTS,
                                        last4=number[-4:])
        assert self.sender is not None
        self.sender.send(number, f"Kaagaz code: {code}. It expires in 10 minutes.")
        return {"sent": True, "expires_in": CODE_TTL_S, "demo_code": code if self.mode == "demo" else None}

    def verify(self, phone: str, code: str, language: str = "mr") -> tuple[str, User]:
        self._ready()
        h = phone_hash(normalize_phone(phone), self.phone_key)
        with self._lock:
            p = self._pending.get(h)
            if p is None or self.clock() > p.expires:
                self._pending.pop(h, None)
                raise AuthError(410, "This code has expired. Please ask for a new one.")
            if not hmac.compare_digest(p.code, (code or "").strip()):
                p.attempts_left -= 1
                if p.attempts_left <= 0:
                    del self._pending[h]
                    raise AuthError(429, "Too many wrong codes. Please ask for a new one.")
                raise AuthError(401, "That code is not right.", attempts_left=p.attempts_left)
            last4 = p.last4
        # The code is used up only once the user is found or created: if the database is down (StoreUnavailable,
        # a friendly 503), the same code works again a moment later.
        user = self.store.user_by_phone_hash(h) or self.store.create_user(h, last4, language)
        with self._lock:
            self._pending.pop(h, None)
        return self.issue(user.id), user

    # ---------- tokens ----------

    def issue(self, user_id: str) -> str:
        body = _b64(json.dumps({"u": user_id, "exp": int(self.clock()) + TOKEN_TTL_S}, separators=(",", ":")).encode())
        sig = _b64(hmac.new(self.token_key.encode(), body.encode(), hashlib.sha256).digest())
        return f"{body}.{sig}"

    def user_for(self, token: str | None) -> User | None:
        """The user a token belongs to; None if it is missing, forged, expired, or the user was deleted."""
        if not token or not self.token_key or token.count(".") != 1:
            return None
        body, sig = token.split(".")
        good = _b64(hmac.new(self.token_key.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            return None
        try:
            claims = json.loads(_unb64(body))
        except (ValueError, json.JSONDecodeError):
            return None
        if not isinstance(claims, dict) or claims.get("exp", 0) < self.clock():
            return None
        return self.store.get_user(str(claims.get("u")))
