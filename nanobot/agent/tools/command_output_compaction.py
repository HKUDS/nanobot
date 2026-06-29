"""Token-oriented compaction for shell command output.

The shell tool still executes the user's command normally.  This module only
reshapes large model-facing stdout/stderr payloads so routine command noise
does not crowd out useful context.
"""

from __future__ import annotations

import json
import re
import shlex
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_COMPACT_TRIGGER_CHARS = 8_000
MIN_COMPACT_TARGET_CHARS = 2_000
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
PROGRESS_RE = re.compile(r"\r|(?:^|\s)(?:\d{1,3}%|[=\-#>]{8,}|\d+(?:\.\d+)?\s*(?:kB|MB|GB)/s)")
FILE_LINE_RE = re.compile(r"(?:^|\s)([^\s:]+\.(?:py|js|jsx|ts|tsx|go|rs|rb|java|kt|cs|cpp|c|h|hpp|yaml|yml|json|toml|md)):(\d+)(?::(\d+))?")
DIFF_FILE_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$")
HUNK_RE = re.compile(r"^@@ .+ @@")

TEST_COMMANDS = {
    "pytest", "py.test", "unittest", "tox", "nox", "jest", "vitest", "mocha", "ava",
    "playwright", "cypress", "rspec", "rake", "go", "cargo", "dotnet", "mvn", "gradle",
    "gradlew", "phpunit", "bats", "ctest", "zig",
}
LINT_COMMANDS = {
    "ruff", "eslint", "mypy", "pyright", "tsc", "biome", "prettier", "black", "isort",
    "flake8", "pylint", "golangci-lint", "rubocop", "clippy", "shellcheck", "stylelint",
    "hadolint", "yamllint", "markdownlint", "swiftlint", "ktlint",
}
BUILD_COMMANDS = {
    "make", "cmake", "ninja", "npm", "pnpm", "yarn", "bun", "pip", "uv", "poetry", "hatch",
    "cargo", "go", "dotnet", "mvn", "gradle", "gradlew", "docker", "podman", "terraform",
    "pulumi", "webpack", "vite", "next", "tsup", "rollup", "esbuild", "bazel", "buck",
}
JSON_COMMANDS = {"jq", "curl", "http", "wget", "aws", "gcloud", "az", "kubectl", "gh", "glab"}
TABLE_COMMANDS = {"psql", "mysql", "sqlite3", "duckdb", "docker", "podman", "kubectl", "helm", "ps", "df", "du"}
LIST_COMMANDS = {"ls", "tree", "find", "fd", "rg", "grep", "ag", "ack", "wc"}
DIFF_COMMANDS = {"git", "diff", "delta"}


@dataclass(slots=True)
class CommandOutput:
    command: str
    stdout: str
    stderr: str
    exit_code: int | None
    max_chars: int

    @property
    def combined(self) -> str:
        return _combine(self.stdout, self.stderr, self.exit_code)


