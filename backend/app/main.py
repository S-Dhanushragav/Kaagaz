import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.account import router as account_router
from app.api.ask import AskService, router as ask_router
from app.api.routes import router
from app.auth import AuthService, auth_keys
from schemas.languages import LANGUAGES
from app.config import get_settings
from app.sessions import SessionManager
from storage import make_store
from storage.store import StoreUnavailable


def _preload_tts() -> None:
    """Load the MMS-TTS models in the background at start-up, so the first question is not spoken late."""
    try:
        from clients.tts import TTSError, _load, model_id
    except ImportError:
        return
    for language in LANGUAGES:
        try:
            _load(model_id(language))
        except (TTSError, OSError) as e:
            logging.getLogger(__name__).warning("TTS preload failed for %s: %s", language, e)


def _purge_loop(store, every_s: int = 6 * 3600) -> None:
    """Delete stored checks older than the retention limit, at start-up and then every few hours."""
    while True:
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=get_settings().check_retention_days)
            store.purge_checks(cutoff)
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("retention purge failed")
        time.sleep(every_s)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not hasattr(app.state, "store"):  # tests set their own
        app.state.store = make_store(get_settings().database_url.get_secret_value())
        app.state.store.init()
    if not hasattr(app.state, "auth"):
        s = get_settings()
        phone_key, token_key = auth_keys(s.kaagaz_env, s.phone_hash_key.get_secret_value(),
                                         s.token_signing_key.get_secret_value())  # refuses to start without keys
        app.state.auth = AuthService(app.state.store, phone_key, token_key, mode=s.auth_mode)
    if not hasattr(app.state, "ask"):
        app.state.ask = AskService()
    if not hasattr(app.state, "sessions"):
        app.state.sessions = SessionManager(store=app.state.store)
    app.state.sessions.start_cleanup_loop()
    threading.Thread(target=_purge_loop, args=(app.state.store,), daemon=True, name="retention").start()
    threading.Thread(target=_preload_tts, daemon=True, name="tts-preload").start()
    yield


app = FastAPI(title="Kaagaz", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)
app.include_router(router)
app.include_router(account_router)
app.include_router(ask_router)


@app.exception_handler(StoreUnavailable)
def store_unavailable(request: Request, exc: StoreUnavailable) -> JSONResponse:
    """The case-file database is down: login, saving and the case file say so; guest checks are unaffected."""
    return JSONResponse(status_code=503, content={"detail": "Saved checks are not available right now. "
                                                            "Your check still works without logging in."})


@app.get("/health")
def health(request: Request) -> dict[str, object]:
    from app.config import REPO_ROOT
    from app.sessions import SessionManager
    from clients import budget

    s = get_settings()
    try:
        from clients.tts import _load

        tts_loaded = _load.cache_info().currsize
    except ImportError:
        tts_loaded = None
    return {
        "status": "ok",
        "providers": {"vision": s.vision_provider, "agent": s.agent_provider, "text": s.text_provider},
        "sample": bool(SessionManager.sample_photos()),  # the sample family's photos
        "sample_video": (REPO_ROOT / s.sample_video).exists(),  # the sweep video, for testing
        "load": sessions.load() if (sessions := getattr(request.app.state, "sessions", None)) else None,
        # Which secrets are set (never their values): the freeze check compares them with what production needs.
        "configured": {name: bool(getattr(s, name).get_secret_value()) for name in
                       ("meta_api_key", "baseten_api_key", "database_url", "phone_hash_key", "token_signing_key")},
        "auth_mode": s.auth_mode,
        # Non-secret settings the freeze check compares with .env.example (scripts/freeze_check.py).
        "settings": {"META_VISION_MODEL": s.meta_vision_model, "META_AGENT_MODEL": s.meta_agent_model,
                     "BASETEN_MODEL": s.baseten_model, "META_SEGMENT_MODEL": s.meta_segment_model,
                     "META_TRANSCRIBE_MODEL": s.meta_transcribe_model, "ASK_PROVIDER": s.ask_provider,
                     "SAMPLE_PHOTOS": s.sample_photos, "MAX_RUNNING_CHECKS": str(s.max_running_checks),
                     "BASETEN_DAILY_TOKENS": str(s.baseten_daily_tokens), "AUTH_MODE": s.auth_mode},
        "tts_models_loaded": tts_loaded,  # None: the tts extra is not installed
        "baseten_budget": budget.status(),  # today's tokens, refusals and fallbacks to Muse Spark (counts only)
    }
