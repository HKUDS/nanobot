from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.command.builtin import builtin_command_palette, register_builtin_commands
from nanobot.command.router import CommandContext, CommandRouter
from nanobot.security.workspace_access import WORKSPACE_SCOPE_METADATA_KEY, WorkspaceScopeResolver
from nanobot.session.manager import Session


def _loop(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        workspace_scopes=WorkspaceScopeResolver(
            default_workspace=tmp_path,
            default_restrict_to_workspace=True,
            scoped_channels={"websocket", "cli"},
        ),
        sessions=SimpleNamespace(get_or_create=lambda key: Session(key)),
        context_window_tokens=1000,
        provider=SimpleNamespace(generation=SimpleNamespace(max_tokens=200)),
        _last_usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        _active_tasks={},
        subagents=SimpleNamespace(get_running_count_by_session=lambda key: 0),
    )


async def _dispatch(raw: str, tmp_path: Path, session: Session | None = None):
    router = CommandRouter()
    register_builtin_commands(router)
    msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content=raw)
    key = "cli:direct"
    ctx = CommandContext(
        msg=msg,
        session=session or Session(key),
        key=key,
        raw=raw,
        loop=_loop(tmp_path),
    )
    return await router.dispatch(ctx), ctx


def test_builtin_palette_includes_optional_cli_metadata() -> None:
    permissions = next(item for item in builtin_command_palette() if item["command"] == "/permissions")

    assert permissions["category"] == "session"
    assert permissions["danger"] is True
    assert permissions["status_provider"] == "workspace_scope"


@pytest.mark.asyncio
async def test_permissions_updates_only_current_session_metadata(tmp_path: Path) -> None:
    session = Session("cli:direct")
    result, ctx = await _dispatch("/permissions full", tmp_path, session=session)

    assert result is not None
    assert "Updated permissions" in result.content
    assert session.metadata[WORKSPACE_SCOPE_METADATA_KEY]["access_mode"] == "full"
    assert ctx.msg.metadata[WORKSPACE_SCOPE_METADATA_KEY]["access_mode"] == "full"


@pytest.mark.asyncio
async def test_workspace_accepts_relative_path_for_cli_session(tmp_path: Path) -> None:
    project = tmp_path / "project"
    nested = project / "nested"
    nested.mkdir(parents=True)
    session = Session(
        "cli:direct",
        metadata={
            WORKSPACE_SCOPE_METADATA_KEY: {
                "project_path": str(project),
                "access_mode": "restricted",
            }
        },
    )

    result, _ = await _dispatch("/workspace nested", tmp_path, session=session)

    assert result is not None
    assert "Updated workspace" in result.content
    assert session.metadata[WORKSPACE_SCOPE_METADATA_KEY] == {
        "project_path": str(nested.resolve()),
        "access_mode": "restricted",
    }


@pytest.mark.asyncio
async def test_output_lists_then_shows_full_tool_result(tmp_path: Path) -> None:
    session = Session("cli:direct")
    session.messages.extend(
        [
            {"role": "user", "content": "read it"},
            {"role": "tool", "name": "read_file", "content": "line 1\nline 2\nline 3"},
        ]
    )

    listing, _ = await _dispatch("/output", tmp_path, session=session)
    assert listing is not None
    assert "read_file" in listing.content
    assert "Recent tool output" in listing.content

    full, _ = await _dispatch("/output 1", tmp_path, session=session)
    assert full is not None
    assert "line 1\nline 2\nline 3" in full.content


@pytest.mark.asyncio
async def test_output_handles_empty_session(tmp_path: Path) -> None:
    result, _ = await _dispatch("/output", tmp_path, session=Session("cli:direct"))
    assert result is not None
    assert "No tool output" in result.content
