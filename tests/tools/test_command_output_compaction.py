from __future__ import annotations

import json

from nanobot.agent.tools.command_output_compaction import compact_command_output


def test_compact_command_output_leaves_small_output_unchanged():
    result = compact_command_output(
        command="echo hello",
        stdout="hello\n",
        stderr="",
        exit_code=0,
        max_chars=10_000,
    )

    assert result == "hello\nExit code: 0"


def test_compact_command_output_summarizes_large_json():
    payload = [{"id": i, "name": f"item-{i}", "nested": {"value": i}} for i in range(500)]

    result = compact_command_output(
        command="curl https://api.example.test/items",
        stdout=json.dumps(payload),
        stderr="",
        exit_code=0,
        max_chars=4_000,
    )

    assert "command output compacted" in result
    assert '"type": "array"' in result
    assert '"items": 500' in result
    assert "Exit code: 0" in result
    assert len(result) < 4_500


def test_compact_command_output_focuses_lint_diagnostics():
    lines = [f"src/module_{i}.py:{i}:1: E999 example lint failure" for i in range(250)]
    lines.extend(f"noise line {i}" for i in range(2000))

    result = compact_command_output(
        command="ruff check src",
        stdout="\n".join(lines),
        stderr="",
        exit_code=1,
        max_chars=5_000,
    )

    assert "command output compacted" in result
    assert "src/module_0.py:0:1" in result
    assert "noise line 1999" not in result
    assert "Exit code: 1" in result


def test_compact_command_output_summarizes_git_diff():
    diff = "\n".join(
        [
            "diff --git a/a.py b/a.py",
            "index 111..222 100644",
            "--- a/a.py",
            "+++ b/a.py",
            "@@ -1,3 +1,3 @@",
        ]
        + [f"-old line {i}\n+new line {i}" for i in range(500)]
    )

    result = compact_command_output(
        command="git diff",
        stdout=diff,
        stderr="",
        exit_code=0,
        max_chars=3_000,
    )

    assert "Changed files: 1" in result
    assert "- a.py" in result
    assert "@@ -1,3 +1,3 @@" in result
    assert "Exit code: 0" in result
