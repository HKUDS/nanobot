from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from dulwich import porcelain

from nanobot.agent.memory import MemoryStore
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.outbound_events import CommandResultEvent
from nanobot.command.application import build_help_text, builtin_command_palette
from nanobot.command.builtin import (
    cmd_dream,
    cmd_dream_log,
    cmd_dream_prompt,
    cmd_dream_restore,
)
from nanobot.command.results import message_text
from nanobot.command.router import CommandContext
from nanobot.session.manager import SessionManager
from nanobot.utils.gitstore import CommitInfo


class _FakeStore:
    def __init__(
        self,
        git,
        last_dream_cursor: int = 1,
        dream_prompt_result=None,
    ):
        self.git = git
        self._last_dream_cursor = last_dream_cursor
        self._dream_prompt_result = dream_prompt_result
        self.compact_history_called = False
        self.dream_lock = asyncio.Lock()

    def get_last_dream_cursor(self) -> int:
        return self._last_dream_cursor

    def build_dream_prompt(self):
        if self._dream_prompt_result and self._last_dream_cursor < self._dream_prompt_result[1]:
            return self._dream_prompt_result
        return None

    def build_dream_tools(self):
        return None

    def set_last_dream_cursor(self, value: int) -> None:
        self._last_dream_cursor = value

    def dream_content_diff(self) -> str:
        return ""

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
        self.revert_calls: list[tuple[str, str | None]] = []

    def is_initialized(self) -> bool:
        return self._initialized

    def log(
        self,
        max_entries: int = 20,
        message_prefix: str | None = None,
    ) -> list[CommitInfo]:
        commits = self._commits
        if message_prefix is not None:
            commits = [c for c in commits if c.message.startswith(message_prefix)]
        return commits[:max_entries]

    def show_commit_diff(
        self,
        sha: str,
        max_entries: int = 20,
        message_prefix: str | None = None,
    ):
        result = self._diff_map.get(sha)
        if result and message_prefix is not None and not result[0].message.startswith(message_prefix):
            return None
        return result

    def revert(self, sha: str, *, message_prefix: str | None = None) -> str | None:
        self.revert_calls.append((sha, message_prefix))
        return self._revert_result

    def auto_commit(self, message: str) -> str | None:
        return None


class _FakeBus:
    def __init__(self):
        self.outbound = []

    async def publish_outbound(self, message):
        self.outbound.append(message)


def _make_sessions(tmp_path) -> SessionManager:
    return SessionManager(
        tmp_path / "workspace",
        sessions_root=tmp_path / "runtime",
    )


def _make_ctx(raw: str, git: _FakeGit, *, args: str = "", last_dream_cursor: int = 1) -> CommandContext:
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content=raw)
    store = _FakeStore(git, last_dream_cursor=last_dream_cursor)
    loop = SimpleNamespace(consolidator=SimpleNamespace(store=store))
    return CommandContext(msg=msg, session=None, key=msg.session_key, raw=raw, args=args, loop=loop)


def _make_dream_ctx(tmp_path) -> tuple[CommandContext, _FakeBus]:
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/dream")
    store = _FakeStore(_FakeGit(initialized=False), dream_prompt_result=None)
    bus = _FakeBus()
    loop = SimpleNamespace(
        bus=bus,
        context=SimpleNamespace(memory=store, timezone="UTC"),
        sessions=_make_sessions(tmp_path),
    )
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/dream", args="", loop=loop)
    return ctx, bus


def _make_dream_prompt_ctx(tmp_path, raw: str = "/dream-prompt", args: str = "") -> CommandContext:
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content=raw)
    loop = SimpleNamespace(context=SimpleNamespace(memory=MemoryStore(tmp_path)))
    return CommandContext(msg=msg, session=None, key=msg.session_key, raw=raw, args=args, loop=loop)


async def _run_dream_command(ctx: CommandContext) -> OutboundMessage:
    before = asyncio.all_tasks()
    ctx.loop.schedule_background = asyncio.create_task
    immediate = await cmd_dream(ctx)
    assert ctx.after_reply is not None
    ctx.after_reply()
    try:
        await asyncio.gather(*(asyncio.all_tasks() - before))
    finally:
        await ctx.loop.sessions.state.aclose()
    return immediate


