from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.shell import ExecTool


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


def test_exec_extract_absolute_paths_keeps_full_windows_path() -> None:
    cmd = r"type C:\user\workspace\txt"
    paths = ExecTool._extract_absolute_paths(cmd)
    assert paths == [r"C:\user\workspace\txt"]


def test_exec_extract_absolute_paths_captures_windows_drive_root_path() -> None:
    """Windows drive root paths like `E:\\` must be extracted for workspace guarding."""
    # Note: raw strings cannot end with a single backslash.
    cmd = "dir E:\\"
    paths = ExecTool._extract_absolute_paths(cmd)
    assert paths == ["E:\\"]


def test_exec_extract_absolute_paths_ignores_relative_posix_segments() -> None:
    cmd = ".venv/bin/python script.py"
    paths = ExecTool._extract_absolute_paths(cmd)
    assert "/bin/python" not in paths


def test_exec_extract_absolute_paths_captures_posix_absolute_paths() -> None:
    cmd = "cat /tmp/data.txt > /tmp/out.txt"
    paths = ExecTool._extract_absolute_paths(cmd)
    assert "/tmp/data.txt" in paths
    assert "/tmp/out.txt" in paths


def test_exec_extract_absolute_paths_captures_home_paths() -> None:
    cmd = "cat ~/.nanobot/config.json > ~/out.txt"
    paths = ExecTool._extract_absolute_paths(cmd)
    assert "~/.nanobot/config.json" in paths
    assert "~/out.txt" in paths


def test_exec_extract_absolute_paths_captures_quoted_paths() -> None:
    cmd = 'cat "/tmp/data.txt" "~/.nanobot/config.json"'
    paths = ExecTool._extract_absolute_paths(cmd)
    assert "/tmp/data.txt" in paths
    assert "~/.nanobot/config.json" in paths


def test_exec_guard_blocks_home_path_outside_workspace(tmp_path) -> None:
    tool = ExecTool(restrict_to_workspace=True)
    error = tool._guard_command("cat ~/.nanobot/config.json", str(tmp_path))
    assert error == "Error: Command blocked by safety guard (path outside working dir)"


def test_exec_guard_blocks_quoted_home_path_outside_workspace(tmp_path) -> None:
    tool = ExecTool(restrict_to_workspace=True)
    error = tool._guard_command('cat "~/.nanobot/config.json"', str(tmp_path))
    assert error == "Error: Command blocked by safety guard (path outside working dir)"


def test_exec_guard_allows_media_path_outside_workspace(tmp_path, monkeypatch) -> None:
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    media_file = media_dir / "photo.jpg"
    media_file.write_text("ok", encoding="utf-8")

    monkeypatch.setattr("nanobot.agent.tools.shell.get_media_dir", lambda: media_dir)

    tool = ExecTool(restrict_to_workspace=True)
    error = tool._guard_command(f'cat "{media_file}"', str(tmp_path / "workspace"))
    assert error is None


def test_exec_guard_blocks_windows_drive_root_outside_workspace(monkeypatch) -> None:
    import nanobot.agent.tools.shell as shell_mod

    class FakeWindowsPath:
        def __init__(self, raw: str) -> None:
            self.raw = raw.rstrip("\\") + ("\\" if raw.endswith("\\") else "")

        def resolve(self) -> "FakeWindowsPath":
            return self

        def expanduser(self) -> "FakeWindowsPath":
            return self

        def is_absolute(self) -> bool:
            return len(self.raw) >= 3 and self.raw[1:3] == ":\\"

        @property
        def parents(self) -> list["FakeWindowsPath"]:
            if not self.is_absolute():
                return []
            trimmed = self.raw.rstrip("\\")
            if len(trimmed) <= 2:
                return []
            idx = trimmed.rfind("\\")
            if idx <= 2:
                return [FakeWindowsPath(trimmed[:2] + "\\")]
            parent = FakeWindowsPath(trimmed[:idx])
            return [parent, *parent.parents]

        def __eq__(self, other: object) -> bool:
            return isinstance(other, FakeWindowsPath) and self.raw.lower() == other.raw.lower()

    monkeypatch.setattr(shell_mod, "Path", FakeWindowsPath)

    tool = ExecTool(restrict_to_workspace=True)
    error = tool._guard_command("dir E:\\", "E:\\workspace")
    assert error == "Error: Command blocked by safety guard (path outside working dir)"


