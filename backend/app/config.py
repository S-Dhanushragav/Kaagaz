"""Settings loaded from the repo-root .env file (see .env.example)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

Provider = Literal["meta", "baseten"]


class ProviderConfig(BaseModel):
    """Connection details for the active LLM provider."""

    name: Provider
    base_url: str
    api_key: SecretStr
    model: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8-sig",  # tolerate a BOM in .env
        extra="ignore",
    )

    llm_provider: Provider = "baseten"

    meta_api_key: SecretStr = SecretStr("")
    meta_base_url: str = ""
    meta_model: str = ""

    baseten_api_key: SecretStr = SecretStr("")
    baseten_base_url: str = ""
    baseten_model: str = ""

    segmenter: Literal["sam31_api", "sam3_modal"] = "sam31_api"

    cache_dir: Path = Path(".cache")

    @property
    def cache_path(self) -> Path:
        """Cache directory; relative paths are resolved against the repo root."""
        return self.cache_dir if self.cache_dir.is_absolute() else REPO_ROOT / self.cache_dir

    def active_provider(self) -> ProviderConfig:
        """Return the selected provider's settings, or raise if any are missing."""
        if self.llm_provider == "meta":
            cfg = ProviderConfig(
                name="meta",
                base_url=self.meta_base_url,
                api_key=self.meta_api_key,
                model=self.meta_model,
            )
        else:
            cfg = ProviderConfig(
                name="baseten",
                base_url=self.baseten_base_url,
                api_key=self.baseten_api_key,
                model=self.baseten_model,
            )
        prefix = cfg.name.upper()
        missing = [
            f"{prefix}_{field}"
            for field, value in (
                ("BASE_URL", cfg.base_url),
                ("API_KEY", cfg.api_key.get_secret_value()),
                ("MODEL", cfg.model),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                f"LLM_PROVIDER={cfg.name} but these are not set in .env: {', '.join(missing)}"
            )
        return cfg


@lru_cache
def get_settings() -> Settings:
    return Settings()