@pytest.mark.asyncio
async def test_dream_no_history_explains_how_to_create_input(tmp_path) -> None:
    ctx, bus = _make_dream_ctx(tmp_path)
    ctx.msg.metadata = {"slack": {"thread_ts": "123.456"}}

    immediate = await _run_dream_command(ctx)

    assert message_text(immediate) == "Dreaming..."
    assert immediate.metadata == ctx.msg.metadata
    assert isinstance(immediate.event, CommandResultEvent)
    assert immediate.event.command == "/dream" and immediate.event.notification_id is None
    [completion] = bus.outbound
    assert completion.metadata == ctx.msg.metadata
    assert isinstance(completion.event, CommandResultEvent)
    assert completion.event.command == "/dream"
    assert completion.event.notification_id and completion.event.notification_id.startswith("command-result:")
    content = message_text(completion)
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
    progress_sentinel = "private Dream progress sentinel"

    async def process_direct(*args, **kwargs):
        calls.append((args, kwargs))
        await kwargs["on_progress"](progress_sentinel)
        await kwargs["on_progress"](
            "",
            tool_events=[{"phase": "start", "name": "edit_file", "hint": progress_sentinel}],
        )
        return OutboundMessage(
            channel="cli",
            chat_id="direct",
            content="done",
            metadata={"_stop_reason": "completed"},
        )

    dream_runtime = object()
    loop = SimpleNamespace(
        bus=bus,
        context=SimpleNamespace(memory=store, timezone="UTC"),
        sessions=_make_sessions(tmp_path),
        process_direct=process_direct,
        dream_runtime=lambda: dream_runtime,
    )
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/dream", args="", loop=loop)

    immediate = await _run_dream_command(ctx)

    assert message_text(immediate) == "Dreaming..."
    assert (immediate.channel, immediate.chat_id) == ("feishu", "chat1")
    assert len(calls) == 1
    assert calls[0][1]["runtime"] is dream_runtime
    assert len(bus.outbound) == 1
    completion = bus.outbound[0]
    assert (completion.channel, completion.chat_id) == ("feishu", "chat1")
    assert message_text(completion).startswith("Dream completed")
    assert progress_sentinel not in message_text(completion)


@pytest.mark.parametrize("command,handler", [("/dream-log", cmd_dream_log), ("/dream-restore", cmd_dream_restore)])
@pytest.mark.parametrize("initialized", [False, True])
async def test_dream_inspection_replies_preserve_topic_routing(command, handler, initialized) -> None:
    ctx = _make_ctx(command, _FakeGit(initialized=initialized))
    ctx.msg.metadata = {"message_thread_id": 12, "message_id": 34}

    reply = await handler(ctx)

    assert reply.metadata == ctx.msg.metadata


@pytest.mark.parametrize("completed", [True, False])
async def test_dream_command_reports_outcome_and_versions_only_real_edits(tmp_path, completed) -> None:
    ctx, bus = _make_dream_ctx(tmp_path)
    store = MemoryStore(ctx.loop.sessions.workspace)
    assert store.git.init()
    versions = store.git.log()
    cursor = store.append_history("A confirmed finding")

    async def process_direct(prompt, **kwargs):
        if not completed:
            store.write_memory("A partial update")
        return OutboundMessage(
            channel="cli", chat_id="direct", content="done",
            metadata={"_stop_reason": "completed" if completed else "length"},
        )

    ctx.loop.context.memory = store
    ctx.loop.process_direct = process_direct
    ctx.loop.dream_runtime = lambda: None
    await _run_dream_command(ctx)

    if completed:
        assert "no memory changes" in message_text(bus.outbound[0])
        assert store.get_last_dream_cursor() == cursor
        assert store.git.log() == versions
    else:
        assert "did not complete" in message_text(bus.outbound[0])
        assert store.get_last_dream_cursor() == 0
        assert store.read_memory() == "A partial update"
        assert store.git.log()[0] != versions[0]


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

    assert "## Dream Update" in message_text(out)
    assert "Here is the latest Dream memory change." in message_text(out)
    assert "- Commit: `abcd1234`" in message_text(out)
    assert "- Changed files: `SOUL.md`" in message_text(out)
    assert "Use `/dream-restore abcd1234` to undo this change." in message_text(out)
    assert "```diff" in message_text(out)


@pytest.mark.asyncio
async def test_dream_log_localizes_summary_without_changing_diff() -> None:
    commit = CommitInfo(sha="abcd1234", message="dream: edit", timestamp="2026-04-04 12:00")
    diff = "diff --git a/SOUL.md b/SOUL.md\n+preserve {sha} and trailing spaces  \n\n"
    ctx = _make_ctx("/dream-log abcd1234", _FakeGit(diff_map={commit.sha: (commit, diff)}), args=commit.sha)
    ctx.msg.metadata = {"locale": "ja"}

    out = await cmd_dream_log(ctx)

    assert isinstance(out.event, CommandResultEvent) and out.event.command == "/dream-log"
    assert "選択した" in message_text(out) and f"```diff\n{diff}```" in message_text(out)
    assert out.event.parts[-1] == {"text": f"```diff\n{diff}```"}