# --- cast_params tests ---


class CastTestTool(Tool):
    """Minimal tool for testing cast_params."""

    def __init__(self, schema: dict[str, Any]) -> None:
        self._schema = schema

    @property
    def name(self) -> str:
        return "cast_test"

    @property
    def description(self) -> str:
        return "test tool for casting"

    @property
    def parameters(self) -> dict[str, Any]:
        return self._schema

    async def execute(self, **kwargs: Any) -> str:
        return "ok"


def test_cast_params_string_to_int() -> None:
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {"count": {"type": "integer"}},
        }
    )
    result = tool.cast_params({"count": "42"})
    assert result["count"] == 42
    assert isinstance(result["count"], int)


def test_cast_params_string_to_number() -> None:
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {"rate": {"type": "number"}},
        }
    )
    result = tool.cast_params({"rate": "3.14"})
    assert result["rate"] == 3.14
    assert isinstance(result["rate"], float)


def test_cast_params_string_to_bool() -> None:
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {"enabled": {"type": "boolean"}},
        }
    )
    assert tool.cast_params({"enabled": "true"})["enabled"] is True
    assert tool.cast_params({"enabled": "false"})["enabled"] is False
    assert tool.cast_params({"enabled": "1"})["enabled"] is True


def test_cast_params_array_items() -> None:
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {
                "nums": {"type": "array", "items": {"type": "integer"}},
            },
        }
    )
    result = tool.cast_params({"nums": ["1", "2", "3"]})
    assert result["nums"] == [1, 2, 3]


def test_cast_params_nested_object() -> None:
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {
                "config": {
                    "type": "object",
                    "properties": {
                        "port": {"type": "integer"},
                        "debug": {"type": "boolean"},
                    },
                },
            },
        }
    )
    result = tool.cast_params({"config": {"port": "8080", "debug": "true"}})
    assert result["config"]["port"] == 8080
    assert result["config"]["debug"] is True


def test_cast_params_bool_not_cast_to_int() -> None:
    """Booleans should not be silently cast to integers."""
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {"count": {"type": "integer"}},
        }
    )
    result = tool.cast_params({"count": True})
    assert result["count"] is True
    errors = tool.validate_params(result)
    assert any("count should be integer" in e for e in errors)


def test_cast_params_preserves_empty_string() -> None:
    """Empty strings should be preserved for string type."""
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }
    )
    result = tool.cast_params({"name": ""})
    assert result["name"] == ""


def test_cast_params_bool_string_false() -> None:
    """Test that 'false', '0', 'no' strings convert to False."""
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {"flag": {"type": "boolean"}},
        }
    )
    assert tool.cast_params({"flag": "false"})["flag"] is False
    assert tool.cast_params({"flag": "False"})["flag"] is False
    assert tool.cast_params({"flag": "0"})["flag"] is False
    assert tool.cast_params({"flag": "no"})["flag"] is False
    assert tool.cast_params({"flag": "NO"})["flag"] is False


def test_cast_params_bool_string_invalid() -> None:
    """Invalid boolean strings should not be cast."""
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {"flag": {"type": "boolean"}},
        }
    )
    # Invalid strings should be preserved (validation will catch them)
    result = tool.cast_params({"flag": "random"})
    assert result["flag"] == "random"
    result = tool.cast_params({"flag": "maybe"})
    assert result["flag"] == "maybe"


def test_cast_params_invalid_string_to_int() -> None:
    """Invalid strings should not be cast to integer."""
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {"count": {"type": "integer"}},
        }
    )
    result = tool.cast_params({"count": "abc"})
    assert result["count"] == "abc"  # Original value preserved
    result = tool.cast_params({"count": "12.5.7"})
    assert result["count"] == "12.5.7"


def test_cast_params_invalid_string_to_number() -> None:
    """Invalid strings should not be cast to number."""
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {"rate": {"type": "number"}},
        }
    )
    result = tool.cast_params({"rate": "not_a_number"})
    assert result["rate"] == "not_a_number"


