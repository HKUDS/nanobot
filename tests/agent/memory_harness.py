"""Scripted helpers for memory lifecycle tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from nanobot.agent.memory import Consolidator, MemoryStore
from nanobot.session.manager import Session, SessionManager


class ScriptedMemoryProvider:
    """Tiny provider stub that returns queued text responses."""

    def __init__(self, *responses: str | BaseException) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.generation = SimpleNamespace(max_tokens=128)

    async def chat_with_retry(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("ScriptedMemoryProvider has no response queued")
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return SimpleNamespace(content=response, finish_reason="stop")


@dataclass
class MemoryLifecycleHarness:
    """Drive a small memory flow from session turns to durable files."""

    workspace: Path
    model: str = "test-model"
    store: MemoryStore = field(init=False)
    sessions: SessionManager = field(init=False)

    def __post_init__(self) -> None:
        self.store = MemoryStore(self.workspace)
        self.sessions = SessionManager(self.workspace)
        self.store.write_soul("# Soul\n- Helpful")
        self.store.write_user("# User\n")
        self.store.write_memory("# Memory\n")

    def session(self, key: str = "cli:memory") -> Session:
        return self.sessions.get_or_create(key)

    def add_turn(self, session: Session, user: str, assistant: str) -> None:
        session.add_message("user", user)
        session.add_message("assistant", assistant)
        self.sessions.save(session)

    async def archive_session(
        self,
        session: Session,
        *,
        summary: str | BaseException,
        end_idx: int | None = None,
    ) -> str | None:
        provider = ScriptedMemoryProvider(summary)
        consolidator = Consolidator(
            store=self.store,
            provider=provider,
            model=self.model,
            sessions=self.sessions,
            context_window_tokens=4096,
            build_messages=lambda **_kwargs: [],
            get_tool_definitions=lambda: [],
            max_completion_tokens=128,
        )
        end_idx = len(session.messages) if end_idx is None else end_idx
        result = await consolidator.archive(session.messages[:end_idx])
        session.last_consolidated = end_idx
        self.sessions.save(session)
        return result

    def init_git_snapshot(self) -> None:
        assert self.store.git.init() is True

    def commit_memory_change(self, message: str) -> str:
        sha = self.store.git.auto_commit(message)
        assert sha is not None
        return sha
