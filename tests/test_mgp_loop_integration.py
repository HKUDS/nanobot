"""AgentLoop ↔ MGP sidecar integration tests.

Confirms the wiring contract between :class:`AgentLoop` and the optional
sidecar:

- when ``mgp.enabled=false`` the sidecar is never built, the recall_memory
  tool is never registered, the Consolidator/Dream hooks stay None, and the
  ``mgp-memory`` skill is suppressed
- when ``mgp.enabled=true`` the sidecar is built once, the tool is
  registered, and AgentLoop installs the ``on_archive`` /
  ``on_phase1_analysis`` hooks so Consolidator + Dream output flows to MGP
  without those classes ever importing ``mgp_client`` themselves
- ``recall_memory`` joins the spawn branch of ``_set_tool_context``

We monkeypatch :func:`build_sidecar` so these tests don't require a real MGP
gateway to be reachable.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import MGPConfig
from nanobot.providers.base import GenerationSettings, LLMResponse


def _make_loop(tmp_path, *, mgp_config: MGPConfig | None, monkeypatch) -> AgentLoop:
    """Build a minimal AgentLoop with a stubbed provider and a fake sidecar.

    The fake sidecar is installed via monkeypatch on ``build_sidecar`` so the
    enabled/disabled branch can be exercised without contacting any gateway.
    """
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings(max_tokens=0)
    provider.estimate_prompt_tokens.return_value = (0, "test-counter")
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))
    provider.chat_stream_with_retry = AsyncMock(
        return_value=LLMResponse(content="ok", tool_calls=[])
    )

    fake_sidecar = MagicMock(name="AsyncMGPSidecar")
    # Mirror real attributes that AgentLoop touches via injection / status.
    fake_sidecar.config = mgp_config

    def _fake_build_sidecar(cfg, *, workspace_id=None):
        return fake_sidecar

    # build_sidecar is imported lazily inside AgentLoop.__init__, so patch
    # at the package origin to intercept that import.
    monkeypatch.setattr("nanobot.agent.mgp.build_sidecar", _fake_build_sidecar)

    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        mgp_config=mgp_config,
    )
    # Stash the fake on the loop so tests can inspect it.
    loop._fake_sidecar = fake_sidecar  # type: ignore[attr-defined]
    return loop


# ---------------------------------------------------------------------------


def test_disabled_mgp_does_not_build_sidecar(tmp_path, monkeypatch) -> None:
    cfg = MGPConfig(enabled=False)
    loop = _make_loop(tmp_path, mgp_config=cfg, monkeypatch=monkeypatch)

    assert loop.mgp_sidecar is None
    assert loop.tools.get("recall_memory") is None
    # Consolidator and Dream stay MGP-unaware: their hooks are uninstalled.
    assert loop.consolidator.on_archive is None
    assert loop.dream.on_phase1_analysis is None


def test_disabled_mgp_suppresses_mgp_memory_skill(tmp_path, monkeypatch) -> None:
    cfg = MGPConfig(enabled=False)
    loop = _make_loop(tmp_path, mgp_config=cfg, monkeypatch=monkeypatch)
    # The mgp-memory skill must be invisible to the LLM when MGP is off.
    assert "mgp-memory" in loop.context.skills.disabled_skills


def test_enabled_mgp_builds_sidecar_and_registers_tool(tmp_path, monkeypatch) -> None:
    cfg = MGPConfig(enabled=True, gateway_url="http://test/")
    loop = _make_loop(tmp_path, mgp_config=cfg, monkeypatch=monkeypatch)

    assert loop.mgp_sidecar is loop._fake_sidecar
    tool = loop.tools.get("recall_memory")
    assert tool is not None
    # The tool reads its defaults from MGPConfig.
    assert tool._default_scope == cfg.recall_default_scope
    assert tool._default_limit == cfg.recall_default_limit
    # And the skill is NOT disabled — agent should see it.
    assert "mgp-memory" not in loop.context.skills.disabled_skills


def test_enabled_mgp_installs_hooks_on_consolidator_and_dream(tmp_path, monkeypatch) -> None:
    """AgentLoop owns the MGP-side wiring: Consolidator/Dream just expose hooks."""
    cfg = MGPConfig(enabled=True)
    loop = _make_loop(tmp_path, mgp_config=cfg, monkeypatch=monkeypatch)
    assert callable(loop.consolidator.on_archive)
    assert callable(loop.dream.on_phase1_analysis)


def test_set_tool_context_routes_recall_memory_via_spawn_branch(tmp_path, monkeypatch) -> None:
    cfg = MGPConfig(enabled=True)
    loop = _make_loop(tmp_path, mgp_config=cfg, monkeypatch=monkeypatch)
    tool = loop.tools.get("recall_memory")
    assert tool is not None

    loop._set_tool_context(channel="telegram", chat_id="alice", message_id="m-1")

    # The ContextVars should carry the channel / chat_id and an
    # auto-derived effective_key (channel:chat_id when not unified-session).
    assert tool._channel.get() == "telegram"
    assert tool._chat_id.get() == "alice"
    assert tool._session_key.get() == "telegram:alice"


def test_set_tool_context_uses_unified_session_key(tmp_path, monkeypatch) -> None:
    cfg = MGPConfig(enabled=True)
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings(max_tokens=0)
    provider.estimate_prompt_tokens.return_value = (0, "test-counter")
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))
    provider.chat_stream_with_retry = AsyncMock(
        return_value=LLMResponse(content="ok", tool_calls=[])
    )

    fake_sidecar = MagicMock()
    fake_sidecar.config = cfg
    monkeypatch.setattr("nanobot.agent.mgp.build_sidecar", lambda c, *, workspace_id=None: fake_sidecar)

    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        unified_session=True,
        mgp_config=cfg,
    )
    loop._set_tool_context(channel="telegram", chat_id="alice", message_id="m-1")
    tool = loop.tools.get("recall_memory")
    assert tool._session_key.get() == "unified:default"


@pytest.mark.asyncio
async def test_consolidator_archive_dispatches_commit_when_enabled(tmp_path, monkeypatch) -> None:
    """archive() must hand off the LLM summary to sidecar.commit_bullets."""
    cfg = MGPConfig(enabled=True)
    loop = _make_loop(tmp_path, mgp_config=cfg, monkeypatch=monkeypatch)

    # Make commit_bullets an awaitable that records its args.
    loop._fake_sidecar.commit_bullets = AsyncMock(return_value=[])

    # Patch the consolidator's LLM call to return a deterministic summary.
    summary = "- User has a cat named Luna"
    loop.provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content=summary, tool_calls=[])
    )
    session = loop.sessions.get_or_create("telegram:alice")
    session.messages = [{"role": "user", "content": "hi", "timestamp": "2026-01-01T00:00:00"}]

    # Drive a single archive() — fire-and-forget MGP commit dispatched.
    result = await loop.consolidator.archive(session.messages, session=session)
    assert result == summary

    # Drain background tasks so commit_bullets actually runs.
    pending = [t for t in __import__("asyncio").all_tasks() if not t.done() and t is not __import__("asyncio").current_task()]
    if pending:
        await __import__("asyncio").gather(*pending, return_exceptions=True)

    loop._fake_sidecar.commit_bullets.assert_awaited()
    # First positional arg is the runtime, second is the summary string.
    call_args = loop._fake_sidecar.commit_bullets.await_args.args
    assert call_args[1] == summary


@pytest.mark.asyncio
async def test_consolidator_archive_skips_commit_when_disabled(tmp_path, monkeypatch) -> None:
    cfg = MGPConfig(enabled=True, enable_consolidator_commit=False)
    loop = _make_loop(tmp_path, mgp_config=cfg, monkeypatch=monkeypatch)
    loop._fake_sidecar.commit_bullets = AsyncMock(return_value=[])
    loop.provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="- a fact", tool_calls=[])
    )
    session = loop.sessions.get_or_create("cli:direct")
    session.messages = [{"role": "user", "content": "hi", "timestamp": "2026-01-01T00:00:00"}]
    await loop.consolidator.archive(session.messages, session=session)
    loop._fake_sidecar.commit_bullets.assert_not_called()


@pytest.mark.asyncio
async def test_consolidator_archive_skips_commit_without_session(tmp_path, monkeypatch) -> None:
    """Legacy callers that omit `session=` must still work without crashing."""
    cfg = MGPConfig(enabled=True)
    loop = _make_loop(tmp_path, mgp_config=cfg, monkeypatch=monkeypatch)
    loop._fake_sidecar.commit_bullets = AsyncMock(return_value=[])
    loop.provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="- a fact", tool_calls=[])
    )
    msgs = [{"role": "user", "content": "hi", "timestamp": "2026-01-01T00:00:00"}]
    summary = await loop.consolidator.archive(msgs)  # no session=
    assert summary == "- a fact"
    loop._fake_sidecar.commit_bullets.assert_not_called()


# -- Dream → MGP wiring (post-decouple regression) --------------------------


@pytest.mark.asyncio
async def test_dream_phase1_hook_dispatches_commit_when_enabled(tmp_path, monkeypatch) -> None:
    """Dream.on_phase1_analysis must hand the analysis to commit_dream_tags."""
    import asyncio as _aio

    cfg = MGPConfig(enabled=True)
    loop = _make_loop(tmp_path, mgp_config=cfg, monkeypatch=monkeypatch)
    loop._fake_sidecar.commit_dream_tags = AsyncMock(return_value=[])

    analysis = "[USER] prefers concise replies\n[MEMORY] uses python 3.11"
    loop.dream.on_phase1_analysis(analysis)

    pending = [t for t in _aio.all_tasks() if not t.done() and t is not _aio.current_task()]
    if pending:
        await _aio.gather(*pending, return_exceptions=True)

    loop._fake_sidecar.commit_dream_tags.assert_awaited()
    call_args = loop._fake_sidecar.commit_dream_tags.await_args.args
    assert call_args[1] == analysis


@pytest.mark.asyncio
async def test_dream_phase1_hook_skips_commit_when_disabled(tmp_path, monkeypatch) -> None:
    cfg = MGPConfig(enabled=True, enable_dream_commit=False)
    loop = _make_loop(tmp_path, mgp_config=cfg, monkeypatch=monkeypatch)
    loop._fake_sidecar.commit_dream_tags = AsyncMock(return_value=[])

    loop.dream.on_phase1_analysis("[USER] foo")
    loop._fake_sidecar.commit_dream_tags.assert_not_called()
