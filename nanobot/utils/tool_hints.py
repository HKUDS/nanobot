from __future__ import annotations

import json
import re
from typing import Any, cast

from nanobot.providers.base import ToolCallRequest
from nanobot.utils.helpers import strip_think
from nanobot.utils.path import abbreviate_path

# Registry: tool_name -> (key_args, template, is_path, is_command)
_TOOL_FORMATS: dict[str, tuple[list[str], str, bool, bool]] = {
    "read_file":  (["path", "file_path"],              "read {}",     True,  False),
    "write_file": (["path", "file_path"],              "write {}",    True,  False),
    "edit":       (["file_path", "path"],              "edit {}",     True,  False),
    "find_files": (["query", "glob", "path"],           "find {}",     False, False),
    "grep":       (["pattern"],                        'grep "{}"',   False, False),
    "rg":         (["args"],                           "rg {}",       False, False),
    "exec":       (["command"],                        "$ {}",        False, True),
    "list_exec_sessions": ([],                          "exec sessions", False, False),
    "web_search": (["query"],                          'search "{}"', False, False),
    "x_search":   (["query"],                        'search X "{}"', False, False),
    "web_fetch":  (["url"],                            "fetch {}",    True,  False),
    "list_dir":   (["path"],                           "ls {}",       True,  False),
}

_PATH_IN_CMD_RE = re.compile(
    r'"(?P<double>(?:[A-Za-z]:[/\\]|~/|/)[^"]+)"'
    r"|'(?P<single>(?:[A-Za-z]:[/\\]|~/|/)[^']+)'"
    r"|(?P<bare>(?:[A-Za-z]:[/\\]|~/|(?<=\s)/)[^\s;&|<>\"']+)"
)


ToolFormat = tuple[list[str], str, bool, bool]


def format_tool_event_hints(events: list[dict[str, Any]], max_length: int = 40) -> str:
    """Render structured tool starts for channels that choose plain-text hints."""
    calls = [
        ToolCallRequest(
            id=str(event.get("call_id") or ""),
            name=event.get("name", ""),
            arguments=event.get("arguments") or {},
        )
        for event in events if event.get("phase") == "start"
    ]
    return strip_think(format_tool_hints(calls, max_length=max_length))


def format_tool_hints(tool_calls: list[ToolCallRequest], max_length: int = 40) -> str:
    """Format tool calls as concise hints with smart abbreviation."""
    if not tool_calls:
        return ""

    formatted: list[str] = []
    for tc in tool_calls:
        name = getattr(tc, "name", None)
        if not isinstance(name, str) or not name:
            # Degenerate/malformed tool call (e.g. a model emits name=None);
            # skip it instead of raising AttributeError on the whole turn.
            continue
        fmt = _TOOL_FORMATS.get(name)
        if fmt:
            formatted.append(_fmt_known(tc, fmt, max_length))
        elif name.startswith("mcp_"):
            formatted.append(_fmt_mcp(tc, max_length))
        else:
            formatted.append(_fmt_fallback(tc, max_length))

    hints: list[tuple[str, int]] = []
    for hint in formatted:
        if hints and hints[-1][0] == hint:
            hints[-1] = (hint, hints[-1][1] + 1)
        else:
            hints.append((hint, 1))

    return ", ".join(
        f"{h} \u00d7 {c}" if c > 1 else h for h, c in hints
    )


def _get_args(tc: ToolCallRequest) -> dict[str, object]:
    if tc.arguments is None:
        return {}
    arguments = tc.arguments
    if isinstance(arguments, list):
        argument_list = cast(list[object], arguments)
        first_argument = argument_list[0] if argument_list else None
        return cast(dict[str, object], first_argument) if isinstance(first_argument, dict) else {}
    if isinstance(arguments, dict):
        return cast(dict[str, object], arguments)
    return {}


def _extract_arg(tc: ToolCallRequest, key_args: list[str]) -> str | None:
    args = _get_args(tc)
    for key in key_args:
        val = args.get(key)
        if isinstance(val, str) and val:
            return val
        if key == "args" and isinstance(val, list) and val:
            return " ".join(
                arg if isinstance(arg, str) and arg and not re.search(r"[\s\"']", arg)
                else json.dumps(arg, ensure_ascii=False)
                for arg in cast(list[object], val)
            )
    for val in args.values():
        if isinstance(val, str) and val:
            return val
    return None


def _fmt_known(tc: ToolCallRequest, fmt: ToolFormat, max_length: int = 40) -> str:
    if not fmt[0] and "{}" not in fmt[1]:
        return fmt[1]
    val = _extract_arg(tc, fmt[0])
    if val is None:
        return tc.name
    if fmt[2]:
        val = abbreviate_path(val, max_len=max_length)
    elif fmt[3]:
        val = _abbreviate_command(val, max_len=max_length)
    elif len(val) > max_length:
        val = val[:max_length - 1] + "\u2026"
    return fmt[1].format(val)


def _abbreviate_command(cmd: str, max_len: int = 40) -> str:
    path_max = max(max_len // 2, 25)

    def _replace_path(match: re.Match[str]) -> str:
        if match.group("double") is not None:
            return f'"{abbreviate_path(match.group("double"), max_len=path_max)}"'
        if match.group("single") is not None:
            return f"'{abbreviate_path(match.group('single'), max_len=path_max)}'"
        return abbreviate_path(match.group("bare"), max_len=path_max)

    abbreviated = _PATH_IN_CMD_RE.sub(_replace_path, cmd)
    if len(abbreviated) <= max_len:
        return abbreviated
    return abbreviated[:max_len - 1] + "\u2026"


def _fmt_mcp(tc: ToolCallRequest, max_length: int = 40) -> str:
    name = tc.name
    if "__" in name:
        parts = name.split("__", 1)
        server = parts[0].removeprefix("mcp_")
        tool = parts[1]
    else:
        rest = name.removeprefix("mcp_")
        parts = rest.split("_", 1)
        server = parts[0] if parts else rest
        tool = parts[1] if len(parts) > 1 else ""
    if not tool:
        return name
    args = _get_args(tc)
    val = next((v for v in args.values() if isinstance(v, str) and v), None)
    if val is None:
        return f"{server}::{tool}"
    return f'{server}::{tool}("{abbreviate_path(val, max_length)}")'


def _fmt_fallback(tc: ToolCallRequest, max_length: int = 40) -> str:
    args = _get_args(tc)
    val = next(iter(args.values()), None)
    if not isinstance(val, str):
        return tc.name
    return f'{tc.name}("{abbreviate_path(val, max_length)}")' if len(val) > max_length else f'{tc.name}("{val}")'
