"""GeoClaw runtime built on top of the nanobot agent loop."""

from __future__ import annotations

import shutil
from pathlib import Path

from nanobot.agent.context import ContextBuilder
from nanobot.agent.loop import AgentLoop

from geoclaw.prompts.system import GEOCLAW_IDENTITY
from geoclaw.tools import register_all_geo_tools


class GeoClawContextBuilder(ContextBuilder):
    """Context builder that brands the agent as GeoClaw."""

    def _get_identity(self) -> str:
        base = super()._get_identity()
        return base + "\n\n---\n\n" + GEOCLAW_IDENTITY


def sync_geoclaw_skills(workspace: Path) -> None:
    """Copy packaged GeoClaw skills into the workspace skill directory."""
    source_dir = Path(__file__).parent / "skills"
    target_dir = workspace / "skills"
    target_dir.mkdir(parents=True, exist_ok=True)

    for skill_dir in source_dir.iterdir():
        if not skill_dir.is_dir():
            continue
        src = skill_dir / "SKILL.md"
        if not src.exists():
            continue
        dest_dir = target_dir / skill_dir.name
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest_dir / "SKILL.md")


class GeoClawLoop(AgentLoop):
    """AgentLoop with GeoClaw tools and prompt customisation."""

    def __init__(self, *args, **kwargs):
        workspace = kwargs.get("workspace") or (args[2] if len(args) > 2 else None)
        super().__init__(*args, **kwargs)
        self.context = GeoClawContextBuilder(self.workspace)
        self.memory_consolidator._build_messages = self.context.build_messages
        sync_geoclaw_skills(self.workspace)

    def _register_default_tools(self) -> None:
        super()._register_default_tools()
        for tool in register_all_geo_tools(self.workspace):
            self.tools.register(tool)
