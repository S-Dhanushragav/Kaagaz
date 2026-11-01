"""The single entry point for LLM calls (Muse Spark via Meta Model API, Muse Spark Open via Baseten).

Both providers are OpenAI-compatible, so Chat Completions is called through one `openai`
client pointed at the base URL resolved for the task. Every call goes through the disk
cache; errors and truncated replies are never cached.
Images must already be prepared (see `vision.images.encode_for_llm`).
"""

import base64
import json
import logging
import re
from functools import lru_cache
from typing import Any, Callable, Mapping, Sequence

from openai import APIError, BadRequestError, OpenAI, UnprocessableEntityError
from pydantic import BaseModel

from app.config import ResolvedModel, Settings, Task, get_settings
from clients import budget
from clients.cache import DiskCache, make_key

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_IMAGES = 3


class LLMError(RuntimeError):
    pass


class EmptyResponse(LLMError):
    """The model returned neither text nor tool calls."""


class BudgetExhausted(LLMError):
    """Today's Baseten token budget is used up and this task has no fallback (clients/budget.py)."""


def _fallback(settings: Settings, task: Task, overrides: Mapping[str, Any] | None,
              resolved: ResolvedModel) -> dict[str, Any] | None:
    """Overrides that send a Baseten call to Muse Spark instead, if this task may fall back (else None)."""
    if resolved.provider != "baseten" or task not in settings.fallback_tasks:
        return None
    model = getattr(settings, f"meta_{task}_model", "")
    if not (model and settings.meta_base_url and settings.meta_api_key.get_secret_value()):
        return None
    return {**(overrides or {}), "provider": "meta", "model": model}


def _before_baseten(settings: Settings, task: Task, overrides: Mapping[str, Any] | None,
                    resolved: ResolvedModel) -> dict[str, Any] | None:
    """Called before a Baseten request (not for cache hits): fallback overrides if today's budget is used up.
    Raises BudgetExhausted when it is used up and the task cannot fall back."""
    if resolved.provider != "baseten" or not budget.exhausted():
        return None
    fallback = _fallback(settings, task, overrides, resolved)
    if fallback is None:
        budget.refused(task)
        raise BudgetExhausted(f"Baseten daily token budget ({settings.baseten_daily_tokens}) is used up")
    budget.fallback(task, "budget")
    return fallback


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
    prompt: str, system: str | None, images: Sequence[bytes], image_mime: str
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    if not images:
        messages.append({"role": "user", "content": prompt})
    else:
        content: list[dict[str, Any]] = [
            {
                "type": "image_url",
                "image_url": {"url": f"data:{image_mime};base64,{base64.b64encode(img).decode('ascii')}"},
            }
            for img in images
        ]
        content.append({"type": "text", "text": prompt})
        messages.append({"role": "user", "content": content})
    return messages


def _reasoning_text(message: Any) -> str | None:
    extra = message.model_extra or {}
    for field in ("reasoning_content", "reasoning"):
        value = extra.get(field)
        if isinstance(value, str) and value:
            return value
    return None


def cache_key(
    resolved: ResolvedModel,
    *,
    prompt: str,
    images: Sequence[bytes],
    image_mime: str,
    system: str | None,
    temperature: float,
    max_tokens: int,
    response_format: dict[str, Any] | None,
) -> str:
    """Cache key from the *resolved* call settings, so overrides never share a cached reply."""
    return make_key(
        {
            "task": resolved.task,
            "provider": resolved.provider,
            "model": resolved.model,
            "reasoning_effort": resolved.reasoning_effort,
            "system": system,
            "prompt": prompt,
            "images": list(images),
            "image_mime": image_mime,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": response_format,
        }
    )


