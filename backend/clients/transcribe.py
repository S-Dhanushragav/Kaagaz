"""Speech input: Muse Voice Transcribe, file endpoint (POST {META_BASE_URL}/asr/transcribe).

Multipart request: a `request` JSON part (model, audioEncoding WAV, mode PUSH_TO_TALK, languageBias,
keywords) and an `audio` part (mono 16-bit PCM WAV at 16 or 24 kHz). Sent with the standard library
(no extra HTTP dependency). Every call goes through the disk cache, keyed by the settings and the audio.
`keywords` bias recognition toward expected words (e.g. the option numbers) but don't guarantee spelling.
"""

import io
import json
import logging
import time
import urllib.error
import urllib.request
import uuid
import wave
from typing import Literal

from pydantic import BaseModel

from app.config import get_settings
from clients.cache import DiskCache, make_key

logger = logging.getLogger(__name__)

Language = Literal["en", "hi", "mr"]
LANGUAGE_NAMES = {"en": "English", "hi": "Hindi", "mr": "Marathi"}  # the API biases on English language names
RATES = (16000, 24000)
# Interactive (the family is waiting): 10 s timeout, one retry, then the caller shows buttons.
INTERACTIVE_TIMEOUT_S, INTERACTIVE_RETRIES, INTERACTIVE_BACKOFF_S = 10.0, 1, 0.5
# Evals only: patient settings.
EVAL_SETTINGS = {"timeout_s": 120.0, "retries": 3, "backoff_s": 2.0}


class TranscribeError(RuntimeError):
    pass


class Transcript(BaseModel):
    text: str
    audio_ms: int
    request_s: float  # time for the API call (0 when cached)
    cached: bool = False


def check_wav(audio: bytes) -> None:
    try:
        with wave.open(io.BytesIO(audio), "rb") as w:
            channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
    except (wave.Error, EOFError) as e:
        raise TranscribeError(f"not a WAV file: {e}") from e
    if channels != 1 or width != 2 or rate not in RATES:
        raise TranscribeError(f"WAV must be mono 16-bit PCM at 16 or 24 kHz (got {channels} ch, {8 * width}-bit, {rate} Hz)")


def _multipart(request: dict, audio: bytes) -> tuple[bytes, str]:
    boundary = f"kaagaz-{uuid.uuid4().hex}"
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="request"\r\nContent-Type: application/json\r\n\r\n'.encode()
        + json.dumps(request, ensure_ascii=False).encode("utf-8") + b"\r\n",
        f'--{boundary}\r\nContent-Disposition: form-data; name="audio"; filename="audio.wav"\r\n'
        "Content-Type: audio/wav\r\n\r\n".encode() + audio + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _post(url: str, body: bytes, content_type: str, api_key: str, timeout_s: float = INTERACTIVE_TIMEOUT_S,
          retries: int = INTERACTIVE_RETRIES, backoff_s: float = INTERACTIVE_BACKOFF_S) -> dict:
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": content_type, "Accept": "application/json"})
    for attempt in range(retries + 1):
        last = attempt == retries
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code in (429, 500, 503) and not last:
                time.sleep(backoff_s * 2 ** attempt)
                continue
            raise TranscribeError(f"transcribe failed: HTTP {e.code}: {detail}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            if not last:
                time.sleep(backoff_s * 2 ** attempt)
                continue
            raise TranscribeError(f"transcribe failed: {getattr(e, 'reason', e)}") from e
    raise TranscribeError("transcribe failed")  # unreachable


def transcribe(audio: bytes, language: Language | None = None, keywords: list[str] | None = None, *,
               timeout_s: float = INTERACTIVE_TIMEOUT_S, retries: int = INTERACTIVE_RETRIES,
               backoff_s: float = INTERACTIVE_BACKOFF_S) -> Transcript:
    """Transcribe one WAV clip. `language` biases recognition (omit to auto-detect). Defaults are the
    interactive settings (10 s timeout, one retry); evals pass EVAL_SETTINGS."""
    settings = get_settings()
    if not settings.meta_transcribe_model or not settings.meta_base_url:
        raise TranscribeError("META_TRANSCRIBE_MODEL and META_BASE_URL must be set")
    check_wav(audio)
    request: dict = {"model": settings.meta_transcribe_model, "audioEncoding": "WAV", "mode": "PUSH_TO_TALK"}
    if language:
        request["languageBias"] = [LANGUAGE_NAMES[language]]
    if keywords:
        request["keywords"] = list(dict.fromkeys(keywords))
    cache = DiskCache(settings.cache_path)
    key = make_key({"kind": "asr", "url": settings.meta_base_url, "request": request, "audio": audio})
    hit = cache.get(key)
    if hit is not None:
        return Transcript.model_validate({**hit, "cached": True})

    body, content_type = _multipart(request, audio)
    start = time.perf_counter()
    reply = _post(f"{settings.meta_base_url.rstrip('/')}/asr/transcribe", body, content_type,
                  settings.meta_api_key.get_secret_value(), timeout_s=timeout_s, retries=retries, backoff_s=backoff_s)
    elapsed = time.perf_counter() - start
    result = Transcript(text=(reply.get("transcript") or "").strip(), audio_ms=int(reply.get("audioDurationMs") or 0),
                        request_s=round(elapsed, 3))
    cache.set(key, result.model_dump())
    logger.info("transcribe [%s] %d ms audio in %.1f s", language or "auto", result.audio_ms, elapsed)
    return result
