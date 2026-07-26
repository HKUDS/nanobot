from unittest.mock import patch

from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.command.router import CommandRouter
from nanobot.config.schema import Config, MCPServerConfig
from nanobot.extensions import ContributionKind, discover_native_extensions


class _Tool(Tool):
    @property
    def name(self) -> str:
        return "acme_tool"

    @property
    def description(self) -> str:
        return "Acme tool"

    @property
    def parameters(self) -> dict:
        return {"type": "object"}

    async def execute(self, **kwargs):
        return kwargs


def test_native_inventory_preserves_runtime_ownership(tmp_path) -> None:
    tools = ToolRegistry()
    tools.register(_Tool(), owner="acme.extension")
    commands = CommandRouter()

    async def _handler(_ctx):
        return None

    commands.exact("/acme", _handler, owner="acme.extension")
    config = Config()
    config.tools.mcp_servers["docs"] = MCPServerConfig(url="https://example.com")

    with (
        patch("nanobot.channels.registry.discover_plugins", return_value={}),
        patch("nanobot.providers.registry.PROVIDERS", ()),
        patch("nanobot.audio.transcription_registry.TRANSCRIPTION_PROVIDERS", ()),
        patch(
            "nanobot.providers.image_generation.image_gen_provider_names",
            return_value=(),
        ),
    ):
        result = discover_native_extensions(
            config,
            skills=SkillsLoader(tmp_path, builtin_skills_dir=tmp_path / "missing"),
            tools=tools,
            commands=commands,
        )

    extensions = {item.manifest.id: item for item in result.candidates}
    assert {
        contribution.kind
        for contribution in extensions["acme.extension"].manifest.contributions
    } == {ContributionKind.TOOL, ContributionKind.COMMAND}
    assert "nanobot.mcp.docs" in extensions


def test_native_inventory_projects_workspace_skill(tmp_path) -> None:
    skill_dir = tmp_path / "skills" / "release"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: release\n"
        "description: Prepare a release.\n"
        "metadata:\n"
        "  nanobot:\n"
        "    requires:\n"
        "      bins: [gh]\n"
        "---\n"
    )

    with (
        patch("nanobot.channels.registry.discover_plugins", return_value={}),
        patch("nanobot.providers.registry.PROVIDERS", ()),
        patch("nanobot.audio.transcription_registry.TRANSCRIPTION_PROVIDERS", ()),
        patch(
            "nanobot.providers.image_generation.image_gen_provider_names",
            return_value=(),
        ),
    ):
        result = discover_native_extensions(
            Config(),
            skills=SkillsLoader(tmp_path, builtin_skills_dir=tmp_path / "missing"),
        )

    skill = next(
        item for item in result.candidates if item.manifest.id == "nanobot.skill.release"
    )
    assert skill.scope.name == "WORKSPACE"
    assert skill.manifest.contributions[0].description == "Prepare a release."
