"""Controlled runner for installed CLI Apps."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field

from blackcat.agent.tools.base import Tool, tool_parameters
from blackcat.agent.tools.schema import ArraySchema, BooleanSchema, IntegerSchema, StringSchema, tool_parameters_schema
from blackcat.security.workspace_access import current_tool_workspace
from blackcat.apps.cli import CliAppError, CliAppManager, CliAppsRuntimeConfig
from blackcat.config_base import Base


class CliAppsToolConfig(Base):
    """CLI Apps tool configuration."""

    enable: bool = True
    install_timeout: int = Field(default=300, ge=1, le=3600)
    run_timeout: int = Field(default=60, ge=1, le=600)
    catalog_ttl_seconds: int = Field(default=3600, ge=60, le=86_400)


@tool_parameters(
    tool_parameters_schema(
        required=["name"],
        name=StringSchema("Installed CLI app registry name, for example gimp, safari, or obsidian."),
        args=ArraySchema(
            StringSchema("One command-line argument."),
            description="Arguments to pass to the CLI entry point. Do not include the entry point itself.",
            nullable=True,
        ),
        json=BooleanSchema(
            description="Whether to prepend --json when supported by the CLI.",
            default=False,
            nullable=True,
        ),
        working_dir=StringSchema("Optional working directory for the CLI call.", nullable=True),
        timeout=IntegerSchema(
            description="Timeout in seconds for this CLI call.",
            minimum=1,
            maximum=600,
            nullable=True,
        ),
    )
)
class CliAppsTool(Tool):
    """Run an installed CLI-Anything or public CLI app through a controlled argv subprocess."""

    config_key = "cli_apps"
    _scopes = {"core", "subagent"}

    @classmethod
    def config_cls(cls):
        return CliAppsToolConfig

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return ctx.config.cli_apps.enable

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        cfg = ctx.config.cli_apps
        return cls(
            workspace=Path(ctx.workspace),
            restrict_to_workspace=ctx.config.restrict_to_workspace,
            runtime=CliAppsRuntimeConfig(
                install_timeout=cfg.install_timeout,
                run_timeout=cfg.run_timeout,
                catalog_ttl_seconds=cfg.catalog_ttl_seconds,
            ),
        )

    def __init__(
        self,
        *,
        workspace: Path,
        restrict_to_workspace: bool = False,
        runtime: CliAppsRuntimeConfig | None = None,
    ) -> None:
        self.workspace = workspace
        self.restrict_to_workspace = restrict_to_workspace
        self.runtime = runtime or CliAppsRuntimeConfig()

    @property
    def name(self) -> str:
        return "run_cli_app"

    @property
    def description(self) -> str:
        try:
            installed = CliAppManager(workspace=self.workspace, runtime=self.runtime).installed_names()
        except Exception:
            installed = []
        installed_note = (
            f" Installed Settings CLI Apps: {', '.join(installed)}."
            if installed
            else " No Settings CLI Apps are currently installed."
        )
        return (
            "Run a CLI App that the user explicitly installed in Settings or attached as @app. "
            "Do not use this for ordinary system CLIs such as git, gh, python, npm, or brew; "
            "unknown names are rejected. Execution uses argv, not shell."
            + installed_note
        )

    async def execute(
        self,
        name: str,
        args: list[str] | None = None,
        json: bool | None = False,
        working_dir: str | None = None,
        timeout: int | None = None,
    ) -> str:
        access = current_tool_workspace(
            self.workspace,
            restrict_to_workspace=self.restrict_to_workspace,
        )
        workspace = access.project_path or self.workspace
        manager = CliAppManager(workspace=workspace, runtime=self.runtime)
        try:
            return manager.run(
                name,
                args=args or [],
                json_output=bool(json),
                working_dir=working_dir,
                timeout=timeout,
                restrict_to_workspace=access.restrict_to_workspace,
            )
        except CliAppError as exc:
            return f"Error: {exc.message}"
