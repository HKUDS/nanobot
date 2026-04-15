"""Kosmos hook names over the legacy NanoCats hook implementation."""

from __future__ import annotations

from pathlib import Path

from .nanocats_hook import (
    NanoCatsAgentHook,
    NanoCatsSubagentHook,
    create_nanocats_hook,
    create_subagent_hook,
)

KosmosAgentHook = NanoCatsAgentHook
KosmosSubagentHook = NanoCatsSubagentHook


def create_kosmos_hook(
    agent_id: str = "main",
    agent_name: str = "Kosmos",
    workspace: Path | None = None,
    task_id: str | None = None,
) -> KosmosAgentHook:
    return create_nanocats_hook(
        agent_id=agent_id, agent_name=agent_name, workspace=workspace, task_id=task_id
    )


def create_kosmos_subagent_hook(
    task_id: str,
    task_label: str = "",
    workspace: Path | None = None,
    project_id: str | None = None,
) -> KosmosSubagentHook:
    return create_subagent_hook(
        task_id=task_id,
        task_label=task_label,
        workspace=workspace,
        project_id=project_id,
    )


__all__ = [
    "KosmosAgentHook",
    "KosmosSubagentHook",
    "create_kosmos_hook",
    "create_kosmos_subagent_hook",
]
