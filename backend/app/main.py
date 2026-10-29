import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import get_settings
from app.sessions import SessionManager


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not hasattr(app.state, "sessions"):  # tests set their own
        app.state.sessions = SessionManager()
    app.state.sessions.start_cleanup_loop()
    threading.Thread(target=_preload_tts, daemon=True, name="tts-preload").start()
    yield


app = FastAPI(title="Kaagaz", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.include_router(router)


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