def complete(
    prompt: str,
    *,
    task: Task,
    images: Sequence[bytes] = (),
    image_mime: str = "image/jpeg",
    system: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    response_format: dict[str, Any] | None = None,
    overrides: Mapping[str, Any] | None = None,
    redact: Callable[[str], str] | None = None,
) -> LLMResponse:
    """Send a prompt (plus up to 3 prepared images of one document) using the model for `task`.

    `max_tokens` overrides the task's configured budget; it includes reasoning tokens.
    `overrides` is passed to `Settings.resolve` (provider/model/reasoning_effort/max_tokens).
    `redact` is applied to the reply and reasoning *before* caching and returning, so sensitive
    values (e.g. identity numbers) never reach disk or callers.
    """
    if images and task == "text":
        raise ValueError("task='text' does not take images; use task='vision'")
    if len(images) > MAX_IMAGES:
        raise ValueError(f"At most {MAX_IMAGES} images per call, got {len(images)}")
    for img in images:
        if len(img) > MAX_IMAGE_BYTES:
            raise ValueError(
                f"Image is {len(img)} bytes (limit {MAX_IMAGE_BYTES}); "
                "run it through vision.images.encode_for_llm first"
            )

    settings = get_settings()
    resolved = settings.resolve(task, overrides)
    if max_tokens is None:
        max_tokens = resolved.max_tokens
    cache = DiskCache(settings.cache_path)

    key = cache_key(
        resolved,
        prompt=prompt,
        images=images,
        image_mime=image_mime,
        system=system,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format=response_format,
    )
    hit = cache.get(key)
    if hit is not None:
        logger.debug("LLM cache hit %s", key[:12])
        return LLMResponse.model_validate({**hit, "cached": True})

    call = dict(prompt=prompt, task=task, images=images, image_mime=image_mime, system=system, temperature=temperature,
                max_tokens=max_tokens, response_format=response_format, redact=redact)
    switch = _before_baseten(settings, task, overrides, resolved)
    if switch is not None:
        return complete(**call, overrides=switch)
    try:
        result = _complete_call(resolved, task, cache, key, prompt, images, image_mime, system, temperature, max_tokens,
                                response_format, redact)
    except (LLMError, APIError):
        fallback = _fallback(settings, task, overrides, resolved)
        if fallback is None:
            raise
        budget.fallback(task, "error")
        return complete(**call, overrides=fallback)
    return result