@pytest.mark.asyncio
async def test_dream_log_latest_skips_non_dream_commit() -> None:
    backup = CommitInfo(
        sha="bbbb2222", message="backup: workspace snapshot", timestamp="2026-04-04 13:00",
    )
    dream = CommitInfo(
        sha="abcd1234", message="dream: latest", timestamp="2026-04-04 12:00",
    )
    diff = "diff --git a/SOUL.md b/SOUL.md\n"
    git = _FakeGit(
        commits=[backup, dream],
        diff_map={dream.sha: (dream, diff), backup.sha: (backup, "unrelated diff")},
    )

    out = await cmd_dream_log(_make_ctx("/dream-log", git))

    assert "`abcd1234`" in message_text(out)
    assert "`bbbb2222`" not in message_text(out)


@pytest.mark.asyncio
async def test_dream_log_missing_commit_guides_user() -> None:
    git = _FakeGit(diff_map={})

    out = await cmd_dream_log(_make_ctx("/dream-log deadbeef", git, args="deadbeef"))

    assert "Couldn't find Dream change `deadbeef`." in message_text(out)
    assert "Use `/dream-restore` to list recent versions" in message_text(out)


@pytest.mark.asyncio
async def test_dream_log_before_first_run_is_clear() -> None:
    git = _FakeGit(initialized=False)

    out = await cmd_dream_log(_make_ctx("/dream-log", git, last_dream_cursor=0))

    assert "Dream has not run yet." in message_text(out)
    assert "Run `/dream`" in message_text(out)
    assert "/dream-prompt" in message_text(out)


@pytest.mark.asyncio
async def test_dream_log_without_saved_versions_mentions_prompt_command() -> None:
    git = _FakeGit(initialized=True, commits=[])

    out = await cmd_dream_log(_make_ctx("/dream-log", git))

    assert "Dream memory has no saved versions yet." in message_text(out)
    assert "/dream-prompt" in message_text(out)


@pytest.mark.asyncio
async def test_dream_prompt_reports_default_prompt(tmp_path) -> None:
    out = await cmd_dream_prompt(_make_dream_prompt_ctx(tmp_path))

    assert "Dream memory instructions: nanobot default" in message_text(out)
    assert "prompts/dream.md" in message_text(out)
    assert str(tmp_path) not in message_text(out)
    assert "/dream-prompt init" in message_text(out)


@pytest.mark.asyncio
async def test_dream_prompt_init_copies_default_prompt(tmp_path) -> None:
    ctx = _make_dream_prompt_ctx(tmp_path, "/dream-prompt init", "init")

    out = await cmd_dream_prompt(ctx)

    prompt_file = tmp_path / "prompts" / "dream.md"
    assert "Created Dream memory instructions" in message_text(out)
    assert "prompts/dream.md" in message_text(out)
    assert str(tmp_path) not in message_text(out)
    assert "fully replaces nanobot's default Dream guide" in message_text(out)
    assert prompt_file.read_text(encoding="utf-8") == MemoryStore.default_dream_prompt() + "\n"


@pytest.mark.asyncio
async def test_dream_prompt_init_does_not_overwrite_existing_prompt(tmp_path) -> None:
    prompt_file = tmp_path / "prompts" / "dream.md"
    prompt_file.parent.mkdir()
    prompt_file.write_text("custom", encoding="utf-8")
    ctx = _make_dream_prompt_ctx(tmp_path, "/dream-prompt init", "init")

    out = await cmd_dream_prompt(ctx)

    assert "already exist" in message_text(out)
    assert "prompts/dream.md" in message_text(out)
    assert str(tmp_path) not in message_text(out)
    assert prompt_file.read_text(encoding="utf-8") == "custom"


@pytest.mark.asyncio
async def test_dream_prompt_init_recreates_empty_prompt(tmp_path) -> None:
    prompt_file = tmp_path / "prompts" / "dream.md"
    prompt_file.parent.mkdir()
    prompt_file.write_text("  \n", encoding="utf-8")
    ctx = _make_dream_prompt_ctx(tmp_path, "/dream-prompt init", "init")

    out = await cmd_dream_prompt(ctx)

    assert "Created Dream memory instructions" in message_text(out)
    assert prompt_file.read_text(encoding="utf-8") == MemoryStore.default_dream_prompt() + "\n"


def test_dream_prompt_command_in_help_and_palette() -> None:
    palette = builtin_command_palette()
    dream_prompt = next(item for item in palette if item["command"] == "/dream-prompt")

    assert dream_prompt["arg_hint"] == "[init]"
    assert dream_prompt["lifecycle"] == "side_channel"
    assert dream_prompt["accepts_args"] is True
    assert "/dream-prompt [init]" in build_help_text()


