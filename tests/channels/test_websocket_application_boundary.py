"""Executable architecture constraints for the WebSocket transport adapter."""

from __future__ import annotations

import ast
from pathlib import Path

from nanobot.channels.websocket import runtime

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_RUNTIME_PATH = _REPOSITORY_ROOT / "nanobot" / "channels" / "websocket" / "runtime.py"
_SESSION_IDENTITY_PATH = _REPOSITORY_ROOT / "nanobot" / "webui" / "session_identity.py"
_FORBIDDEN_RUNTIME_IMPORTS = (
    "nanobot.bus.outbound_events",
    "nanobot.command",
    "nanobot.runtime_context",
    "nanobot.security.workspace_access",
    "nanobot.session.goal_state",
    "nanobot.webui.cli_apps_api",
    "nanobot.webui.forking",
    "nanobot.webui.mcp_presets_api",
    "nanobot.webui.sidebar_state",
    "nanobot.webui.transcription_ws",
)


def _channel_method(name: str) -> ast.AsyncFunctionDef:
    tree = ast.parse(_RUNTIME_PATH.read_text(encoding="utf-8"))
    channel = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "WebSocketChannel"
    )
    return next(
        node
        for node in channel.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name
    )


def _statements_without_docstring(node: ast.AsyncFunctionDef) -> list[ast.stmt]:
    body = list(node.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body.pop(0)
    return body


def test_websocket_runtime_does_not_import_application_command_trees() -> None:
    tree = ast.parse(_RUNTIME_PATH.read_text(encoding="utf-8"))
    imported = {
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    violations = sorted(
        module
        for module in imported
        if module.startswith(_FORBIDDEN_RUNTIME_IMPORTS)
    )
    assert violations == []


def test_business_entrypoints_are_thin_transport_delegations() -> None:
    for method_name in ("_dispatch_envelope", "_hydrate_after_subscribe", "send"):
        statements = _statements_without_docstring(_channel_method(method_name))
        assert len(statements) == 1, method_name
        assert isinstance(statements[0], ast.Expr), method_name
        assert isinstance(statements[0].value, ast.Await), method_name

    statements = _statements_without_docstring(_channel_method("_dispatch_http"))
    assert len(statements) == 1
    assert isinstance(statements[0], ast.Return)
    assert isinstance(statements[0].value, ast.Await)


def test_persisted_webui_session_prefix_has_one_production_owner() -> None:
    owners = []
    for path in (_REPOSITORY_ROOT / "nanobot").rglob("*.py"):
        if "tests" in path.parts or path == _SESSION_IDENTITY_PATH:
            continue
        if "websocket:" in path.read_text(encoding="utf-8"):
            owners.append(path.relative_to(_REPOSITORY_ROOT).as_posix())
    assert owners == []
    assert 'WEBUI_SESSION_STORAGE_PREFIX = "websocket:"' in _SESSION_IDENTITY_PATH.read_text(
        encoding="utf-8"
    )


def test_runtime_exports_compatibility_protocol_helpers() -> None:
    assert runtime._is_valid_chat_id("unified:default")  # pyright: ignore[reportPrivateUsage]
    assert not runtime._is_valid_chat_id("../escape")  # pyright: ignore[reportPrivateUsage]
