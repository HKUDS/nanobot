from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from nanobot.agent.memory import MemoryStore
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.command.builtin import (
    build_help_text,
    builtin_command_palette,
    cmd_dream,
    cmd_dream_log,
    cmd_dream_prompt,
    cmd_dream_restore,
)
from nanobot.command.router import CommandContext
from nanobot.utils.gitstore import CommitInfo


class _FakeStore:
    def __init__(self, git, last_dream_cursor: int = 1, dream_prompt_result=None):
        self.git = git
        self._last_dream_cursor = last_dream_cursor
        self._dream_prompt_result = dream_prompt_result
        self.compact_history_called = False

    def get_last_dream_cursor(self) -> int:
        return self._last_dream_cursor

    def build_dream_prompt(self):
        return self._dream_prompt_result

    def build_dream_tools(self):
        return None

    def set_last_dream_cursor(self, value: int) -> None:
        self._last_dream_cursor = value

    def compact_history(self) -> None:
        self.compact_history_called = True


class _FakeGit:
    def __init__(
        self,
        *,
        initialized: bool = True,
        commits: list[CommitInfo] | None = None,
        diff_map: dict[str, tuple[CommitInfo, str] | None] | None = None,
        revert_result: str | None = None,
    ):
        self._initialized = initialized
        self._commits = commits or []
        self._diff_map = diff_map or {}
        self._revert_result = revert_result

    def is_initialized(self) -> bool:
        return self._initialized

    def log(self, max_entries: int = 20) -> list[CommitInfo]:
        return self._commits[:max_entries]

    def show_commit_diff(self, sha: str, max_entries: int = 20):
        return self._diff_map.get(sha)

    def revert(self, sha: str) -> str | None:
        return self._revert_result

    def auto_commit(self, message: str) -> str | None:
        return None


class _FakeBus:
    def __init__(self):
        self.outbound = []

    async def publish_outbound(self, message):
        self.outbound.append(message)


def _make_ctx(raw: str, git: _FakeGit, *, args: str = "", last_dream_cursor: int = 1) -> CommandContext:
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content=raw)
    store = _FakeStore(git, last_dream_cursor=last_dream_cursor)
    loop = SimpleNamespace(consolidator=SimpleNamespace(store=store))
    return CommandContext(msg=msg, session=None, key=msg.session_key, raw=raw, args=args, loop=loop)


def _make_dream_ctx(tmp_path) -> tuple[CommandContext, _FakeBus]:
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/dream")
    store = _FakeStore(_FakeGit(initialized=False), dream_prompt_result=None)
    bus = _FakeBus()
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    loop = SimpleNamespace(
        bus=bus,
        context=SimpleNamespace(memory=store, timezone="UTC"),
        sessions=SimpleNamespace(sessions_dir=sessions_dir),
    )
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/dream", args="", loop=loop)
    return ctx, bus


def _make_dream_prompt_ctx(tmp_path, raw: str = "/dream-prompt", args: str = "") -> CommandContext:
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content=raw)
    loop = SimpleNamespace(context=SimpleNamespace(memory=MemoryStore(tmp_path)))
    return CommandContext(msg=msg, session=None, key=msg.session_key, raw=raw, args=args, loop=loop)


@pytest.mark.asyncio
async def test_dream_no_history_explains_how_to_create_input(tmp_path) -> None:
    ctx, bus = _make_dream_ctx(tmp_path)

    immediate = await cmd_dream(ctx)
    await asyncio.sleep(0)

    assert immediate.content == "Dreaming..."
    assert len(bus.outbound) == 1
    content = bus.outbound[0].content
    assert "Dream has no conversation history to process yet." in content
    assert "`memory/history.jsonl`" in content
    assert "idle auto-compact" in content
    assert "Dream cursor" in content
    assert "agents.defaults.idleCompactAfterMinutes" in content
    assert "/dream-prompt" in content


@pytest.mark.asyncio
async def test_dream_internal_run_silences_progress(tmp_path) -> None:
    msg = InboundMessage(channel="feishu", sender_id="u1", chat_id="chat1", content="/dream")
    store = _FakeStore(_FakeGit(initialized=False), dream_prompt_result=("dream prompt", 123))
    bus = _FakeBus()
    calls = []

    async def process_direct(*args, **kwargs):
        calls.append((args, kwargs))
        return OutboundMessage(
            channel="cli",
            chat_id="direct",
            content="done",
            metadata={"_stop_reason": "completed"},
        )

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    loop = SimpleNamespace(
        bus=bus,
        context=SimpleNamespace(memory=store, timezone="UTC"),
        sessions=SimpleNamespace(sessions_dir=sessions_dir),
        process_direct=process_direct,
    )
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/dream", args="", loop=loop)

    await cmd_dream(ctx)
    await asyncio.sleep(0)

    assert len(calls) == 1
    assert callable(calls[0][1]["on_progress"])