@pytest.mark.asyncio
async def test_dream_restore_lists_versions_with_next_steps() -> None:
    commits = [
        CommitInfo(sha="abcd1234", message="dream: latest", timestamp="2026-04-04 12:00"),
        CommitInfo(sha="cccc3333", message="backup: workspace", timestamp="2026-04-04 10:00"),
        CommitInfo(sha="bbbb2222", message="dream: older", timestamp="2026-04-04 08:00"),
    ]
    git = _FakeGit(commits=commits)

    out = await cmd_dream_restore(_make_ctx("/dream-restore", git))

    assert "## Dream Restore" in message_text(out)
    assert "Choose a Dream memory version to restore." in message_text(out)
    assert "`abcd1234` 2026-04-04 12:00 - dream: latest" in message_text(out)
    assert "`bbbb2222` 2026-04-04 08:00 - dream: older" in message_text(out)
    assert "backup: workspace" not in message_text(out)
    assert "Preview a version with `/dream-log <sha>`" in message_text(out)
    assert "Restore a version with `/dream-restore <sha>`." in message_text(out)


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

    assert "Restored Dream memory to the state before `abcd1234`." in message_text(out)
    assert "- New safety commit: `eeee9999`" in message_text(out)
    assert "- Restored files: `SOUL.md`, `memory/MEMORY.md`" in message_text(out)
    assert "Use `/dream-log eeee9999` to inspect the restore diff." in message_text(out)
    assert git.revert_calls == [("abcd1234", "dream:")]


@pytest.mark.asyncio
async def test_dream_restore_rejects_non_dream_commit_clearly() -> None:
    commit = CommitInfo(
        sha="cccc3333", message="backup: workspace", timestamp="2026-04-04 10:00",
    )
    git = _FakeGit(
        diff_map={commit.sha: (commit, "unrelated diff")},
        revert_result="eeee9999",
    )

    out = await cmd_dream_restore(_make_ctx("/dream-restore cccc3333", git, args="cccc3333"))

    assert "Only Dream memory versions can be restored." in message_text(out)
    assert "Use `/dream-restore` to list recent versions." in message_text(out)
    assert git.revert_calls == []


@pytest.mark.parametrize("dirty", ["untracked", "edited", "deleted", "staged", None])
async def test_dream_restore_preserves_uncommitted_memory(tmp_path, dirty) -> None:
    store = MemoryStore(tmp_path)
    assert store.git.init()
    store.wiki_dir.mkdir()
    page = store.wiki_dir / "known.md"
    page.write_bytes(b"before\n")
    store.write_memory("before")
    store.set_last_dream_cursor(1)
    assert store.git.auto_commit("dream: before")
    page.write_bytes(b"current\n")
    store.write_memory("current")
    store.set_last_dream_cursor(2)
    sha = store.git.auto_commit("dream: current")
    assert sha
    store.set_last_dream_cursor(3)  # A no-op Dream does not create a commit.

    draft = store.wiki_dir / "draft.md"
    if dirty == "untracked":
        draft.write_bytes(b"uncommitted draft\n")
    elif dirty == "edited":
        store.write_memory("user edit")
    elif dirty == "deleted":
        page.unlink()
    elif dirty == "staged":
        page.write_bytes(b"staged page\n")
        porcelain.add(str(tmp_path), paths=[str(page)])
        page.write_bytes(b"current\n")  # Only the index differs from HEAD.

    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content=f"/dream-restore {sha}")
    loop = SimpleNamespace(consolidator=SimpleNamespace(store=store))
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw=msg.content, args=sha, loop=loop)
    out = await cmd_dream_restore(ctx)

    if dirty is None:
        assert "Restored Dream memory" in message_text(out)
        assert store.read_memory() == "before"
        assert store.get_last_dream_cursor() == 1
        assert page.read_bytes() == b"before\n"
    else:
        assert "Couldn't restore" in message_text(out)
        if dirty == "staged":
            assert "staged changes" in message_text(out)
        elif dirty == "deleted":
            assert "`memory/wiki/known.md`" in message_text(out)
        assert "Commit or undo your changes" in message_text(out)
        assert store.git.log()[0].sha == sha
        assert store.get_last_dream_cursor() == 3
        assert store.read_memory() == ("user edit" if dirty == "edited" else "current")
        if dirty == "deleted":
            assert not page.exists()
        else:
            assert page.read_bytes() == b"current\n"
        if dirty == "untracked":
            assert draft.read_bytes() == b"uncommitted draft\n"
        if dirty == "staged":
            assert porcelain.get_tree_changes(str(tmp_path))["modify"] == [b"memory/wiki/known.md"]
