"""Phone login: normalization, hashed numbers, code expiry and attempts, rate limits per number and per IP, signed
tokens (forged, expired, deleted user), demo vs sms mode, and the HTTP routes with a Bearer header."""

import pytest
from fastapi.testclient import TestClient

from app.auth import (CODE_TTL_S, MAX_ATTEMPTS, STARTS_PER_IP, TOKEN_TTL_S, AuthError, AuthService, normalize_phone,
                      phone_hash)
from storage.store import MemoryStore

PHONE = "+91 98765 43210"


class Clock:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


def _auth(**kw) -> tuple[AuthService, MemoryStore, Clock]:
    store, clock = MemoryStore(), Clock()
    return AuthService(store, "phone-key", "token-key", clock=clock, **kw), store, clock


@pytest.mark.parametrize("raw", ["9876543210", "+91 98765 43210", "098765-43210", "91 9876543210"])
def test_numbers_are_normalized(raw: str) -> None:
    assert normalize_phone(raw) == "9876543210"


@pytest.mark.parametrize("raw", ["", "12345", "5876543210", "98765432101", "abc"])
def test_bad_numbers_are_rejected(raw: str) -> None:
    with pytest.raises(AuthError) as e:
        normalize_phone(raw)
    assert e.value.status == 422


def test_demo_login_stores_only_a_hash_and_last4() -> None:
    auth, store, _ = _auth()
    started = auth.start(PHONE, "1.2.3.4")
    assert started["sent"] and len(started["demo_code"]) == 6
    token, user = auth.verify("9876543210", started["demo_code"], "hi")
    assert user.phone_hash == phone_hash("9876543210", "phone-key") and user.phone_last4 == "3210"
    assert "9876543210" not in repr(store.users) and user.language == "hi"
    assert auth.user_for(token).id == user.id
    again = auth.start(PHONE, "1.2.3.4")["demo_code"]
    assert auth.verify(PHONE, again)[1].id == user.id  # the same number logs into the same user
    with pytest.raises(AuthError) as e:
        auth.verify(PHONE, again)  # a code works once
    assert e.value.status == 410


def test_codes_expire_after_ten_minutes() -> None:
    auth, _, clock = _auth()
    code = auth.start(PHONE, "ip")["demo_code"]
    clock.t += CODE_TTL_S + 1
    with pytest.raises(AuthError) as e:
        auth.verify(PHONE, code)
    assert e.value.status == 410


def test_five_wrong_codes_end_the_attempt() -> None:
    auth, _, _ = _auth()
    code = auth.start(PHONE, "ip")["demo_code"]
    wrong = "000000" if code != "000000" else "111111"
    for left in range(MAX_ATTEMPTS - 1, 0, -1):
        with pytest.raises(AuthError) as e:
            auth.verify(PHONE, wrong)
        assert e.value.status == 401 and e.value.extra["attempts_left"] == left
    with pytest.raises(AuthError) as e:
        auth.verify(PHONE, wrong)
    assert e.value.status == 429
    with pytest.raises(AuthError) as e:
        auth.verify(PHONE, code)  # even the right code is gone now
    assert e.value.status == 410


def test_rate_limits_per_number_and_per_ip() -> None:
    auth, _, clock = _auth()
    for _ in range(3):
        auth.start(PHONE, "ip-a")
    with pytest.raises(AuthError) as e:
        auth.start(PHONE, "ip-b")  # the same number from another IP
    assert e.value.status == 429
    clock.t += 601
    auth.start(PHONE, "ip-a")  # ten minutes later
    for i in range(STARTS_PER_IP[0]):
        auth.start(f"90000000{i:02d}", "ip-c")
    with pytest.raises(AuthError) as e:
        auth.start("9666666666", "ip-c")  # one more number from the same IP within the hour
    assert e.value.status == 429


def test_tokens_forged_expired_or_for_a_deleted_user_are_refused() -> None:
    auth, store, clock = _auth()
    token, user = auth.verify(PHONE, auth.start(PHONE, "ip")["demo_code"])
    body, sig = token.split(".")
    assert auth.user_for(f"{body}.{sig[:-2]}xx") is None  # forged signature
    other = AuthService(store, "phone-key", "another-key", clock=clock)
    assert other.user_for(token) is None  # signed with another key
    assert auth.user_for("garbage") is None and auth.user_for(None) is None
    clock.t += TOKEN_TTL_S + 1
    assert auth.user_for(token) is None  # expired
    fresh = auth.issue(user.id)
    store.delete_user(user.id)
    assert auth.user_for(fresh) is None  # deleted


def test_sms_mode_without_a_provider_and_missing_keys() -> None:
    auth, _, _ = _auth(mode="sms")
    with pytest.raises(AuthError) as e:
        auth.start(PHONE, "ip")
    assert e.value.status == 503
    sent = []
    auth, _, _ = _auth(mode="sms", sender=type("S", (), {"send": lambda self, n, t: sent.append((n, t))})())
    assert auth.start(PHONE, "ip")["demo_code"] is None and sent[0][0] == "9876543210"
    with pytest.raises(AuthError) as e:
        AuthService(MemoryStore(), "", "").start(PHONE, "ip")
    assert e.value.status == 503


def test_routes_with_a_bearer_header(monkeypatch) -> None:
    from app.main import app

    auth, _, _ = _auth()
    monkeypatch.setattr(app.state, "auth", auth, raising=False)
    client = TestClient(app)
    code = client.post("/auth/start", json={"phone": PHONE}).json()["demo_code"]
    bad = client.post("/auth/verify", json={"phone": PHONE, "code": "x"})
    assert bad.status_code == 401 and bad.json()["detail"]["attempts_left"] == MAX_ATTEMPTS - 1
    token = client.post("/auth/verify", json={"phone": PHONE, "code": code, "language": "en"}).json()["token"]
    me = client.get("/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["phone_last4"] == "3210" and me["language"] == "en" and "phone_hash" not in me
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers={"Authorization": "Bearer nope"}).status_code == 401
    pre = client.options("/me", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "DELETE",
                                         "Access-Control-Request-Headers": "authorization"})
    assert pre.status_code == 200 and "DELETE" in pre.headers["access-control-allow-methods"]


def test_a_spoofed_first_forwarded_entry_does_not_bypass_the_ip_limit(monkeypatch) -> None:
    """The client can put anything first in X-Forwarded-For; Modal's proxy appends the real address last."""
    from app.main import app

    auth, _, _ = _auth()
    monkeypatch.setattr(app.state, "auth", auth, raising=False)
    client = TestClient(app)
    limit = STARTS_PER_IP[0]
    for i in range(limit):
        spoofed = {"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.7"}  # a new fake first entry every time
        assert client.post("/auth/start", json={"phone": f"90000000{i:02d}"}, headers=spoofed).status_code == 200
    blocked = client.post("/auth/start", json={"phone": "9666666666"}, headers={"X-Forwarded-For": "10.9.9.9, 203.0.113.7"})
    assert blocked.status_code == 429
    other = client.post("/auth/start", json={"phone": "9666666666"}, headers={"X-Forwarded-For": "203.0.113.8"})
    assert other.status_code == 200  # another real address is not affected
