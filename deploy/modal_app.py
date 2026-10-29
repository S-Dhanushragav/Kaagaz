"""Kaagaz backend on Modal: the FastAPI app as one ASGI container.

Deploy (from the repo root, with the `deploy` extra):
    modal secret create kaagaz-secrets META_API_KEY=... BASETEN_API_KEY=...     # once; keys never in code
    KAAGAZ_FRONTEND_ORIGIN=https://<site>.netlify.app modal deploy deploy/modal_app.py
Keep one container warm during judging (costs credits while it runs; off by default):
    KAAGAZ_KEEP_WARM=1 KAAGAZ_FRONTEND_ORIGIN=... modal deploy deploy/modal_app.py

- One container at most: sessions (paused graphs) live in memory, so every request must reach the same process.
- MMS-TTS models are downloaded while the image builds, not on the first request.
- The model-call disk cache lives on a Modal Volume, so the sample family stays cached across restarts.
- Non-secret settings come from .env.example (model IDs, limits); only the API keys come from the secret.
"""

import os
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
REMOTE = "/root/kaagaz"
TTS_MODELS = ("facebook/mms-tts-mar", "facebook/mms-tts-hin", "facebook/mms-tts-eng")
KEEP_WARM = int(os.environ.get("KAAGAZ_KEEP_WARM", "0"))
FRONTEND_ORIGIN = os.environ.get("KAAGAZ_FRONTEND_ORIGIN", "")


def _settings() -> dict[str, str]:
    """Non-empty, non-secret values from .env.example, with the server's own paths and origin."""
    out = {}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and not line.startswith("#") and value.strip() and not key.endswith("_API_KEY"):
            out[key.strip()] = value.strip()
    out.update({"CACHE_DIR": "/cache", "SESSIONS_DIR": "/tmp/kaagaz-sessions", "HF_HOME": "/models",
                "CORS_ORIGINS": FRONTEND_ORIGIN or out.get("CORS_ORIGINS", "")})
    return out


def _download_tts_models() -> None:
    from transformers import AutoTokenizer, VitsModel

    for model in TTS_MODELS:
        VitsModel.from_pretrained(model)
        AutoTokenizer.from_pretrained(model)


image = (
    modal.Image.debian_slim(python_version="3.13")
    .apt_install("ffmpeg")
    .pip_install("torch", index_url="https://download.pytorch.org/whl/cpu")
    .pip_install_from_pyproject(str(ROOT / "backend" / "pyproject.toml"), optional_dependencies=["tts"])
    .env(_settings())
    .run_function(_download_tts_models)
    .add_local_dir(ROOT / "backend", f"{REMOTE}/backend",
                   ignore=[".venv", "**/__pycache__", ".pytest_cache", "*.egg-info", "tests"])
    .add_local_dir(ROOT / "data", f"{REMOTE}/data")
    .add_local_file(ROOT / "synthetic" / "videos" / "HH009" / "sweep.mp4", f"{REMOTE}/synthetic/videos/HH009/sweep.mp4")
)

cache = modal.Volume.from_name("kaagaz-cache", create_if_missing=True)
app = modal.App("kaagaz", image=image)


@app.function(
    secrets=[modal.Secret.from_name("kaagaz-secrets")],
    volumes={"/cache": cache},
    cpu=4.0,
    memory=8192,
    timeout=900,
    min_containers=KEEP_WARM,
    max_containers=1,  # in-memory sessions: one process
    scaledown_window=1200,  # stay up 20 min after the last request, so open sessions survive a pause
)
@modal.concurrent(max_inputs=40)
@modal.asgi_app()
def web():
    import sys

    sys.path.insert(0, f"{REMOTE}/backend")
    from app.main import app as fastapi_app

    return fastapi_app
