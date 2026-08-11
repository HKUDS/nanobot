"""Explicit runtime state boundary used by :class:`MyTool`."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TypeAlias, runtime_checkable

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager, SubagentStatus
    from nanobot.agent.tools.shell import ExecToolConfig
    from nanobot.agent.tools.web import WebToolsConfig
    from nanobot.config.schema import ModelPresetConfig
    from nanobot.utils.llm_runtime import LLMRuntime


JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


RUNTIME_SNAPSHOT_KEYS = frozenset({
    "model",
    "model_preset",
    "model_presets",
    "max_iterations",
    "context_window_tokens",
    "workspace",
    "provider_retry_mode",
    "max_tool_result_chars",
    "current_iteration",
    "_current_iteration",
    "tool_names",
    "web_config",
    "exec_config",
    "subagents",
    "_last_usage",
})

RUNTIME_COMMAND_KEYS = frozenset({
    "model",
    "model_preset",
    "max_iterations",
    "context_window_tokens",
    "provider_retry_mode",
    "max_tool_result_chars",
    "workspace",
})


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    """Detached, allowlisted values available to self-inspection."""

    model: str
    model_preset: str | None
    model_presets: dict[str, dict[str, object]]
    max_iterations: int
    context_window_tokens: int
    workspace: Path | str
    provider_retry_mode: str
    max_tool_result_chars: int
    current_iteration: int
    tool_names: list[str]
    web_config: dict[str, object]
    exec_config: dict[str, object]
    subagent_statuses: dict[str, dict[str, object]]
    last_usage: dict[str, int]
    scratchpad: dict[str, JsonValue]

    def as_mapping(self) -> Mapping[str, object]:
        """Return the fixed public names understood by ``MyTool``."""
        values: dict[str, object] = {
            "model": self.model,
            "model_preset": self.model_preset,
            "model_presets": self.model_presets,
            "max_iterations": self.max_iterations,
            "context_window_tokens": self.context_window_tokens,
            "workspace": self.workspace,
            "provider_retry_mode": self.provider_retry_mode,
            "max_tool_result_chars": self.max_tool_result_chars,
            "current_iteration": self.current_iteration,
            "_current_iteration": self.current_iteration,
            "tool_names": self.tool_names,
            "web_config": self.web_config,
            "exec_config": self.exec_config,
            "subagents": {"_task_statuses": self.subagent_statuses},
            "_last_usage": self.last_usage,
        }
        assert values.keys() == RUNTIME_SNAPSHOT_KEYS
        return values


@runtime_checkable
class RuntimeControl(Protocol):
    """The complete runtime capability exposed to ``MyTool``."""

    def snapshot(self) -> RuntimeSnapshot: ...

    def set_model(self, model: str) -> LLMRuntime: ...

    def set_model_preset(
        self,
        name: str,
        *,
        session_key: str | None,
    ) -> LLMRuntime: ...

    def set_max_iterations(self, value: int) -> None: ...

    def set_context_window_tokens(self, value: int) -> LLMRuntime: ...

    def set_provider_retry_mode(self, value: str) -> None: ...

    def set_max_tool_result_chars(self, value: int) -> None: ...

    def set_workspace_display(self, value: str) -> None: ...

    def set_scratchpad(self, key: str, value: JsonValue, *, max_keys: int) -> None: ...


class _RuntimeControlTarget(Protocol):
    """Narrow structural dependency required by ``AgentRuntimeControl``."""

    max_iterations: int
    provider_retry_mode: str
    max_tool_result_chars: int
    web_config: WebToolsConfig
    exec_config: ExecToolConfig
    subagents: SubagentManager

    @property
    def model(self) -> str: ...

    @property
    def model_preset(self) -> str | None: ...

    @property
    def model_presets(self) -> Mapping[str, ModelPresetConfig]: ...

    @property
    def context_window_tokens(self) -> int: ...

    @property
    def workspace(self) -> Path: ...

    @property
    def current_iteration(self) -> int: ...

    @property
    def tool_names(self) -> list[str]: ...

    @property
    def last_usage(self) -> Mapping[str, int]: ...

    def set_runtime_model(self, model: str) -> LLMRuntime: ...

    def set_runtime_context_window(self, context_window_tokens: int) -> LLMRuntime: ...

    def set_model_preset(self, name: str | None) -> LLMRuntime: ...

    def set_session_model_preset(self, session_key: str, name: str) -> LLMRuntime: ...


class AgentRuntimeControl:
    """Allowlisted adapter from agent-loop state to ``RuntimeControl``."""

    def __init__(self, target: _RuntimeControlTarget) -> None:
        self.__target = target
        self.__scratchpad: dict[str, JsonValue] = {}
        self.__workspace_display: str | None = None

    def snapshot(self) -> RuntimeSnapshot:
        target = self.__target
        return RuntimeSnapshot(
            model=target.model,
            model_preset=target.model_preset,
            model_presets=_snapshot_model_presets(target.model_presets),
            max_iterations=target.max_iterations,
            context_window_tokens=target.context_window_tokens,
            workspace=(
                self.__workspace_display
                if self.__workspace_display is not None
                else target.workspace
            ),
            provider_retry_mode=target.provider_retry_mode,
            max_tool_result_chars=target.max_tool_result_chars,
            current_iteration=target.current_iteration,
            tool_names=list(target.tool_names),
            web_config=_snapshot_web_config(target.web_config),
            exec_config=_snapshot_exec_config(target.exec_config),
            subagent_statuses=_snapshot_subagent_statuses(target.subagents),
            last_usage=dict(target.last_usage),
            scratchpad=_snapshot_json_mapping(self.__scratchpad),
        )

    def set_model(self, model: str) -> LLMRuntime:
        return self.__target.set_runtime_model(model)

    def set_model_preset(
        self,
        name: str,
        *,
        session_key: str | None,
    ) -> LLMRuntime:
        if session_key is not None:
            return self.__target.set_session_model_preset(session_key, name)
        return self.__target.set_model_preset(name)

    def set_max_iterations(self, value: int) -> None:
        self.__target.max_iterations = value
        self.__target.subagents.max_iterations = value

    def set_context_window_tokens(self, value: int) -> LLMRuntime:
        return self.__target.set_runtime_context_window(value)

    def set_provider_retry_mode(self, value: str) -> None:
        self.__target.provider_retry_mode = value

    def set_max_tool_result_chars(self, value: int) -> None:
        self.__target.max_tool_result_chars = value

    def set_workspace_display(self, value: str) -> None:
        """Preserve MyTool display compatibility without changing path enforcement."""
        self.__workspace_display = value

    def set_scratchpad(self, key: str, value: JsonValue, *, max_keys: int) -> None:
        if key not in self.__scratchpad and len(self.__scratchpad) >= max_keys:
            raise ValueError(f"scratchpad is full (max {max_keys} keys)")
        self.__scratchpad[key] = value


def _snapshot_model_presets(
    presets: Mapping[str, ModelPresetConfig],
) -> dict[str, dict[str, object]]:
    return {
        name: {
            "label": preset.label,
            "model": preset.model,
            "provider": preset.provider,
            "max_tokens": preset.max_tokens,
            "context_window_tokens": preset.context_window_tokens,
            "temperature": preset.temperature,
            "reasoning_effort": preset.reasoning_effort,
        }
        for name, preset in presets.items()
    }


def _snapshot_web_config(config: WebToolsConfig) -> dict[str, object]:
    return {
        "enable": config.enable,
        # Proxy URLs may embed credentials. Presence is enough for diagnosis.
        "proxy": "<configured>" if config.proxy else config.proxy,
        "user_agent": config.user_agent,
        "search": {
            "provider": config.search.provider,
            "base_url": config.search.base_url,
            "max_results": config.search.max_results,
            "timeout": config.search.timeout,
        },
        "fetch": {
            "use_jina_reader": config.fetch.use_jina_reader,
        },
    }


def _snapshot_exec_config(config: ExecToolConfig) -> dict[str, object]:
    return {
        "enable": config.enable,
        "timeout": config.timeout,
        "path_prepend": config.path_prepend,
        "path_append": config.path_append,
        "sandbox": config.sandbox,
        "sandbox_ro_binds": list(config.sandbox_ro_binds),
        "sandbox_rw_binds": list(config.sandbox_rw_binds),
        "allowed_env_keys": list(config.allowed_env_keys),
        "allow_patterns": list(config.allow_patterns),
        "deny_patterns": list(config.deny_patterns),
    }


def _snapshot_subagent_statuses(
    manager: SubagentManager,
) -> dict[str, dict[str, object]]:
    return {
        task_id: _snapshot_subagent_status(status)
        for task_id, status in manager.runtime_statuses().items()
    }


def _snapshot_subagent_status(status: SubagentStatus) -> dict[str, object]:
    return {
        "task_id": status.task_id,
        "label": status.label,
        "task_description": status.task_description,
        "started_at": status.started_at,
        "phase": status.phase,
        "iteration": status.iteration,
        "tool_events": [dict(event) for event in status.tool_events],
        "usage": dict(status.usage),
        "stop_reason": status.stop_reason,
        "error": status.error,
    }


def _snapshot_json_mapping(values: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    return {key: _snapshot_json_value(value) for key, value in values.items()}


def _snapshot_json_value(value: JsonValue) -> JsonValue:
    if isinstance(value, list):
        return [_snapshot_json_value(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _snapshot_json_value(item)
            for key, item in value.items()
        }
    return value