def _complete_call(resolved: ResolvedModel, task: Task, cache: DiskCache, key: str, prompt: str, images: Sequence[bytes],
                   image_mime: str, system: str | None, temperature: float, max_tokens: int,
                   response_format: dict[str, Any] | None, redact: Callable[[str], str] | None) -> LLMResponse:
    params: dict[str, Any] = {
        "model": resolved.model,
        "messages": _build_messages(prompt, system, images, image_mime),
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
    if resolved.provider == "baseten" and resp.usage is not None:
        budget.add(resp.usage.total_tokens or 0)  # counted whether or not the reply is usable
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
    text, reasoning = choice.message.content, _reasoning_text(choice.message)
    if redact is not None:
        text = redact(text)
        reasoning = redact(reasoning) if reasoning else reasoning
    result = LLMResponse(
        text=text,
        reasoning=reasoning,
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


# ---------- multi-turn chat with tools (agents) ----------

class ToolCall(BaseModel):
    id: str
    name: str
    arguments: str  # JSON text, as the model wrote it


class ChatResponse(BaseModel):
    content: str | None
    tool_calls: list[ToolCall] = []
    reasoning: str | None = None
    finish_reason: str | None = None
    task: Task
    provider: str
    model: str
    usage: TokenUsage
    cached: bool = False


# Muse Spark Open on Baseten sometimes writes a tool call as text instead of `tool_calls`:
# <x:invoke name="reply"><x:parameter name="kind">answer</x:parameter>...</x:invoke>
_TEXT_CALL = re.compile(r"<(?:\w+:)?invoke name=\"([^\"]+)\">(.*?)</(?:\w+:)?invoke>", re.DOTALL)
_TEXT_PARAM = re.compile(r"<(?:\w+:)?parameter name=\"([^\"]+)\">(.*?)</(?:\w+:)?parameter>", re.DOTALL)


def recover_text_tool_calls(content: str | None, tool_names: set[str]) -> list[ToolCall]:
    """Tool calls written as markup in the reply text (only for tools that were offered)."""
    calls = []
    for n, m in enumerate(_TEXT_CALL.finditer(content or "")):
        if m.group(1) not in tool_names:
            continue
        args: dict[str, Any] = {}
        for name, raw in _TEXT_PARAM.findall(m.group(2)):
            try:
                value = json.loads(raw)
                args[name] = value if isinstance(value, (list, dict)) else raw.strip()
            except json.JSONDecodeError:
                args[name] = raw.strip()
        calls.append(ToolCall(id=f"text-call-{n}", name=m.group(1), arguments=json.dumps(args, ensure_ascii=False)))
    return calls


def _with_recovered_calls(result: ChatResponse, tools: Sequence[Mapping[str, Any]] | None) -> ChatResponse:
    if result.tool_calls or not tools:
        return result
    calls = recover_text_tool_calls(result.content, {t["function"]["name"] for t in tools})
    return result.model_copy(update={"tool_calls": calls, "content": None}) if calls else result


def chat(
    messages: Sequence[Mapping[str, Any]],
    *,
    task: Task = "agent",
    tools: Sequence[Mapping[str, Any]] | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    overrides: Mapping[str, Any] | None = None,
    timeout: float | None = None,
    tool_choice: str | None = None,
) -> ChatResponse:
    """One turn of a tool-calling conversation (OpenAI Chat Completions `tools`).

    `messages` is the whole conversation so far, in OpenAI format (text only). The cache key is
    the full conversation plus the tools, so a replayed agent run costs nothing.
    `timeout` (seconds, no retries) is for interactive callers; it does not change the reply, so it is not in the key.
    `tool_choice` ("required": the model must call a tool) is sent only when given.
    """
    settings = get_settings()
    resolved = settings.resolve(task, overrides)
    if max_tokens is None:
        max_tokens = resolved.max_tokens
    cache = DiskCache(settings.cache_path)
    key = make_key({
        "kind": "chat", "task": resolved.task, "provider": resolved.provider, "model": resolved.model,
        "reasoning_effort": resolved.reasoning_effort, "messages": list(messages), "tools": list(tools or []),
        "temperature": temperature, "max_tokens": max_tokens, **({"tool_choice": tool_choice} if tool_choice else {}),
    })
    hit = cache.get(key)
    if hit is not None:
        return _with_recovered_calls(ChatResponse.model_validate({**hit, "cached": True}), tools)

    call = dict(messages=messages, task=task, tools=tools, temperature=temperature, max_tokens=max_tokens,
                timeout=timeout, tool_choice=tool_choice)
    switch = _before_baseten(settings, task, overrides, resolved)
    if switch is not None:
        return chat(**call, overrides=switch)
    try:
        return _chat_call(resolved, task, cache, key, messages, tools, temperature, max_tokens, timeout, tool_choice)
    except (LLMError, APIError):
        fallback = _fallback(settings, task, overrides, resolved)
        if fallback is None:
            raise
        budget.fallback(task, "error")
        return chat(**call, overrides=fallback)


def _chat_call(resolved: ResolvedModel, task: Task, cache: DiskCache, key: str, messages: Sequence[Mapping[str, Any]],
               tools: Sequence[Mapping[str, Any]] | None, temperature: float, max_tokens: int, timeout: float | None,
               tool_choice: str | None) -> ChatResponse:
    params: dict[str, Any] = {"model": resolved.model, "messages": list(messages), "temperature": temperature,
                              "max_tokens": max_tokens}
    if tools:
        params["tools"] = list(tools)
        if tool_choice:
            params["tool_choice"] = tool_choice
    if resolved.reasoning_effort is not None:
        params["reasoning_effort"] = resolved.reasoning_effort
    label = f"{resolved.provider}/{resolved.model}"
    client = _client(resolved.base_url, resolved.api_key.get_secret_value())
    if timeout is not None:
        client = client.with_options(timeout=timeout, max_retries=0)
    resp = client.chat.completions.create(**params)
    if not resp.choices:
        raise LLMError(f"No choices in response from {label}")
    choice = resp.choices[0]
    if resolved.provider == "baseten" and resp.usage is not None:
        budget.add(resp.usage.total_tokens or 0)  # counted whether or not the reply is usable
    if choice.finish_reason == "length":
        raise LLMError(f"{label} hit max_tokens={max_tokens}; raise {task.upper()}_MAX_TOKENS")
    message = choice.message
    calls = [ToolCall(id=c.id, name=c.function.name, arguments=c.function.arguments or "{}")
             for c in (message.tool_calls or [])]
    if message.content is None and not calls:
        raise EmptyResponse(f"Empty response from {label} (finish_reason={choice.finish_reason})")
    usage = TokenUsage()
    if resp.usage is not None:
        usage = TokenUsage(prompt_tokens=resp.usage.prompt_tokens or 0,
                           completion_tokens=resp.usage.completion_tokens or 0,
                           total_tokens=resp.usage.total_tokens or 0)
    result = ChatResponse(content=message.content, tool_calls=calls, reasoning=_reasoning_text(message),
                          finish_reason=choice.finish_reason, task=task, provider=resolved.provider,
                          model=resolved.model, usage=usage)
    cache.set(key, result.model_dump())
    logger.info("LLM chat [%s] %s: %d prompt + %d completion tokens, %d tool calls", task, label,
                usage.prompt_tokens, usage.completion_tokens, len(calls))
    return _with_recovered_calls(result, tools)
