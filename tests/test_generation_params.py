from types import SimpleNamespace

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.subagent import SubagentManager
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.providers.openai_codex_provider import OpenAICodexProvider
from nanobot.session.manager import Session


class _RecordingProvider(LLMProvider):
    def __init__(self) -> None:
        super().__init__(api_key=None, api_base=None)
        self.calls: list[dict[str, object]] = []

    async def chat(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        self.calls.append(
            {
                "messages": messages,
                "tools": tools,
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        return LLMResponse(content="ok")

    def get_default_model(self) -> str:
        return "test-model"


class _InMemorySessions:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def get_or_create(self, key: str) -> Session:
        if key not in self._sessions:
            self._sessions[key] = Session(key=key)
        return self._sessions[key]

    def save(self, session: Session) -> None:
        self._sessions[session.key] = session


@pytest.mark.asyncio
async def test_agent_loop_forwards_generation_parameters(tmp_path) -> None:
    provider = _RecordingProvider()
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        max_tokens=1234,
        temperature=0.25,
        session_manager=_InMemorySessions(),
    )

    response = await loop.process_direct("hello")

    assert response == "ok"
    assert provider.calls
    call = provider.calls[0]
    assert call["max_tokens"] == 1234
    assert call["temperature"] == 0.25


@pytest.mark.asyncio
async def test_subagent_forwards_generation_parameters(tmp_path) -> None:
    provider = _RecordingProvider()
    manager = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=MessageBus(),
        model="test-model",
        max_tokens=2222,
        temperature=0.15,
    )

    await manager._run_subagent(
        task_id="task1234",
        task="say hello",
        label="hello",
        origin={"channel": "cli", "chat_id": "direct"},
    )

    assert provider.calls
    call = provider.calls[0]
    assert call["max_tokens"] == 2222
    assert call["temperature"] == 0.15


@pytest.mark.asyncio
async def test_litellm_chat_uses_passed_generation_parameters(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_acompletion(**kwargs):
        captured.update(kwargs)
        message = SimpleNamespace(content="ok", tool_calls=None)
        choice = SimpleNamespace(message=message, finish_reason="stop")
        return SimpleNamespace(choices=[choice], usage=None)

    monkeypatch.setattr("nanobot.providers.litellm_provider.acompletion", _fake_acompletion)

    provider = LiteLLMProvider(default_model="anthropic/claude-opus-4-5")
    result = await provider.chat(
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=987,
        temperature=0.42,
    )

    assert result.content == "ok"
    assert captured["max_tokens"] == 987
    assert captured["temperature"] == 0.42


def test_agent_defaults_max_tokens_default_is_4096() -> None:
    defaults = AgentDefaults()
    assert defaults.max_tokens == 4096


@pytest.mark.asyncio
async def test_codex_chat_uses_max_output_tokens_and_ignores_temperature(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_request_codex(
        url: str, headers: dict[str, str], body: dict[str, object], verify: bool
    ):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = body
        captured["verify"] = verify
        return "ok", [], "stop"

    monkeypatch.setattr(
        "nanobot.providers.openai_codex_provider.get_codex_token",
        lambda: SimpleNamespace(account_id="acc", access="tok"),
    )
    monkeypatch.setattr(
        "nanobot.providers.openai_codex_provider._request_codex",
        _fake_request_codex,
    )

    provider = OpenAICodexProvider(default_model="openai-codex/gpt-5.1-codex")
    response = await provider.chat(
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=777,
        temperature=0.19,
    )

    assert response.content == "ok"
    assert captured["verify"] is True
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["max_output_tokens"] == 777
    assert "temperature" not in body
