"""Tool hint formatting for concise, human-readable tool call display."""

from __future__ import annotations

from nanobot.utils.path import abbreviate_path

# Registry: tool_name -> (key_args, template, is_path, is_command)
_TOOL_FORMATS: dict[str, tuple[list[str], str, bool, bool]] = {
    "read_file":  (["path", "file_path"],              "read {}",     True,  False),
    "write_file": (["path", "file_path"],              "write {}",    True,  False),
    "edit":       (["file_path", "path"],              "edit {}",     True,  False),
    "glob":       (["pattern"],                        'glob "{}"',   False, False),
    "grep":       (["pattern"],                        'grep "{}"',   False, False),
    "exec":       (["command"],                        "$ {}",        False, True),
    "web_search": (["query"],                          'search "{}"', False, False),
    "web_fetch":  (["url"],                            "fetch {}",    True,  False),
    "list_dir":   (["path"],                           "ls {}",       True,  False),
}


def format_tool_hints(tool_calls: list) -> str:
    """Format tool calls as concise hints with smart abbreviation."""
    if not tool_calls:
        return ""

    hints = []
    for name, count, example_tc in _group_consecutive(tool_calls):
        fmt = _TOOL_FORMATS.get(name)
        if fmt:
            hint = _fmt_known(example_tc, fmt)
        elif name.startswith("mcp_"):
            hint = _fmt_mcp(example_tc)
        else:
            hint = _fmt_fallback(example_tc)

        if count > 1:
            hint = f"{hint} \u00d7 {count}"
        hints.append(hint)

    return ", ".join(hints)


def _get_args(tc) -> dict:
    """Extract args dict from tc.arguments, handling list/dict/None/empty."""
    if tc.arguments is None:
        return {}
    if isinstance(tc.arguments, list):
        return tc.arguments[0] if tc.arguments else {}
    if isinstance(tc.arguments, dict):
        return tc.arguments
    return {}


def _group_consecutive(calls: list) -> list[tuple[str, int, object]]:
    """Group consecutive calls to the same tool: [(name, count, first), ...]."""
    groups: list[tuple[str, int, object]] = []
    for tc in calls:
        if groups and groups[-1][0] == tc.name:
            groups[-1] = (groups[-1][0], groups[-1][1] + 1, groups[-1][2])
        else:
            groups.append((tc.name, 1, tc))
    return groups


def _extract_arg(tc, key_args: list[str]) -> str | None:
    """Extract the first available value from preferred key names."""
    args = _get_args(tc)
    if not isinstance(args, dict):
        return None
    for key in key_args:
        val = args.get(key)
        if isinstance(val, str) and val:
            return val
    for val in args.values():
        if isinstance(val, str) and val:
            return val
    return None


def _fmt_known(tc, fmt: tuple) -> str:
    """Format a registered tool using its template."""
    val = _extract_arg(tc, fmt[0])
    if val is None:
        return tc.name
    if fmt[2]:  # is_path
        val = abbreviate_path(val)
    elif fmt[3]:  # is_command
        val = val[:40] + "\u2026" if len(val) > 40 else val
    return fmt[1].format(val)


def _fmt_mcp(tc) -> str:
    """Format MCP tool as server::tool."""
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
    return f'{server}::{tool}("{abbreviate_path(val, 40)}")'


def _fmt_fallback(tc) -> str:
    """Original formatting logic for unregistered tools."""
    args = _get_args(tc)
    val = next(iter(args.values()), None) if isinstance(args, dict) else None
    if not isinstance(val, str):
        return tc.name
    return f'{tc.name}("{abbreviate_path(val, 40)}")' if len(val) > 40 else f'{tc.name}("{val}")'
