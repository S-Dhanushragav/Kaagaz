"""Speech output: Meta MMS-TTS (VITS) for English, Hindi and Marathi, run locally on CPU.

Models come from TTS_MODEL_EN / TTS_MODEL_HI / TTS_MODEL_MR (facebook/mms-tts-eng, -hin, -mar; all
CC-BY-NC 4.0, non-commercial). Both Indic models read Devanagari directly (no uroman). Needs the optional
`tts` extra (torch, transformers). Input should be speech text (agents.speech.speech_text: numbers spelled
out). Output: 16-bit mono WAV at the model's rate (16 kHz), cached on disk by (model, text): the same
sentence is synthesized once. A fixed seed makes the output repeatable.
"""

import hashlib
import io
import logging
import re
import time
import wave
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel

from app.config import get_settings

logger = logging.getLogger(__name__)

Language = Literal["en", "hi", "mr"]
SEED = 0
PAUSE_S = 0.25  # silence between sentences
SENTENCE_END = re.compile(r"(?<=[.?!।])\s+")


class TTSError(RuntimeError):
    pass


class Speech(BaseModel):
    language: str
    text: str
    path: Path  # WAV file in the cache
    sample_rate: int
    seconds: float  # audio length
    synth_s: float  # time spent synthesizing (0 when cached)
    cached: bool


def model_id(language: Language) -> str:
    model = getattr(get_settings(), f"tts_model_{language}", "")
    if not model:
        raise TTSError(f"TTS_MODEL_{language.upper()} is not set")
    return model


@lru_cache
def _load(model: str) -> tuple[Any, Any]:
    try:
        import torch  # noqa: F401
        from transformers import AutoTokenizer, VitsModel
    except ImportError as e:
        raise TTSError('TTS needs the optional extra: pip install -e ".[tts]" '
                       "--extra-index-url https://download.pytorch.org/whl/cpu") from e
    logger.info("loading %s", model)
    return VitsModel.from_pretrained(model).eval(), AutoTokenizer.from_pretrained(model)


def _synthesize(model_name: str, text: str) -> tuple[np.ndarray, int]:
    import torch

    model, tokenizer = _load(model_name)
    rate = model.config.sampling_rate
    pause = np.zeros(int(rate * PAUSE_S), dtype=np.float32)
    parts: list[np.ndarray] = []
    for sentence in (s for s in SENTENCE_END.split(text.strip()) if s.strip()):
        inputs = tokenizer(sentence, return_tensors="pt")
        if inputs["input_ids"].shape[-1] == 0:
            continue  # nothing the model can say (e.g. only punctuation)
        torch.manual_seed(SEED)
        with torch.no_grad():
            parts += [model(**inputs).waveform[0].numpy(), pause]
    if not parts:
        raise TTSError(f"nothing to say in {text!r}")
    return np.concatenate(parts[:-1]), rate


def wav_bytes(samples: np.ndarray, rate: int) -> bytes:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def synthesize(text: str, language: Language) -> Speech:
    """Speak `text` (already speech text) in `language`; returns the cached WAV."""
    model = model_id(language)
    key = hashlib.sha256(f"{model}\n{text}".encode("utf-8")).hexdigest()
    path = get_settings().cache_path / "tts" / f"{key}.wav"
    if path.exists():
        with wave.open(str(path), "rb") as w:
            rate, frames = w.getframerate(), w.getnframes()
        return Speech(language=language, text=text, path=path, sample_rate=rate, seconds=frames / rate, synth_s=0.0,
                      cached=True)
    start = time.perf_counter()
    samples, rate = _synthesize(model, text)
    elapsed = time.perf_counter() - start
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(wav_bytes(samples, rate))
    tmp.replace(path)
    logger.info("TTS [%s] %.1f s of audio in %.1f s", language, len(samples) / rate, elapsed)
    return Speech(language=language, text=text, path=path, sample_rate=rate, seconds=len(samples) / rate,
                  synth_s=elapsed, cached=False)
