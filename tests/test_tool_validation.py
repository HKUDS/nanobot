import json
from typing import Any

from nanobot.agent.memory import MemoryStore
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.events import InboundMessage
from nanobot.session.manager import SessionManager


class SampleTool(Tool):
    @property
    def name(self) -> str:
        return "sample"

    @property
    def description(self) -> str:
        return "sample tool"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 2},
                "count": {"type": "integer", "minimum": 1, "maximum": 10},
                "mode": {"type": "string", "enum": ["fast", "full"]},
                "meta": {
                    "type": "object",
                    "properties": {
                        "tag": {"type": "string"},
                        "flags": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["tag"],
                },
            },
            "required": ["query", "count"],
        }

    async def execute(self, **kwargs: Any) -> str:
        return "ok"


def test_validate_params_missing_required() -> None:
    tool = SampleTool()
    errors = tool.validate_params({"query": "hi"})
    assert "missing required count" in "; ".join(errors)


def test_validate_params_type_and_range() -> None:
    tool = SampleTool()
    errors = tool.validate_params({"query": "hi", "count": 0})
    assert any("count must be >= 1" in e for e in errors)

    errors = tool.validate_params({"query": "hi", "count": "2"})
    assert any("count should be integer" in e for e in errors)


def test_validate_params_enum_and_min_length() -> None:
    tool = SampleTool()
    errors = tool.validate_params({"query": "h", "count": 2, "mode": "slow"})
    assert any("query must be at least 2 chars" in e for e in errors)
    assert any("mode must be one of" in e for e in errors)


def test_validate_params_nested_object_and_array() -> None:
    tool = SampleTool()
    errors = tool.validate_params(
        {
            "query": "hi",
            "count": 2,
            "meta": {"flags": [1, "ok"]},
        }
    )
    assert any("missing required meta.tag" in e for e in errors)
    assert any("meta.flags[0] should be string" in e for e in errors)


def test_validate_params_ignores_unknown_fields() -> None:
    tool = SampleTool()
    errors = tool.validate_params({"query": "hi", "count": 2, "extra": "x"})
    assert errors == []


async def test_registry_returns_validation_error() -> None:
    reg = ToolRegistry()
    reg.register(SampleTool())
    result = await reg.execute("sample", {"query": "hi"})
    assert "Invalid parameters" in result


def test_memory_store_explicit_memory_flushes_immediately(tmp_path) -> None:
    store = MemoryStore(
        workspace=tmp_path,
        flush_every_updates=100,
        flush_interval_seconds=10_000,
        short_term_turns=8,
        pending_limit=8,
    )

    store.record_turn(
        session_key="cli:test",
        user_message="请记住以后都用中文回答",
        assistant_message="好的，我记住了。",
    )

    assert store.snapshot_file.exists()
    data = json.loads(store.snapshot_file.read_text(encoding="utf-8"))
    assert data["items"]
    assert any("中文" in item["text"] for item in data["items"])

    reloaded = MemoryStore(workspace=tmp_path)
    context = reloaded.get_memory_context(session_key="cli:test")
    assert "Long-term Memory (Snapshot)" in context


def test_memory_store_deferred_flush_and_short_term_context(tmp_path) -> None:
    store = MemoryStore(
        workspace=tmp_path,
        flush_every_updates=1000,
        flush_interval_seconds=10_000,
        short_term_turns=4,
        pending_limit=4,
    )

    store.remember("User prefers concise responses", immediate=False)
    assert not store.snapshot_file.exists()

    changed = store.flush(force=True)
    assert changed is True
    assert store.snapshot_file.exists()

    store.record_turn(
        session_key="cli:todo",
        user_message="todo: remind me to submit the PR tomorrow",
        assistant_message="I added it to pending items.",
    )
    ctx = store.get_memory_context(session_key="cli:todo")
    assert "Short-term Working Memory" in ctx
    assert "Pending Items" in ctx


def test_session_save_is_append_only(tmp_path) -> None:
    manager = SessionManager(
        workspace=tmp_path,
        compact_threshold_messages=1000,
        compact_threshold_bytes=10_000_000,
        compact_keep_messages=500,
    )

    session = manager.get_or_create("cli:test")
    session.add_message("user", "hello")
    session.add_message("assistant", "hi")
    manager.save(session)

    session_path = manager._get_session_path("cli:test")

    # Sentinel line should stay if save() appends instead of rewriting.
    with open(session_path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"_type": "sentinel", "value": 1}) + "\n")

    session.add_message("user", "second")
    session.add_message("assistant", "reply")
    manager.save(session)

    text = session_path.read_text(encoding="utf-8")
    assert '"_type": "sentinel"' in text


def test_session_compact_keeps_recent_messages(tmp_path) -> None:
    manager = SessionManager(
        workspace=tmp_path,
        compact_threshold_messages=6,
        compact_threshold_bytes=10_000_000,
        compact_keep_messages=4,
    )

    session = manager.get_or_create("cli:compact")
    for i in range(10):
        session.add_message("user", f"u{i}")
    manager.save(session)

    assert len(session.messages) == 4

    session_path = manager._get_session_path("cli:compact")
    lines = [line for line in session_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    # 1 metadata + 4 kept messages
    assert len(lines) == 5


def test_inbound_message_session_key_override() -> None:
    msg = InboundMessage(
        channel="telegram",
        sender_id="u1",
        chat_id="chat-1",
        content="hello",
        session_key_override="cli:custom",
    )
    assert msg.session_key == "cli:custom"


def test_memory_store_tool_feedback_learns_lessons(tmp_path) -> None:
    store = MemoryStore(workspace=tmp_path, self_improvement_enabled=True)
    changed = store.record_tool_feedback(
        session_key="cli:lesson",
        tool_name="read_file",
        result="Error: File not found: /tmp/missing.txt",
    )
    assert changed is True

    lessons = store.get_lessons_for_context(
        session_key="cli:lesson",
        current_message="read_file still fails",
    )
    assert lessons
    assert lessons[0]["trigger"] == "tool:read_file:error"
    assert "read_file" in lessons[0]["better_action"]

    context = store.get_memory_context(
        session_key="cli:lesson",
        current_message="read_file still fails",
    )
    assert "## Lessons" in context


def test_memory_store_user_feedback_learns_lessons(tmp_path) -> None:
    store = MemoryStore(workspace=tmp_path, self_improvement_enabled=True)
    changed = store.record_user_feedback(
        session_key="cli:feedback",
        user_message="不对，回答太长了，简短一点",
        previous_assistant="这是一个非常非常长的回答...",
    )
    assert changed is True

    lessons = store.get_lessons_for_context(
        session_key="cli:feedback",
        current_message="请给我更简短的回答",
    )
    assert lessons
    assert lessons[0]["trigger"] == "response:length"
    assert lessons[0]["confidence"] >= 2


def test_memory_store_lessons_compact_and_reset(tmp_path) -> None:
    store = MemoryStore(workspace=tmp_path, self_improvement_enabled=True, max_lessons=20)
    for i in range(6):
        store.learn_lesson(
            trigger=f"response:alignment:{i}",
            bad_action=f"bad{i}",
            better_action=f"better{i}",
            session_key="cli:compact",
            source="test",
            scope="session",
            confidence_delta=1,
            immediate=False,
        )

    removed = store.compact_lessons(max_lessons=3, auto_flush=False)
    assert removed >= 3

    status = store.get_status()
    assert status["lessons_count"] <= 3

    removed_all = store.reset_lessons()
    assert removed_all >= 1
    assert store.get_status()["lessons_count"] == 0
