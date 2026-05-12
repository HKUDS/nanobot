from types import SimpleNamespace

import pytest

import nanobot.providers.openai_codex_provider as codex_provider
from nanobot.providers.openai_codex_provider import OpenAICodexProvider


def _stub_codex_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        codex_provider,
        "get_codex_token",
        lambda: SimpleNamespace(account_id="account", access="token"),
    )


@pytest.mark.asyncio
async def test_codex_empty_exception_is_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_codex_token(monkeypatch)

    async def fake_request(*args, **kwargs):
        raise Exception()

    monkeypatch.setattr(codex_provider, "_request_codex", fake_request)

    response = await OpenAICodexProvider().chat(
        messages=[{"role": "user", "content": "hello"}],
    )

    assert response.finish_reason == "error"
    assert response.error_kind == "connection"
    assert response.error_should_retry is True
    assert response.content == "Error calling Codex: request failed without details"


@pytest.mark.asyncio
async def test_codex_empty_exception_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_codex_token(monkeypatch)
    calls = 0
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    async def fake_request(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise Exception()
        return "ok", [], "stop"

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(codex_provider, "_request_codex", fake_request)

    response = await OpenAICodexProvider().chat_with_retry(
        messages=[{"role": "user", "content": "hello"}],
    )

    assert response.finish_reason == "stop"
    assert response.content == "ok"
    assert calls == 2
    assert delays == [1]
