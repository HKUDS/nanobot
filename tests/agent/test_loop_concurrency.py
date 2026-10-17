from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nanobot.agent.loop import resolve_max_concurrent_requests


def _provider() -> MagicMock:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = SimpleNamespace(
        max_tokens=4096,
        temperature=0.1,
        reasoning_effort=None,
    )
    return provider


def test_request_concurrency_is_unlimited_by_default(
    monkeypatch: pytest.MonkeyPatch,
    loop_factory,
) -> None:
    monkeypatch.delenv("NANOBOT_MAX_CONCURRENT_REQUESTS", raising=False)

    loop = loop_factory(provider=_provider(), patch_deps=True)

    assert loop._concurrency_gate is None


@pytest.mark.asyncio
async def test_positive_request_concurrency_keeps_explicit_cap(
    monkeypatch: pytest.MonkeyPatch,
    loop_factory,
) -> None:
    monkeypatch.setenv("NANOBOT_MAX_CONCURRENT_REQUESTS", "2")
    loop = loop_factory(provider=_provider(), patch_deps=True)
    gate = loop._concurrency_gate

    assert gate is not None
    for _ in range(2):
        await gate.acquire()
    try:
        assert gate.locked()
    finally:
        for _ in range(2):
            gate.release()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", None),
        ("   ", None),
        ("auto", None),
        ("2.5", None),
        ("0", None),
        ("-1", None),
        (" 3 ", 3),
    ],
)
def test_unparsable_request_concurrency_falls_back_to_unlimited(
    raw: str,
    expected: int | None,
) -> None:
    assert resolve_max_concurrent_requests(raw) == expected


def test_blank_request_concurrency_does_not_break_loop_startup(
    monkeypatch: pytest.MonkeyPatch,
    loop_factory,
) -> None:
    # A commented-out or empty entry in an environment file yields "", not an
    # unset variable; that must not raise out of AgentLoop.__init__.
    monkeypatch.setenv("NANOBOT_MAX_CONCURRENT_REQUESTS", "")
    loop = loop_factory(provider=_provider(), patch_deps=True)

    assert loop._concurrency_gate is None
