"""Agent delegation tool for calling external agents (Claude Code, Codex, etc.)."""

from __future__ import annotations

import asyncio
import os
import shutil
from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import IntegerSchema, StringSchema, tool_parameters_schema


@tool_parameters(
    tool_parameters_schema(
        task=StringSchema("The task for the external agent to complete"),
        agent=StringSchema(
            "External agent CLI to invoke. Supported: claude (Claude Code), "
            "codex (OpenAI Codex CLI), opencode (opencode). "
            "Uses the first one found on PATH by default."
        ),
        model=StringSchema(
            "Optional model override for the external agent. "
            "Passed as --model to the CLI."
        ),
        timeout=IntegerSchema(
            300,
            description="Timeout in seconds (default 300, max 600).",
            minimum=1,
            maximum=600,
        ),
        required=["task"],
    )
)
class AgentDelegateTool(Tool):
    """Delegate a task to an external AI agent CLI and return its output."""

    name = "agent_delegate"
    _KNOWN_AGENTS = ("claude", "codex", "opencode")

    @property
    def description(self) -> str:
        agents = ", ".join(self._KNOWN_AGENTS)
        return (
            "Delegate a coding or analysis task to an external AI agent CLI "
            f"({agents}). The agent runs in the current workspace and returns "
            "its final output. Use this for heavy coding tasks that benefit "
            "from a dedicated agent runtime."
        )

    @property
    def read_only(self) -> bool:
        return False

    @property
    def exclusive(self) -> bool:
        return True

    async def execute(
        self,
        task: str,
        agent: str | None = None,
        model: str | None = None,
        timeout: int = 300,
        **kwargs: Any,
    ) -> str:
        # Resolve the agent CLI.
        if agent and agent not in self._KNOWN_AGENTS:
            return (
                f"Error: unknown agent {agent!r}. "
                f"Supported: {', '.join(self._KNOWN_AGENTS)}"
            )
        cli = shutil.which(agent) if agent else None
        if not cli:
            for candidate in self._KNOWN_AGENTS:
                cli = shutil.which(candidate)
                if cli:
                    break
        if not cli:
            return (
                "Error: no external agent CLI found on PATH. "
                "Install one of: claude (Claude Code), codex, or opencode."
            )

        args = [cli]
        if model:
            args.extend(["--model", model])
        # Pass the task via stdin so it doesn't hit shell escaping issues.
        args.extend(["-p", task])

        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ},
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout,
            )
        except asyncio.TimeoutError:
            return f"Error: external agent timed out after {timeout}s"

        output = stdout.decode("utf-8", errors="replace") if stdout else ""
        if stderr:
            err_text = stderr.decode("utf-8", errors="replace").strip()
            if err_text:
                output += f"\n\n[stderr]\n{err_text}"

        if not output.strip():
            return f"External agent returned empty output (exit code {process.returncode})"

        return output.strip()
