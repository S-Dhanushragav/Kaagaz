import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.account import router as account_router
from app.api.routes import router
from app.auth import AuthService
from app.config import get_settings
from app.sessions import SessionManager
from storage import make_store


def _preload_tts() -> None:
    """Load the MMS-TTS models in the background at start-up, so the first question is not spoken late."""
    try:
        from clients.tts import TTSError, _load, model_id
    except ImportError:
        return
    for language in ("mr", "hi", "en"):
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
        app.state.auth = AuthService(app.state.store, s.phone_hash_key.get_secret_value(),
                                     s.token_signing_key.get_secret_value(), mode=s.auth_mode)
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


@app.get("/health")
def health() -> dict[str, object]:
    from app.config import REPO_ROOT

    s = get_settings()
    try:
        from clients.tts import _load

        tts_loaded = _load.cache_info().currsize
    except ImportError:
        tts_loaded = None
    return {
        "status": "ok",
        "providers": {"vision": s.vision_provider, "agent": s.agent_provider, "text": s.text_provider},
        "sample": (REPO_ROOT / s.sample_video).exists(),
        "tts_models_loaded": tts_loaded,  # None: the tts extra is not installed
    }
