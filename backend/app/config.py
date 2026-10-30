"""Settings loaded from the repo-root .env file (see .env.example).

LLM calls are routed per task ("vision", "agent", "text"): each task picks a provider,
and the provider + task decide the model, reasoning effort, and max tokens.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import BaseModel, Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

Provider = Literal["meta", "baseten"]
Task = Literal["vision", "agent", "text"]

OVERRIDABLE = frozenset({"provider", "model", "reasoning_effort", "max_tokens"})


class ResolvedModel(BaseModel):
    """Everything needed to make one LLM call for a task."""

    task: Task
    provider: Provider
    base_url: str
    api_key: SecretStr
    model: str
    reasoning_effort: str | None
    max_tokens: int


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8-sig",  # tolerate a BOM in .env
        extra="ignore",
        str_strip_whitespace=True,
    )

    # Per-task routing
    vision_provider: Provider | None = None
    agent_provider: Provider | None = None
    text_provider: Provider | None = None

    # Per-task reasoning effort; None = parameter not sent
    vision_reasoning_effort: str | None = None
    agent_reasoning_effort: str | None = None
    text_reasoning_effort: str | None = None

    # Per-task output budget (includes reasoning tokens)
    vision_max_tokens: int = Field(4000, gt=0)
    agent_max_tokens: int = Field(6000, gt=0)
    text_max_tokens: int = Field(4000, gt=0)

    # Meta Model API
    meta_api_key: SecretStr = SecretStr("")
    meta_base_url: str = ""
    meta_vision_model: str = ""
    meta_agent_model: str = ""
    meta_text_model: str = ""
    meta_transcribe_model: str = ""  # used by clients/transcribe.py
    asr_keyword_languages: str = "en"  # comma-separated: languages that send keyword biasing (it hurt hi/mr)
    meta_segment_model: str = ""  # used by clients/segmenter.py (not built yet)

    # Baseten (Muse Spark Open): one model for all tasks
    baseten_api_key: SecretStr = SecretStr("")
    baseten_base_url: str = ""
    baseten_model: str = ""

    segmenter: Literal["sam31_api", "sam3_modal"] = "sam31_api"

    # API sessions (app/sessions.py)
    max_sessions_per_hour: int = Field(30, ge=0)  # uploads; the bundled sample is not counted
    session_ttl_s: int = Field(3600, gt=0)  # session data (results, crops) deleted after this
    max_video_s: float = 45.0
    max_video_mb: float = 60.0
    upload_long_side: int = 1920  # uploads are re-encoded with at most this long side (1080p keeps full size)
    sample_video: str = "synthetic/videos/HH009/sweep.mp4"  # relative to the repo root
    cors_origins: str = "http://localhost:5173"  # comma-separated; the deployed frontend's origin only
    sessions_dir: Path = Path("tmp/sessions")

    # Case files and login (Phase 9). Secrets come from .env / the Modal secret, never from code.
    database_url: SecretStr = SecretStr("")  # Neon pooled URL; empty: an in-memory store (nothing survives a restart)
    phone_hash_key: SecretStr = SecretStr("")  # HMAC key for phone numbers
    token_signing_key: SecretStr = SecretStr("")  # HMAC key for login tokens
    auth_mode: Literal["demo", "sms"] = "demo"  # demo: the code is shown in the app, no SMS is sent
    # production (default): login keys must be set (app/auth.py auth_keys); local/test: development keys allowed
    kaagaz_env: Literal["local", "test", "production"] = "production"
    database_url_test: SecretStr = SecretStr("")  # live-database tests use this when set (KAAGAZ_LIVE_DB=1)
    check_retention_days: int = Field(365, gt=0)  # stored checks older than this are deleted

    # Speech output (clients/tts.py): Meta MMS-TTS, CC-BY-NC 4.0, run locally on CPU
    tts_model_en: str = ""
    tts_model_hi: str = ""
    tts_model_mr: str = ""

    cache_dir: Path = Path(".cache")

    @field_validator(
        "vision_provider",
        "agent_provider",
        "text_provider",
        "vision_reasoning_effort",
        "agent_reasoning_effort",
        "text_reasoning_effort",
        mode="before",
    )
    @classmethod
    def _blank_is_none(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("vision_max_tokens", "agent_max_tokens", "text_max_tokens", mode="before")
    @classmethod
    def _blank_is_default(cls, value: Any, info: ValidationInfo) -> Any:
        if isinstance(value, str) and not value.strip():
            return cls.model_fields[info.field_name].default
        return value

    @property
    def cache_path(self) -> Path:
        """Cache directory; relative paths are resolved against the repo root."""
        return self.cache_dir if self.cache_dir.is_absolute() else REPO_ROOT / self.cache_dir

    def resolve(self, task: Task, overrides: Mapping[str, Any] | None = None) -> ResolvedModel:
        """Resolve provider, model, and call settings for a task, or raise naming what's missing.

        `overrides` replaces any of provider, model, reasoning_effort, max_tokens for this call
        only (e.g. model comparisons). A key that is present wins even if its value is None,
        so {"reasoning_effort": None} means "don't send it".
        """
        overrides = dict(overrides or {})
        unknown = overrides.keys() - OVERRIDABLE
        if unknown:
            raise ValueError(f"Unknown override(s): {', '.join(sorted(unknown))}")

        provider: Provider | None = overrides.get("provider", getattr(self, f"{task}_provider"))
        if provider is None:
            raise ValueError(f"Task '{task}': {task.upper()}_PROVIDER is not set in .env (meta | baseten)")
        if provider not in ("meta", "baseten"):
            raise ValueError(f"Unknown provider override: {provider!r}")

        if provider == "meta":
            base_url, api_key = self.meta_base_url, self.meta_api_key
            model, model_var = getattr(self, f"meta_{task}_model"), f"META_{task.upper()}_MODEL"
        else:
            base_url, api_key = self.baseten_base_url, self.baseten_api_key
            model, model_var = self.baseten_model, "BASETEN_MODEL"
        model = overrides.get("model", model)

        prefix = provider.upper()
        missing = [
            name
            for name, value in (
                (f"{prefix}_BASE_URL", base_url),
                (f"{prefix}_API_KEY", api_key.get_secret_value()),
                (model_var, model),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                f"Task '{task}' uses provider '{provider}' but these are not set in .env: "
                + ", ".join(missing)
            )

        return ResolvedModel(
            task=task,
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            model=model,
            reasoning_effort=overrides.get("reasoning_effort", getattr(self, f"{task}_reasoning_effort")),
            max_tokens=overrides.get("max_tokens", getattr(self, f"{task}_max_tokens")),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
