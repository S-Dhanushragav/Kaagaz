import pytest

from app.config import Settings

FULL = {
    "vision_provider": "meta",
    "agent_provider": "meta",
    "text_provider": "baseten",
    "meta_api_key": "mk",
    "meta_base_url": "https://meta.example/v1",
    "meta_vision_model": "meta-vision",
    "meta_agent_model": "meta-agent",
    "meta_text_model": "meta-text",
    "baseten_api_key": "bk",
    "baseten_base_url": "https://baseten.example/v1",
    "baseten_model": "open-model",
}


def make(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**FULL, **overrides})


def test_meta_tasks_use_their_own_model() -> None:
    s = make()
    assert s.resolve("vision").model == "meta-vision"
    assert s.resolve("agent").model == "meta-agent"
    assert s.resolve("vision").base_url == "https://meta.example/v1"


def test_baseten_uses_one_model_for_every_task() -> None:
    s = make(vision_provider="baseten", agent_provider="baseten")
    for task in ("vision", "agent", "text"):
        r = s.resolve(task)
        assert (r.provider, r.model, r.base_url) == ("baseten", "open-model", "https://baseten.example/v1")


def test_max_tokens_defaults_and_override() -> None:
    s = make()
    assert [s.resolve(t).max_tokens for t in ("vision", "agent", "text")] == [4000, 6000, 1500]
    assert make(vision_max_tokens="8000").resolve("vision").max_tokens == 8000
    assert make(text_max_tokens="").resolve("text").max_tokens == 1500


def test_reasoning_effort_blank_is_none() -> None:
    assert make().resolve("vision").reasoning_effort is None
    assert make(agent_reasoning_effort=" ").resolve("agent").reasoning_effort is None
    assert make(agent_reasoning_effort="high").resolve("agent").reasoning_effort == "high"


def test_missing_provider_error() -> None:
    with pytest.raises(ValueError, match="VISION_PROVIDER"):
        make(vision_provider="").resolve("vision")


def test_missing_settings_named_in_error() -> None:
    with pytest.raises(ValueError, match="'vision'.*'meta'.*META_API_KEY, META_VISION_MODEL"):
        make(meta_api_key="", meta_vision_model="").resolve("vision")
    with pytest.raises(ValueError, match="BASETEN_MODEL"):
        make(baseten_model="").resolve("text")


def test_values_are_stripped() -> None:
    s = make(meta_vision_model="  muse-spark-1.3 ", vision_provider=" meta ")
    assert s.resolve("vision").model == "muse-spark-1.3"


def test_invalid_provider_rejected() -> None:
    with pytest.raises(ValueError):
        make(text_provider="openai")


def test_overrides() -> None:
    s = make(vision_reasoning_effort="low")
    r = s.resolve("vision", {"model": "other-model", "reasoning_effort": None, "max_tokens": 9000})
    assert (r.model, r.reasoning_effort, r.max_tokens) == ("other-model", None, 9000)
    assert s.resolve("vision").reasoning_effort == "low"  # overrides don't stick
    r = s.resolve("text", {"provider": "meta"})
    assert (r.provider, r.model) == ("meta", "meta-text")


def test_bad_overrides_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown override"):
        make().resolve("vision", {"temperature": 1})
    with pytest.raises(ValueError, match="provider override"):
        make().resolve("vision", {"provider": "openai"})


def test_comparison_cells_never_share_cache_key() -> None:
    from clients.llm import cache_key

    s = make()
    keys = {
        cache_key(
            s.resolve("vision", {"model": model, "reasoning_effort": effort}),
            prompt="p", image=b"img", image_mime="image/jpeg", system=None,
            temperature=0.0, max_tokens=8000, response_format=None,
        )
        for model in ("muse-spark-1.3", "muse-spark-1.1")
        for effort in (None, "low")
    }
    assert len(keys) == 4