def compact_command_output(
    *,
    command: str,
    stdout: str,
    stderr: str,
    exit_code: int | None,
    max_chars: int,
) -> str:
    """Return compact model-facing output for a completed shell command."""
    output = CommandOutput(
        command=command,
        stdout=_strip_control_noise(stdout),
        stderr=_strip_control_noise(stderr),
        exit_code=exit_code,
        max_chars=max(max_chars, MIN_COMPACT_TARGET_CHARS),
    )
    combined = output.combined
    if len(combined) <= min(DEFAULT_COMPACT_TRIGGER_CHARS, output.max_chars):
        return combined or "(no output)"

    family = _command_family(command)
    compacted = _route_compactor(family, output)
    if compacted is None:
        compacted = _generic_compact(output.stdout, output.max_chars)
        if output.stderr.strip():
            compacted = _join_sections([compacted, _error_focused(output.stderr, output.max_chars // 3)])

    compacted = _fit(compacted, output.max_chars)
    if compacted == combined:
        compacted = _middle_truncate(combined, output.max_chars)

    header = (
        f"[command output compacted: {len(combined):,} -> {len(compacted):,} chars"
        f"; command={family or 'shell'}]"
    )
    return _join_sections([header, compacted, f"Exit code: {exit_code}"])


def _route_compactor(family: str | None, output: CommandOutput) -> str | None:
    text = output.stdout
    if _looks_like_json(text) or family in JSON_COMMANDS:
        compacted = _json_compact(text, output.max_chars)
        if compacted:
            return compacted
    if family == "git":
        return _git_compact(output.command, text, output.max_chars)
    if family in DIFF_COMMANDS or _looks_like_diff(text):
        return _diff_compact(text, output.max_chars)
    if family in TEST_COMMANDS or _looks_like_test_output(text):
        return _failure_focused(text, output.max_chars)
    if family in LINT_COMMANDS or _looks_like_lint_output(text):
        return _lint_compact(text, output.max_chars)
    if family in BUILD_COMMANDS:
        return _build_compact(text, output.max_chars)
    if output.exit_code not in (0, None):
        return _join_sections([
            _error_focused(output.stderr or text, output.max_chars // 2),
            _generic_compact(text, output.max_chars // 2) if text else "",
        ])
    if family in TABLE_COMMANDS or _looks_like_table(text):
        return _table_compact(text, output.max_chars)
    if family in LIST_COMMANDS:
        return _listing_compact(text, output.max_chars)
    return None


def _command_family(command: str) -> str | None:
    try:
        parts = shlex.split(command, posix=True)
    except ValueError:
        parts = command.split()
    while parts and ("=" in parts[0] and not parts[0].startswith("-")):
        key = parts[0].split("=", 1)[0]
        if not key.replace("_", "").isalnum():
            break
        parts.pop(0)
    while parts and parts[0] in {"sudo", "env", "command", "time", "nice", "nohup"}:
        parts.pop(0)
    if not parts:
        return None
    return Path(parts[0]).name.lower()


def _combine(stdout: str, stderr: str, exit_code: int | None) -> str:
    parts = []
    if stdout:
        parts.append(stdout.rstrip())
    if stderr.strip():
        parts.append(f"STDERR:\n{stderr.rstrip()}")
    parts.append(f"Exit code: {exit_code}")
    return "\n".join(parts)


def _strip_control_noise(text: str) -> str:
    if not text:
        return ""
    text = ANSI_RE.sub("", text.replace("\r\n", "\n"))
    lines = []
    for line in text.splitlines():
        if "\r" in line:
            line = line.split("\r")[-1]
        if PROGRESS_RE.search(line) and not any(word in line.lower() for word in _IMPORTANT_WORDS):
            continue
        lines.append(line.rstrip())
    return "\n".join(lines).strip()


_IMPORTANT_WORDS = ("error", "failed", "failure", "warning", "warn", "traceback", "exception")


def _generic_compact(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    json_summary = _json_compact(text, max_chars)
    if json_summary:
        return json_summary
    if _looks_like_table(text):
        return _table_compact(text, max_chars)
    return _join_sections([_dedupe_lines(text, max_chars // 2), _head_tail(text, max_chars // 2)])


def _json_compact(text: str, max_chars: int) -> str | None:
    stripped = text.strip()
    if not _looks_like_json(stripped):
        return None
    try:
        data = json.loads(stripped)
    except Exception:
        return None
    summary = _json_shape(data)
    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    return _fit(rendered, max_chars)


def _json_shape(value: Any, depth: int = 0) -> Any:
    if depth >= 3:
        return _json_leaf(value)
    if isinstance(value, dict):
        keys = list(value.keys())
        shaped = {str(k): _json_shape(value[k], depth + 1) for k in keys[:20]}
        if len(keys) > 20:
            shaped["..."] = f"{len(keys) - 20} more keys"
        return {"type": "object", "keys": len(keys), "sample": shaped}
    if isinstance(value, list):
        sample = [_json_shape(v, depth + 1) for v in value[:3]]
        return {"type": "array", "items": len(value), "sample": sample}
    return _json_leaf(value)


def _json_leaf(value: Any) -> Any:
    if isinstance(value, str):
        return value if len(value) <= 120 else value[:117] + "..."
    return value


def _git_compact(command: str, text: str, max_chars: int) -> str:
    lower = command.lower()
    if " diff" in lower or lower.startswith("git diff") or _looks_like_diff(text):
        return _diff_compact(text, max_chars)
    if " status" in lower:
        return _head_tail(text, max_chars, head=80, tail=20)
    if " log" in lower:
        return _head_tail(text, max_chars, head=60, tail=0)
    return _generic_compact(text, max_chars)


def _diff_compact(text: str, max_chars: int) -> str:
    files: list[str] = []
    kept: list[str] = []
    hunk_context = 0
    for line in text.splitlines():
        match = DIFF_FILE_RE.match(line)
        if match:
            files.append(match.group(2))
            kept.append(line)
            continue
        if HUNK_RE.match(line):
            kept.append(line)
            hunk_context = 8
            continue
        if hunk_context > 0 and (line.startswith(("+", "-")) or line.strip()):
            kept.append(line)
            hunk_context -= 1
    summary = [f"Changed files: {len(files)}"]
    summary.extend(f"- {path}" for path in files[:80])
    if len(files) > 80:
        summary.append(f"- ... {len(files) - 80} more files")
    return _fit(_join_sections(["\n".join(summary), "\n".join(kept)]), max_chars)


def _failure_focused(text: str, max_chars: int) -> str:
    lines = text.splitlines()
    important = _important_lines(lines)
    summary = _summary_lines(lines)
    if not important:
        return _head_tail(text, max_chars)
    return _fit(_join_sections(["Summary:", "\n".join(summary), "Failures/errors:", "\n".join(important)]), max_chars)


def _lint_compact(text: str, max_chars: int) -> str:
    lines = text.splitlines()
    by_file: Counter[str] = Counter()
    important: list[str] = []
    for line in lines:
        match = FILE_LINE_RE.search(line)
        if match:
            by_file[match.group(1)] += 1
            important.append(line.strip())
        elif any(word in line.lower() for word in _IMPORTANT_WORDS):
            important.append(line.strip())
    summary = [f"Files with diagnostics: {len(by_file)}"]
    summary.extend(f"- {path}: {count}" for path, count in by_file.most_common(40))
    return _fit(_join_sections(["\n".join(summary), "Diagnostics:", "\n".join(important[:300])]), max_chars)


def _build_compact(text: str, max_chars: int) -> str:
    lines = text.splitlines()
    important = _important_lines(lines)
    if important:
        return _fit(_join_sections(["Build diagnostics:", "\n".join(important), "Tail:", "\n".join(lines[-40:])]), max_chars)
    return _head_tail(text, max_chars, head=40, tail=60)


def _table_compact(text: str, max_chars: int) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) <= 80 and len(text) <= max_chars:
        return text
    head = lines[:30]
    tail = lines[-20:] if len(lines) > 50 else []
    omitted = max(0, len(lines) - len(head) - len(tail))
    middle = [f"... {omitted:,} rows omitted ..."] if omitted else []
    return _fit("\n".join(head + middle + tail), max_chars)


def _listing_compact(text: str, max_chars: int) -> str:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if len(lines) <= 120 and len(text) <= max_chars:
        return text
    suffix_counts = Counter(Path(line.split()[-1]).suffix or "[no suffix]" for line in lines if line.split())
    summary = [f"Entries: {len(lines)}"]
    summary.extend(f"- {suffix}: {count}" for suffix, count in suffix_counts.most_common(20))
    return _fit(_join_sections(["\n".join(summary), _head_tail("\n".join(lines), max_chars // 2)]), max_chars)


def _error_focused(text: str, max_chars: int) -> str:
    lines = text.splitlines()
    important = _important_lines(lines)
    return _fit("\n".join(important or lines[-80:]), max_chars)


def _important_lines(lines: list[str]) -> list[str]:
    kept: list[str] = []
    for idx, line in enumerate(lines):
        lower = line.lower()
        if any(word in lower for word in _IMPORTANT_WORDS) or FILE_LINE_RE.search(line):
            start = max(0, idx - 2)
            end = min(len(lines), idx + 4)
            kept.extend(lines[start:end])
    return _dedupe_preserve_order([line for line in kept if line.strip()])[:500]


def _summary_lines(lines: list[str]) -> list[str]:
    return [
        line.strip()
        for line in lines
        if line.strip() and any(token in line.lower() for token in ("passed", "failed", "error", "warning", "collected", "total", "summary"))
    ][:80]


def _dedupe_lines(text: str, max_chars: int) -> str:
    lines = _dedupe_preserve_order([line for line in text.splitlines() if line.strip()])
    return _fit("\n".join(lines), max_chars)


def _dedupe_preserve_order(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    kept: list[str] = []
    for line in lines:
        key = re.sub(r"\d+", "#", line.strip())
        if key in seen:
            continue
        seen.add(key)
        kept.append(line)
    return kept


def _looks_like_json(text: str) -> bool:
    stripped = text.strip()
    return len(stripped) >= 2 and stripped[0] in "[{" and stripped[-1] in "]}"


def _looks_like_diff(text: str) -> bool:
    return "diff --git " in text or "\n@@ " in text


def _looks_like_table(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 20:
        return False
    pipe_rows = sum(1 for line in lines[:50] if "|" in line)
    spaced_rows = sum(1 for line in lines[:50] if len(re.split(r"\s{2,}", line.strip())) >= 3)
    return pipe_rows >= 10 or spaced_rows >= 10


def _looks_like_test_output(text: str) -> bool:
    lower = text.lower()
    return " traceback " in lower or " failed" in lower or " failures" in lower or " tests passed" in lower


def _looks_like_lint_output(text: str) -> bool:
    return bool(FILE_LINE_RE.search(text)) and any(word in text.lower() for word in ("error", "warning", "lint"))


def _head_tail(text: str, max_chars: int, *, head: int = 80, tail: int = 80) -> str:
    lines = text.splitlines()
    if len(text) <= max_chars:
        return text
    head_lines = lines[:head]
    tail_lines = lines[-tail:] if tail else []
    omitted = max(0, len(lines) - len(head_lines) - len(tail_lines))
    return _fit("\n".join(head_lines + [f"... {omitted:,} lines omitted ..."] + tail_lines), max_chars)


def _fit(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else _middle_truncate(text, max_chars)


def _middle_truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    marker = f"\n\n... ({len(text) - max_chars:,} chars omitted by command-output compactor) ...\n\n"
    budget = max(0, max_chars - len(marker))
    head = budget // 2
    tail = budget - head
    return text[:head].rstrip() + marker + text[-tail:].lstrip()


def _join_sections(sections: list[str]) -> str:
    return "\n\n".join(section.strip() for section in sections if section and section.strip())