def test_validate_params_bool_not_accepted_as_number() -> None:
    """Booleans should not pass number validation."""
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {"rate": {"type": "number"}},
        }
    )
    errors = tool.validate_params({"rate": False})
    assert any("rate should be number" in e for e in errors)


def test_cast_params_none_values() -> None:
    """Test None handling for different types."""
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "count": {"type": "integer"},
                "items": {"type": "array"},
                "config": {"type": "object"},
            },
        }
    )
    result = tool.cast_params(
        {
            "name": None,
            "count": None,
            "items": None,
            "config": None,
        }
    )
    # None should be preserved for all types
    assert result["name"] is None
    assert result["count"] is None
    assert result["items"] is None
    assert result["config"] is None


def test_cast_params_single_value_not_auto_wrapped_to_array() -> None:
    """Single values should NOT be automatically wrapped into arrays."""
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {"items": {"type": "array"}},
        }
    )
    # Non-array values should be preserved (validation will catch them)
    result = tool.cast_params({"items": 5})
    assert result["items"] == 5  # Not wrapped to [5]
    result = tool.cast_params({"items": "text"})
    assert result["items"] == "text"  # Not wrapped to ["text"]


# --- ExecTool enhancement tests ---


async def test_exec_always_returns_exit_code() -> None:
    """Exit code should appear in output even on success (exit 0)."""
    tool = ExecTool()
    result = await tool.execute(command="echo hello")
    assert "Exit code: 0" in result
    assert "hello" in result


async def test_exec_head_tail_truncation() -> None:
    """Long output should preserve both head and tail."""
    tool = ExecTool()
    # Generate output that exceeds _MAX_OUTPUT (10_000 chars)
    # Use python to generate output to avoid command line length limits
    result = await tool.execute(
        command="python -c \"print('A' * 6000 + '\\n' + 'B' * 6000)\""
    )
    assert "chars truncated" in result
    # Head portion should start with As
    assert result.startswith("A")
    # Tail portion should end with the exit code which comes after Bs
    assert "Exit code:" in result


async def test_exec_timeout_parameter() -> None:
    """LLM-supplied timeout should override the constructor default."""
    tool = ExecTool(timeout=60)
    # A very short timeout should cause the command to be killed
    result = await tool.execute(command="sleep 10", timeout=1)
    assert "timed out" in result
    assert "1 seconds" in result


async def test_exec_timeout_capped_at_max() -> None:
    """Timeout values above _MAX_TIMEOUT should be clamped."""
    tool = ExecTool()
    # Should not raise — just clamp to 600
    result = await tool.execute(command="echo ok", timeout=9999)
    assert "Exit code: 0" in result


# --- _resolve_type and nullable param tests ---


def test_resolve_type_simple_string() -> None:
    """Simple string type passes through unchanged."""
    assert Tool._resolve_type("string") == "string"


def test_resolve_type_union_with_null() -> None:
    """Union type ['string', 'null'] resolves to 'string'."""
    assert Tool._resolve_type(["string", "null"]) == "string"


def test_resolve_type_only_null() -> None:
    """Union type ['null'] resolves to None (no non-null type)."""
    assert Tool._resolve_type(["null"]) is None


def test_resolve_type_none_input() -> None:
    """None input passes through as None."""
    assert Tool._resolve_type(None) is None


def test_validate_nullable_param_accepts_string() -> None:
    """Nullable string param should accept a string value."""
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {"name": {"type": ["string", "null"]}},
        }
    )
    errors = tool.validate_params({"name": "hello"})
    assert errors == []


def test_validate_nullable_param_accepts_none() -> None:
    """Nullable string param should accept None."""
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {"name": {"type": ["string", "null"]}},
        }
    )
    errors = tool.validate_params({"name": None})
    assert errors == []


def test_validate_nullable_flag_accepts_none() -> None:
    """OpenAI-normalized nullable params should still accept None locally."""
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {"name": {"type": "string", "nullable": True}},
        }
    )
    errors = tool.validate_params({"name": None})
    assert errors == []


def test_cast_nullable_param_no_crash() -> None:
    """cast_params should not crash on nullable type (the original bug)."""
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {"name": {"type": ["string", "null"]}},
        }
    )
    result = tool.cast_params({"name": "hello"})
    assert result["name"] == "hello"
    result = tool.cast_params({"name": None})
    assert result["name"] is None
