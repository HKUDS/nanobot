import os
from typing import Any

import pytest

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.shell import ExecTool
from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import TelegramConfig


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


class DummyChannel(BaseChannel):
    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def send(self, msg: OutboundMessage) -> None:
        _ = msg


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


def test_guard_blocks_python_rmtree_script() -> None:
    tool = ExecTool()
    result = tool._guard_command(
        "python -c \"import shutil; shutil.rmtree('tmp', ignore_errors=True)\"",
        os.getcwd(),
    )
    assert result is not None
    assert "blocked" in result.lower()


def test_guard_blocks_wrapper_interpreter_script() -> None:
    tool = ExecTool()
    result = tool._guard_command(
        "uv run python -c \"import os; os.remove('x.txt')\"",
        os.getcwd(),
    )
    assert result is not None
    assert "blocked" in result.lower()


def test_guard_allows_non_destructive_python_script() -> None:
    tool = ExecTool()
    result = tool._guard_command("python -c \"print('ok')\"", os.getcwd())
    assert result is None


def test_guard_blocks_nonexistent_python_script_file() -> None:
    tool = ExecTool()
    result = tool._guard_command("python cleanup.py", os.getcwd())
    assert result is not None
    assert "blocked" in result.lower()


def test_guard_blocks_destructive_python_script_file(tmp_path) -> None:
    script = tmp_path / "wipe.py"
    script.write_text("import os\nos.remove('x.txt')\n", encoding="utf-8")

    tool = ExecTool()
    result = tool._guard_command(f'python "{script}"', os.getcwd())
    assert result is not None
    assert "blocked" in result.lower()


def test_guard_allows_safe_python_script_file(tmp_path) -> None:
    script = tmp_path / "safe.py"
    script.write_text("print('ok')\n", encoding="utf-8")

    tool = ExecTool()
    result = tool._guard_command(f'python "{script}"', os.getcwd())
    assert result is None


def test_is_allowed_denies_when_allowlist_empty_by_default() -> None:
    channel = DummyChannel(TelegramConfig(), MessageBus())
    assert channel.is_allowed("123") is False


def test_is_allowed_allows_when_public_access_enabled() -> None:
    channel = DummyChannel(TelegramConfig(public_access=True), MessageBus())
    assert channel.is_allowed("123") is True


@pytest.mark.asyncio
async def test_handle_message_is_dropped_when_not_allowed() -> None:
    channel = DummyChannel(TelegramConfig(), MessageBus())
    await channel._handle_message(
        sender_id="123",
        chat_id="c1",
        content="hello",
    )
    assert channel.bus.inbound_size == 0
