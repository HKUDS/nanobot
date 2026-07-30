"""RuntimeState protocol: agent loop state exposed to MyTool."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager
    from nanobot.agent.tools.shell import ExecToolConfig
    from nanobot.agent.tools.web import WebToolsConfig
    from nanobot.utils.llm_runtime import LLMRuntime


class RuntimeState(Protocol):
    """Minimum contract that MyTool requires from its runtime state provider.

    In practice, this is always satisfied by ``AgentLoop``.  MyTool also
    accesses arbitrary attributes dynamically (via ``getattr`` / ``setattr``)
    for dot-path inspection and modification; those paths are validated at
    runtime rather than by this protocol.
    """

    @property
    def model(self) -> str: ...

    @property
    def max_iterations(self) -> int: ...

    @property
    def current_iteration(self) -> int: ...

    @property
    def tool_names(self) -> list[str]: ...

    @property
    def workspace(self) -> Path: ...

    @property
    def provider_retry_mode(self) -> str: ...

    @property
    def max_tool_result_chars(self) -> int: ...

    @property
    def context_window_tokens(self) -> int: ...

    @property
    def web_config(self) -> WebToolsConfig: ...

    @property
    def exec_config(self) -> ExecToolConfig: ...

    @property
    def subagents(self) -> SubagentManager: ...

    @property
    def _runtime_vars(self) -> dict[str, Any]: ...

    @property
    def _last_usage(self) -> dict[str, int]: ...

    def _sync_subagent_runtime_limits(self) -> None: ...

    def set_runtime_model(self, model: str) -> LLMRuntime: ...

    def set_runtime_context_window(self, context_window_tokens: int) -> LLMRuntime: ...

    def set_session_model_preset(
        self,
        session_key: str,
        name: str,
    ) -> LLMRuntime: ...

    @property
    def model_preset(self) -> str | None: ...
