"""Test /new archival behavior."""

import asyncio
from collections.abc import Coroutine
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.utils.prompt_templates import render_template

_ARCHIVE_PROMPT = render_template("agent/consolidator_archive.md", strip=True)


class TestNewCommandArchival:
    """Test /new archival behavior with the structured archive flow."""

    @staticmethod
    def _make_loop(tmp_path: Path):
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.queue import MessageBus
        from nanobot.providers.base import GenerationSettings, LLMResponse

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.estimate_prompt_tokens.return_value = (10_000, "test")
        provider.generation = GenerationSettings(max_tokens=100)
        loop = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=tmp_path,
            model="test-model",
            context_window_tokens=1,
        )
        loop.provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content="ok", tool_calls=[])
        )
        loop.tools.get_definitions = MagicMock(return_value=[])
        return loop

    @pytest.mark.asyncio
    async def test_new_clears_session_immediately_even_if_archive_fails(
        self,
        tmp_path: Path,
    ) -> None:
        """/new clears session immediately; archive is fire-and-forget."""
        from nanobot.bus.events import InboundMessage

        loop = self._make_loop(tmp_path)
        session = loop.sessions.get_or_create("cli:test")
        for i in range(5):
            session.add_message("user", f"msg{i}")
            session.add_message("assistant", f"resp{i}")
        loop.sessions.save(session)

        call_count = 0
        expected_runtime = loop.llm_runtime()

        async def _failing_summarize(session, *, archive_end, runtime) -> None:
            nonlocal call_count
            assert runtime is expected_runtime
            assert session.key == "cli:test"
            assert archive_end == len(session.messages)
            call_count += 1

        loop.consolidator.archive_session = _failing_summarize  # type: ignore[method-assign]

        new_msg = InboundMessage(channel="cli", sender_id="user", chat_id="test", content="/new")
        response = await loop._process_message(new_msg, runtime=expected_runtime)

        assert response is not None
        assert "new session started" in response.content.lower()

        session_after = loop.sessions.get_or_create("cli:test")
        assert len(session_after.messages) == 0

        await loop.aclose()
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_new_reuses_replay_prefix_and_archives_only_unarchived_messages(
        self,
        tmp_path: Path,
    ) -> None:
        from nanobot.bus.events import InboundMessage

        loop = self._make_loop(tmp_path)
        loop.set_runtime_context_window(128_000)
        session = loop.sessions.get_or_create("cli:test")
        for i in range(5):
            session.add_message("user", f"msg{i}")
            session.add_message("assistant", f"resp{i}")
        session.last_archived = len(session.messages) - 2
        ordinary_history = session.get_history()
        assert [message["content"] for message in ordinary_history] == [
            "msg1",
            "resp1",
            "msg2",
            "resp2",
            "msg3",
            "resp3",
            "msg4",
            "resp4",
        ]
        loop.sessions.save(session)

        expected_runtime = loop.llm_runtime()
        scheduled: list[Coroutine[Any, Any, object]] = []
        loop.schedule_background = scheduled.append  # type: ignore[method-assign]

        new_msg = InboundMessage(channel="cli", sender_id="user", chat_id="test", content="/new")
        response = await loop._process_message(new_msg, runtime=expected_runtime)

        assert response is not None
        assert "new session started" in response.content.lower()

        assert len(scheduled) == 1
        await scheduled[0]
        await loop.aclose()
        sent = loop.provider.chat_with_retry.call_args.kwargs["messages"]
        assert sent[1:-1] == ordinary_history
        assert sent[-1]["content"] == _ARCHIVE_PROMPT

    @pytest.mark.asyncio
    async def test_new_clears_session_and_responds(self, tmp_path: Path) -> None:
        from nanobot.bus.events import InboundMessage

        loop = self._make_loop(tmp_path)
        session = loop.sessions.get_or_create("cli:test")
        for i in range(3):
            session.add_message("user", f"msg{i}")
            session.add_message("assistant", f"resp{i}")
        loop.sessions.save(session)
        expected_runtime = loop.llm_runtime()

        async def _ok_summarize(session, *, archive_end, runtime) -> str:
            assert runtime is expected_runtime
            assert session.key == "cli:test"
            assert archive_end == len(session.messages)
            return "Summary."

        loop.consolidator.archive_session = _ok_summarize  # type: ignore[method-assign]

        new_msg = InboundMessage(channel="cli", sender_id="user", chat_id="test", content="/new")
        response = await loop._process_message(new_msg, runtime=expected_runtime)

        assert response is not None
        assert "new session started" in response.content.lower()
        assert loop.sessions.get_or_create("cli:test").messages == []

    @pytest.mark.asyncio
    async def test_aclose_drains_background_tasks(self, tmp_path: Path) -> None:
        """aclose waits for background tasks to complete."""
        from nanobot.bus.events import InboundMessage

        loop = self._make_loop(tmp_path)
        session = loop.sessions.get_or_create("cli:test")
        for i in range(3):
            session.add_message("user", f"msg{i}")
            session.add_message("assistant", f"resp{i}")
        loop.sessions.save(session)

        archived = asyncio.Event()
        release_archive = asyncio.Event()
        expected_runtime = loop.llm_runtime()

        async def _slow_summarize(session, *, archive_end, runtime) -> str:
            assert runtime is expected_runtime
            assert session.key == "cli:test"
            assert archive_end == len(session.messages)
            await release_archive.wait()
            archived.set()
            return "Summary."

        loop.consolidator.archive_session = _slow_summarize  # type: ignore[method-assign]

        new_msg = InboundMessage(channel="cli", sender_id="user", chat_id="test", content="/new")
        await loop._process_message(new_msg, runtime=expected_runtime)

        assert not archived.is_set()
        release_archive.set()
        await loop.aclose()
        assert archived.is_set()