@pytest.mark.asyncio
async def test_dream_log_latest_is_more_user_friendly() -> None:
    commit = CommitInfo(sha="abcd1234", message="dream: 2026-04-04, 2 change(s)", timestamp="2026-04-04 12:00")
    diff = (
        "diff --git a/SOUL.md b/SOUL.md\n"
        "--- a/SOUL.md\n"
        "+++ b/SOUL.md\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    git = _FakeGit(commits=[commit], diff_map={commit.sha: (commit, diff)})

    out = await cmd_dream_log(_make_ctx("/dream-log", git))

    assert "## Dream Update" in out.content
    assert "Here is the latest Dream memory change." in out.content
    assert "- Commit: `abcd1234`" in out.content
    assert "- Changed files: `SOUL.md`" in out.content
    assert "Use `/dream-restore abcd1234` to undo this change." in out.content
    assert "```diff" in out.content


@pytest.mark.asyncio
async def test_dream_log_missing_commit_guides_user() -> None:
    git = _FakeGit(diff_map={})

    out = await cmd_dream_log(_make_ctx("/dream-log deadbeef", git, args="deadbeef"))

    assert "Couldn't find Dream change `deadbeef`." in out.content
    assert "Use `/dream-restore` to list recent versions" in out.content


@pytest.mark.asyncio
async def test_dream_log_before_first_run_is_clear() -> None:
    git = _FakeGit(initialized=False)

    out = await cmd_dream_log(_make_ctx("/dream-log", git, last_dream_cursor=0))

    assert "Dream has not run yet." in out.content
    assert "Run `/dream`" in out.content
    assert "/dream-prompt" in out.content


@pytest.mark.asyncio
async def test_dream_log_without_saved_versions_mentions_prompt_command() -> None:
    git = _FakeGit(initialized=True, commits=[])

    out = await cmd_dream_log(_make_ctx("/dream-log", git))

    assert "Dream memory has no saved versions yet." in out.content
    assert "/dream-prompt" in out.content


@pytest.mark.asyncio
async def test_dream_prompt_reports_default_prompt(tmp_path) -> None:
    out = await cmd_dream_prompt(_make_dream_prompt_ctx(tmp_path))

    assert "Dream prompt: bundled default" in out.content
    assert "prompts" in out.content
    assert "dream.md" in out.content
    assert "/dream-prompt init" in out.content


@pytest.mark.asyncio
async def test_dream_prompt_init_copies_default_prompt(tmp_path) -> None:
    ctx = _make_dream_prompt_ctx(tmp_path, "/dream-prompt init", "init")

    out = await cmd_dream_prompt(ctx)

    prompt_file = tmp_path / "prompts" / "dream.md"
    assert "Created Dream prompt override" in out.content
    assert prompt_file.read_text(encoding="utf-8") == MemoryStore.default_dream_prompt() + "\n"


@pytest.mark.asyncio
async def test_dream_prompt_init_does_not_overwrite_existing_prompt(tmp_path) -> None:
    prompt_file = tmp_path / "prompts" / "dream.md"
    prompt_file.parent.mkdir()
    prompt_file.write_text("custom", encoding="utf-8")
    ctx = _make_dream_prompt_ctx(tmp_path, "/dream-prompt init", "init")

    out = await cmd_dream_prompt(ctx)

    assert "already exists" in out.content
    assert prompt_file.read_text(encoding="utf-8") == "custom"


def test_dream_prompt_command_in_help_and_palette() -> None:
    palette = builtin_command_palette()

    assert any(
        item["command"] == "/dream-prompt" and item["arg_hint"] == "[init]"
        for item in palette
    )
    assert "/dream-prompt [init]" in build_help_text()


@pytest.mark.asyncio
async def test_dream_restore_lists_versions_with_next_steps() -> None:
    commits = [
        CommitInfo(sha="abcd1234", message="dream: latest", timestamp="2026-04-04 12:00"),
        CommitInfo(sha="bbbb2222", message="dream: older", timestamp="2026-04-04 08:00"),
    ]
    git = _FakeGit(commits=commits)

    out = await cmd_dream_restore(_make_ctx("/dream-restore", git))

    assert "## Dream Restore" in out.content
    assert "Choose a Dream memory version to restore." in out.content
    assert "`abcd1234` 2026-04-04 12:00 - dream: latest" in out.content
    assert "Preview a version with `/dream-log <sha>`" in out.content
    assert "Restore a version with `/dream-restore <sha>`." in out.content


@pytest.mark.asyncio
async def test_dream_restore_success_mentions_files_and_followup() -> None:
    commit = CommitInfo(sha="abcd1234", message="dream: latest", timestamp="2026-04-04 12:00")
    diff = (
        "diff --git a/SOUL.md b/SOUL.md\n"
        "--- a/SOUL.md\n"
        "+++ b/SOUL.md\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
        "diff --git a/memory/MEMORY.md b/memory/MEMORY.md\n"
        "--- a/memory/MEMORY.md\n"
        "+++ b/memory/MEMORY.md\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    git = _FakeGit(
        diff_map={commit.sha: (commit, diff)},
        revert_result="eeee9999",
    )

    out = await cmd_dream_restore(_make_ctx("/dream-restore abcd1234", git, args="abcd1234"))

    assert "Restored Dream memory to the state before `abcd1234`." in out.content
    assert "- New safety commit: `eeee9999`" in out.content
    assert "- Restored files: `SOUL.md`, `memory/MEMORY.md`" in out.content
    assert "Use `/dream-log eeee9999` to inspect the restore diff." in out.content
