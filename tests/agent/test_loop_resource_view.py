"""AgentLoop integration tests for the runtime resource view."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nanobot.agent.loop import AgentLoop, TurnKind
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ToolsConfig
from nanobot.resource_links import ResourceView
from nanobot.security.workspace_access import build_workspace_scope


def _provider() -> MagicMock:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = SimpleNamespace(
        max_tokens=4096,
        temperature=0.1,
        reasoning_effort=None,
    )
    return provider


def _loop(
    tmp_path: Path,
    *,
    resource_view: ResourceView | None,
    tools_config: ToolsConfig | None = None,
) -> tuple[AgentLoop, MagicMock, MagicMock]:
    with (
        patch("nanobot.agent.loop.ContextBuilder") as context_builder,
        patch("nanobot.agent.loop.SessionManager"),
        patch("nanobot.agent.loop.SubagentManager") as subagent_manager,
        patch.object(AgentLoop, "_register_default_tools"),
    ):
        loop = AgentLoop(
            bus=MessageBus(),
            provider=_provider(),
            workspace=tmp_path,
            tools_config=tools_config,
            resource_view=resource_view,
        )
    return loop, context_builder, subagent_manager


def test_loop_injects_resource_view_without_creating_one(tmp_path: Path) -> None:
    view = ResourceView(root=tmp_path / "resources" / "view")

    loop, context_builder, subagent_manager = _loop(
        tmp_path,
        resource_view=view,
    )

    assert loop.resource_view is view
    assert context_builder.call_args.kwargs["resource_view"] is view
    assert subagent_manager.call_args.kwargs["resource_view"] is view


@pytest.mark.parametrize(
    ("access_mode", "sandbox", "expected"),
    [
        ("full", "", "full"),
        ("restricted", "", "restricted"),
        ("full", "bwrap", "restricted"),
    ],
)
def test_initial_prompt_uses_effective_resource_view_mode(
    tmp_path: Path,
    access_mode: str,
    sandbox: str,
    expected: str,
) -> None:
    tools_config = ToolsConfig()
    tools_config.exec.sandbox = sandbox
    view = ResourceView(root=tmp_path / "resources" / "view")
    loop, _, _ = _loop(
        tmp_path,
        resource_view=view,
        tools_config=tools_config,
    )
    scope = build_workspace_scope(tmp_path, access_mode)
    loop.workspace_scopes = SimpleNamespace(for_message=MagicMock(return_value=scope))
    loop.context.build_messages.return_value = []
    turn = SimpleNamespace(
        session=SimpleNamespace(key="cli:test", metadata={}),
        msg=SimpleNamespace(content="hello", media=None),
        history=[],
        kind=TurnKind.USER,
        delivery=SimpleNamespace(route=SimpleNamespace(channel="cli")),
        pending_summary=None,
        runtime_context_blocks=[],
        ephemeral=False,
    )

    loop._build_initial_messages(turn)

    assert loop.context.build_messages.call_args.kwargs["resource_view_mode"] == expected


def test_initial_prompt_keeps_legacy_mode_without_resource_view(tmp_path: Path) -> None:
    loop, _, _ = _loop(tmp_path, resource_view=None)
    scope = build_workspace_scope(tmp_path, "full")

    assert loop._resource_view_mode_for_scope(scope) is None
