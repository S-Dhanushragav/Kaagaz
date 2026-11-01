"""Baseten daily token budget and the fallback to Muse Spark (clients/budget.py, clients/llm.py). No network."""

from types import SimpleNamespace

import pytest
from openai import APIConnectionError

from app.config import get_settings
from clients import budget, llm


def _resp(text: str = "ok", total: int = 100) -> SimpleNamespace:
    message = SimpleNamespace(content=text, tool_calls=None, model_extra={})
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")],
                           usage=SimpleNamespace(prompt_tokens=total - 10, completion_tokens=10, total_tokens=total))


class FakeClient:
    """Stands in for the OpenAI client: records which provider (base URL) each call went to."""

    def __init__(self, calls: list[str], base_url: str, fail: set[str]) -> None:
        self.calls, self.base_url, self.fail = calls, base_url, fail
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def with_options(self, **_: object) -> "FakeClient":
        return self

    def _create(self, **params: object) -> SimpleNamespace:
        provider = "baseten" if "baseten" in self.base_url else "meta"
        self.calls.append(provider)
        if provider in self.fail:
            raise APIConnectionError(request=None)  # type: ignore[arg-type]
        return _resp(f"from {provider}", total=400)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path):
    for k, v in {"META_BASE_URL": "https://meta.test", "META_API_KEY": "k", "META_VISION_MODEL": "muse-spark",
                 "META_AGENT_MODEL": "muse-spark", "BASETEN_BASE_URL": "https://baseten.test", "BASETEN_API_KEY": "k",
                 "BASETEN_MODEL": "muse-spark-open", "VISION_PROVIDER": "baseten", "ASK_PROVIDER": "baseten",
                 "TEXT_PROVIDER": "baseten", "CACHE_DIR": str(tmp_path), "BASETEN_DAILY_TOKENS": "1000"}.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    budget.reset_for_tests()
    calls: list[str] = []
    fail: set[str] = set()
    monkeypatch.setattr(llm, "_client", lambda base_url, key: FakeClient(calls, base_url, fail))
    yield SimpleNamespace(calls=calls, fail=fail)
    get_settings.cache_clear()
    budget.reset_for_tests()


def test_baseten_tokens_are_counted_and_cache_hits_are_free(env) -> None:
    llm.complete("hello", task="text")
    llm.complete("hello", task="text")  # cached
    assert env.calls == ["baseten"]
    assert budget.status()["tokens"] == 400 and budget.status()["calls"] == 1


def test_budget_used_up_refuses_ask_and_text(env) -> None:
    llm.complete("a", task="text")
    llm.complete("b", task="text")
    llm.complete("c", task="text")  # 1200 >= 1000
    with pytest.raises(llm.BudgetExhausted):
        llm.complete("d", task="text")
    with pytest.raises(llm.BudgetExhausted):
        llm.chat([{"role": "user", "content": "q"}], task="ask")
    assert env.calls == ["baseten"] * 3
    assert budget.status()["refused"] == 2


def test_budget_used_up_sends_a_vision_read_to_muse_spark(env) -> None:
    for p in "abc":
        llm.complete(p, task="text")
    resp = llm.complete("read this", task="vision")
    assert resp.provider == "meta" and resp.text == "from meta"
    assert env.calls[-1] == "meta"
    assert budget.status()["fallbacks"] == {"vision:budget": 1}


def test_baseten_failure_falls_back_for_vision_but_not_for_ask(env) -> None:
    env.fail.add("baseten")
    resp = llm.complete("read this", task="vision")
    assert resp.provider == "meta" and env.calls == ["baseten", "meta"]
    assert budget.status()["fallbacks"] == {"vision:error": 1}
    with pytest.raises(APIConnectionError):
        llm.chat([{"role": "user", "content": "q"}], task="ask")


def test_budget_survives_a_restart(env) -> None:
    llm.complete("a", task="text")
    budget.reset_for_tests()  # memory gone: read back from the file
    assert budget.status()["tokens"] == 400


def test_ask_says_unavailable_when_the_budget_is_used_up(env) -> None:
    from agents.ask import ask
    from agents.ask_tools import load_ask

    for p in "abc":
        llm.complete(p, task="text")
    answer = ask("Who can get Ladki Bahin?", "mr")
    assert answer.kind == "unavailable" and answer.text == load_ask("mr").replies["unavailable"]


def test_photo_second_read_goes_to_its_provider() -> None:
    from graph.nodes.read_documents import DocumentInput, StreamingReader

    seen: list[object] = []

    def fake_llm(prompt: str, **kw: object) -> object:
        seen.append((kw.get("overrides") or {}).get("provider"))
        raise llm.LLMError("stop here")

    doc = DocumentInput(id="d1", images=[b"a", b"b"], read_providers=[None, "baseten"])
    with StreamingReader(llm=fake_llm, agreement=True) as reader:
        reader.submit(doc)
        reader.results()
    assert sorted(seen, key=str) == [None, "baseten"]
