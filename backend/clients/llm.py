"""The single entry point for LLM calls (Muse Spark via Meta Model API, Muse Spark Open via Baseten).

Both providers are OpenAI-compatible, so Chat Completions is called through one `openai`
client pointed at the base URL resolved for the task. Every call goes through the disk
cache; errors and truncated replies are never cached.
Images must already be prepared (see `vision.images.encode_for_llm`).
"""

import base64
import logging
from functools import lru_cache
from typing import Any

from openai import BadRequestError, OpenAI, UnprocessableEntityError
from pydantic import BaseModel

from app.config import Task, get_settings
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
    reasoning: str | None = None  # reasoning_content, when the provider returns it
    task: Task
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


def _reasoning_text(message: Any) -> str | None:
    extra = message.model_extra or {}
    for field in ("reasoning_content", "reasoning"):
        value = extra.get(field)
        if isinstance(value, str) and value:
            return value
    return None


def complete(
    prompt: str,
    *,
    task: Task,
    image: bytes | None = None,
    image_mime: str = "image/jpeg",
    system: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    response_format: dict[str, Any] | None = None,
) -> LLMResponse:
    """Send a prompt (plus optional prepared image) using the model configured for `task`.

    `max_tokens` overrides the task's configured budget; it includes reasoning tokens.
    """
    if image is not None and task == "text":
        raise ValueError("task='text' does not take an image; use task='vision'")
    if image is not None and len(image) > MAX_IMAGE_BYTES:
        raise ValueError(
            f"Image is {len(image)} bytes (limit {MAX_IMAGE_BYTES}); "
            "run it through vision.images.encode_for_llm first"
        )

    settings = get_settings()
    resolved = settings.resolve(task)
    if max_tokens is None:
        max_tokens = resolved.max_tokens
    cache = DiskCache(settings.cache_path)

    key = make_key(
        {
            "task": task,
            "provider": resolved.provider,
            "model": resolved.model,
            "reasoning_effort": resolved.reasoning_effort,
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
        "model": resolved.model,
        "messages": _build_messages(prompt, system, image, image_mime),
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if resolved.reasoning_effort is not None:
        params["reasoning_effort"] = resolved.reasoning_effort
    if response_format is not None:
        params["response_format"] = response_format

    label = f"{resolved.provider}/{resolved.model}"
    client = _client(resolved.base_url, resolved.api_key.get_secret_value())
    try:
        resp = client.chat.completions.create(**params)
    except (BadRequestError, UnprocessableEntityError) as e:
        if resolved.reasoning_effort is not None and "reasoning" in str(e).lower():
            raise LLMError(
                f"Provider '{resolved.provider}' rejected parameter "
                f"reasoning_effort={resolved.reasoning_effort!r} for model {resolved.model}; "
                f"fix or unset {task.upper()}_REASONING_EFFORT. Provider said: {e}"
            ) from e
        raise

    if not resp.choices:
        raise LLMError(f"No choices in response from {label}")
    choice = resp.choices[0]
    # Reasoning tokens count toward max_tokens; running out mid-reasoning gives
    # finish_reason="length" with content=None. Truncated output is never cached.
    if choice.finish_reason == "length":
        raise LLMError(
            f"{label} hit max_tokens={max_tokens} "
            f"(content {'empty' if choice.message.content is None else 'truncated'}); "
            f"raise {task.upper()}_MAX_TOKENS"
        )
    if choice.message.content is None:
        raise LLMError(f"Empty response from {label} (finish_reason={choice.finish_reason})")

    usage = TokenUsage()
    if resp.usage is not None:
        usage = TokenUsage(
            prompt_tokens=resp.usage.prompt_tokens or 0,
            completion_tokens=resp.usage.completion_tokens or 0,
            total_tokens=resp.usage.total_tokens or 0,
        )
    result = LLMResponse(
        text=choice.message.content,
        reasoning=_reasoning_text(choice.message),
        task=task,
        provider=resolved.provider,
        model=resolved.model,
        usage=usage,
    )
    cache.set(key, result.model_dump())
    logger.info(
        "LLM call [%s] %s: %d prompt + %d completion tokens",
        task,
        label,
        usage.prompt_tokens,
        usage.completion_tokens,
    )
    return result
