"""The single entry point for LLM calls (Muse Spark via Meta Model API or Baseten).

Both providers are OpenAI-compatible, so one `openai` client is pointed at the
configured base URL. Every call goes through the disk cache; errors are never cached.
Images must already be prepared (see `vision.images.encode_for_llm`).
"""

import base64
import logging
from functools import lru_cache
from typing import Any

from openai import OpenAI
from pydantic import BaseModel

from app.config import get_settings
from clients.cache import DiskCache, make_key

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 2 * 1024 * 1024


class LLMError(RuntimeError):
    pass


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMResponse(BaseModel):
    text: str
    provider: str
    model: str
    usage: TokenUsage
    cached: bool = False  # True when served from disk; usage then reflects the original call


@lru_cache
def _client(base_url: str, api_key: str) -> OpenAI:
    return OpenAI(base_url=base_url, api_key=api_key)


def _build_messages(
    prompt: str, system: str | None, image: bytes | None, image_mime: str
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    if image is None:
        messages.append({"role": "user", "content": prompt})
    else:
        data_url = f"data:{image_mime};base64,{base64.b64encode(image).decode('ascii')}"
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        )
    return messages


def complete(
    prompt: str,
    *,
    image: bytes | None = None,
    image_mime: str = "image/jpeg",
    system: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    response_format: dict[str, Any] | None = None,
) -> LLMResponse:
    """Send a text prompt, optionally with one prepared image, and return the reply."""
    if image is not None and len(image) > MAX_IMAGE_BYTES:
        raise ValueError(
            f"Image is {len(image)} bytes (limit {MAX_IMAGE_BYTES}); "
            "run it through vision.images.encode_for_llm first"
        )

    settings = get_settings()
    provider = settings.active_provider()
    cache = DiskCache(settings.cache_path)

    key = make_key(
        {
            "provider": provider.name,
            "model": provider.model,
            "system": system,
            "prompt": prompt,
            "image": image,
            "image_mime": image_mime,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": response_format,
        }
    )
    hit = cache.get(key)
    if hit is not None:
        logger.debug("LLM cache hit %s", key[:12])
        return LLMResponse.model_validate({**hit, "cached": True})

    params: dict[str, Any] = {
        "model": provider.model,
        "messages": _build_messages(prompt, system, image, image_mime),
        "temperature": temperature,
    }
    if max_tokens is not None:
        params["max_tokens"] = max_tokens
    if response_format is not None:
        params["response_format"] = response_format

    client = _client(provider.base_url, provider.api_key.get_secret_value())
    resp = client.chat.completions.create(**params)

    if not resp.choices:
        raise LLMError(f"No choices in response from {provider.name}/{provider.model}")
    choice = resp.choices[0]
    # Reasoning tokens count toward max_tokens; running out mid-reasoning gives
    # finish_reason="length" with content=None. Truncated output is never cached.
    if choice.finish_reason == "length":
        raise LLMError(
            f"{provider.name}/{provider.model} hit max_tokens={max_tokens} "
            f"(content {'empty' if choice.message.content is None else 'truncated'}); "
            "raise max_tokens"
        )
    if choice.message.content is None:
        raise LLMError(
            f"Empty response from {provider.name}/{provider.model} "
            f"(finish_reason={choice.finish_reason})"
        )

    usage = TokenUsage()
    if resp.usage is not None:
        usage = TokenUsage(
            prompt_tokens=resp.usage.prompt_tokens or 0,
            completion_tokens=resp.usage.completion_tokens or 0,
            total_tokens=resp.usage.total_tokens or 0,
        )
    result = LLMResponse(
        text=choice.message.content,
        provider=provider.name,
        model=provider.model,
        usage=usage,
    )
    cache.set(key, result.model_dump())
    logger.info(
        "LLM call %s/%s: %d prompt + %d completion tokens",
        provider.name,
        provider.model,
        usage.prompt_tokens,
        usage.completion_tokens,
    )
    return result
