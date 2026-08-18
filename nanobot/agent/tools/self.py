"""MyTool: runtime state inspection and configuration for the agent loop."""

# Tool.execute accepts heterogeneous schemas.
# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeGuard, cast

from loguru import logger

from nanobot.agent.tools.base import Tool, ToolResult
from nanobot.agent.tools.context import current_request_context, current_request_session_key
from nanobot.agent.tools.runtime_control import (
    RUNTIME_COMMAND_KEYS,
    RUNTIME_SNAPSHOT_KEYS,
    JsonValue,
    RuntimeControl,
    RuntimeSnapshot,
)
from nanobot.config_base import Base

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentStatus
    from nanobot.agent.tools.context import ToolContext


class MyToolConfig(Base):
    """Self-inspection tool configuration."""
    enable: bool = True
    allow_set: bool = False


def _is_subagent_status(value: object) -> TypeGuard[SubagentStatus]:
    from nanobot.agent.subagent import SubagentStatus

    return isinstance(value, SubagentStatus)


def _is_subagent_status_snapshot(value: object) -> TypeGuard[Mapping[str, object]]:
    if not isinstance(value, Mapping):
        return False
    return all(
        field in value
        for field in ("task_id", "label", "task_description", "started_at", "phase")
    )


def _is_string_mapping(value: object) -> TypeGuard[Mapping[str, object]]:
    if not isinstance(value, Mapping):
        return False
    mapping = cast(Mapping[object, object], value)
    return all(isinstance(key, str) for key in mapping)


class MyTool(Tool):
    """Check and set the agent loop's runtime configuration."""

    _plugin_discoverable = False  # Requires AgentLoop reference; registered manually
    config_key = "my"

    @classmethod
    def config_cls(cls):
        return MyToolConfig

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return ctx.config.my.enable

    BLOCKED = frozenset({
        # Core infrastructure
        "bus", "provider", "runtime_resolver", "_running", "tools",
        # Config management
        "_runtime_vars",
        # Subsystems
        "runner", "sessions", "consolidator",
        "dream", "auto_compact", "context", "commands",
        # Sensitive runtime state (credentials, message routing, task tracking)
        "_pending_queues",
        "_session_locks", "_active_tasks", "_background_tasks",
        # Security boundaries (inspect + modify both blocked)
        "restrict_to_workspace", "channels_config",
        "_concurrency_gate", "_unified_session", "_extra_hooks", "_hook_factories",
    })

    READ_ONLY = frozenset({
        "subagents",  # observable but replacing it would break the system
        "tool_names",
        "current_iteration",
        "_current_iteration",  # updated by runner only
        "_last_usage",
        "exec_config",  # inspect allowed (e.g. check sandbox), modify blocked
        "web_config",  # inspect allowed (e.g. check enable), modify blocked
        "model_presets",  # config-derived catalog; changes require config reload
        "workspace_sandbox",  # read-only view of workspace enforcement level
        "request",  # current message routing metadata
    })

    _REQUEST_FIELDS = ("channel", "chat_id", "sender_id")

    _DENIED_ATTRS = frozenset({
        "__class__", "__dict__", "__bases__", "__subclasses__", "__mro__",
        "__init__", "__new__", "__reduce__", "__getstate__", "__setstate__",
        "__del__", "__call__", "__getattr__", "__setattr__", "__delattr__",
        "__code__", "__globals__", "func_globals", "func_code",
        "__wrapped__", "__closure__",
    })

    # Sub-field names that are sensitive regardless of parent path
    _SENSITIVE_NAMES = frozenset({
        "api_key", "secret", "password", "token", "credential",
        "private_key", "access_token", "refresh_token", "auth",
    })

    RESTRICTED: dict[str, dict[str, Any]] = {
        "max_iterations":        {"type": int, "min": 1,   "max": 100},
        "context_window_tokens": {"type": int, "min": 4096, "max": 1_000_000},
        "model":                 {"type": str, "min_len": 1},
    }

    _MAX_RUNTIME_KEYS = 64
    _MODEL_RUNTIME_FIELDS = frozenset({
        "model",
        "model_preset",
        "context_window_tokens",
    })

    def __init__(self, runtime_control: RuntimeControl, modify_allowed: bool = True) -> None:
        self._runtime_control = runtime_control
        self._modify_allowed = modify_allowed

    def __deepcopy__(self, memo: dict[int, Any]) -> MyTool:
        cls = self.__class__
        result = cls.__new__(cls)
        memo[id(self)] = result
        result._runtime_control = self._runtime_control
        result._modify_allowed = self._modify_allowed
        return result

    @property
    def name(self) -> str:
        return "my"

    @property
    def description(self) -> str:
        base = (
            "Check and set your own runtime state.\n"
            "Actions: check, set.\n"
            "- check (no key): full config overview — start here.\n"
            "- check (key): drill into a value. Dot-paths allowed "
            "(e.g. '_last_usage.prompt_tokens', 'web_config.enable').\n"
            "- set (key, value): change config or store notes in your scratchpad. "
            "Scratchpad keys persist across turns but not restarts.\n"
            "Key values: _current_iteration (current progress), "
            "max_iterations - _current_iteration = remaining iterations.\n"
            "Current routing metadata is available read-only via request.channel, "
            "request.chat_id, and request.sender_id.\n"
            "Use model_preset for session-scoped model or context changes; direct "
            "model/context_window_tokens writes are disabled during active sessions.\n"
            "Note: web_config and exec_config are readable but read-only.\n"
            "\n"
            "When to use:\n"
            "- User asks about your model, settings, or token usage → check that key.\n"
            "- User asks to switch to a named model preset → set model_preset to that preset name.\n"
            "- A tool fails or behaves unexpectedly → check the related config to diagnose.\n"
            "- User asks you to remember a preference for this session → set to store it in your scratchpad.\n"
            "- About to start a large task → check context_window_tokens and max_iterations first."
        )
        if not self._modify_allowed:
            base += "\nREAD-ONLY MODE: set is disabled."
        else:
            base += (
                "\nIMPORTANT: Before setting state, predict the potential impact. "
                "If the operation could cause crashes or instability "
                "(e.g. changing model), warn the user first."
            )
        return base

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["check", "set"],
                    "description": "Action to perform",
                },
                "key": {
                    "type": "string",
                    "description": "Dot-path for check/set. Examples: 'max_iterations', 'workspace', 'provider_retry_mode'. "
                    "Use 'request.channel', 'request.chat_id', or 'request.sender_id' for current routing metadata. "
                    "Use 'model_preset' to switch named model presets. For check without key, shows all config values.",
                },
                "value": {"description": "New value (for set). Type must match target (int for max_iterations/context_window_tokens, str for model/model_preset)."},
            },
            "required": ["action"],
        }

    def _audit(self, action: str, detail: str) -> None:
        ctx = current_request_context()
        session = (
            ctx.session_key or f"{ctx.channel}:{ctx.chat_id}"
            if ctx is not None and ctx.channel
            else "unknown"
        )
        logger.info("self.{} | {} | session:{}", action, detail, session)

    # ------------------------------------------------------------------
    # Path resolution
    # ------------------------------------------------------------------

    def _resolve_path(
        self,
        snapshot: RuntimeSnapshot,
        path: str,
    ) -> tuple[object | None, str | None]:
        parts = path.split(".")
        for part in parts:
            if part in self._DENIED_ATTRS or part.startswith("__"):
                return None, f"'{part}' is not accessible"
            if part in self.BLOCKED:
                return None, f"'{part}' is not accessible"
            if part.lower() in self._SENSITIVE_NAMES:
                return None, f"'{part}' is not accessible"
        obj: object = snapshot.as_mapping()
        for part in parts:
            if not _is_string_mapping(obj):
                return None, f"'{part}' not found"
            if part not in obj:
                return None, f"'{part}' not found in mapping"
            obj = obj[part]
        return obj, None

    @staticmethod
    def _validate_key(key: str | None, label: str = "key") -> str | None:
        if not key or not key.strip():
            return ToolResult.error(f"Error: '{label}' cannot be empty or whitespace")
        return None

    # ------------------------------------------------------------------
    # Smart formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _format_status(
        st: "SubagentStatus | Mapping[str, object]",
        indent: str = "  ",
    ) -> str:
        if isinstance(st, Mapping):
            started_at = st.get("started_at", time.monotonic())
            raw_events = st.get("tool_events", [])
            phase = st.get("phase", "unknown")
            iteration = st.get("iteration", 0)
            usage = st.get("usage", {})
            error = st.get("error")
            stop_reason = st.get("stop_reason")
        else:
            started_at = st.started_at
            raw_events = st.tool_events
            phase = st.phase
            iteration = st.iteration
            usage = st.usage
            error = st.error
            stop_reason = st.stop_reason
        elapsed = time.monotonic() - (
            float(started_at) if isinstance(started_at, (int, float)) else time.monotonic()
        )
        tool_events = cast(list[object], raw_events) if isinstance(raw_events, list) else []
        tool_summaries: list[str] = []
        for raw_event in tool_events[-5:]:
            if not isinstance(raw_event, Mapping):
                continue
            event = cast(Mapping[str, object], raw_event)
            tool_summaries.append(
                f"{event.get('name', '?')}({event.get('status', '?')})"
            )
        tool_summary = ", ".join(tool_summaries) or "none"
        lines = [
            f"{indent}phase: {phase}, iteration: {iteration}, elapsed: {elapsed:.1f}s",
            f"{indent}tools: {tool_summary}",
            f"{indent}usage: {usage or 'n/a'}",
        ]
        if error:
            lines.append(f"{indent}error: {error}")
        if stop_reason:
            lines.append(f"{indent}stop_reason: {stop_reason}")
        return "\n".join(lines)

    @staticmethod
    def _format_value(val: Any, key: str = "") -> str:
        if _is_subagent_status(val):
            header = f"Subagent [{val.task_id}] '{val.label}'"
            detail = MyTool._format_status(val, "  ")
            return f"{header}\n  task: {val.task_description}\n{detail}"
        if _is_subagent_status_snapshot(val):
            header = f"Subagent [{val['task_id']}] '{val['label']}'"
            detail = MyTool._format_status(val, "  ")
            return f"{header}\n  task: {val['task_description']}\n{detail}"
        if isinstance(val, Mapping):
            mapping = cast(Mapping[object, object], val)
        else:
            mapping = None
        if mapping and set(mapping) == {"_task_statuses"}:
            task_statuses = mapping["_task_statuses"]
            if isinstance(task_statuses, Mapping):
                return MyTool._format_value(task_statuses, key)
        if (
            mapping
            and (
                _is_subagent_status(next(iter(mapping.values())))
                or _is_subagent_status_snapshot(next(iter(mapping.values())))
            )
        ):
            prefix = f"{key}: " if key else ""
            lines = [f"{prefix}{len(mapping)} subagent(s):"]
            for tid, st in mapping.items():
                if _is_subagent_status(st):
                    detail = MyTool._format_status(st, "    ")
                    label = st.label
                elif _is_subagent_status_snapshot(st):
                    detail = MyTool._format_status(st, "    ")
                    label = st.get("label", "?")
                else:
                    continue
                lines.append(f"  [{tid}] '{label}'\n{detail}")
            return "\n".join(lines)
        # Scalar types — repr is fine
        if isinstance(val, (str, int, float, bool, type(None))):
            r = repr(val)
            return f"{key}: {r}" if key else r
        # Mapping — small: show content; large: show keys for dot-path navigation
        if isinstance(val, Mapping):
            value_mapping = cast(Mapping[object, object], val)
            ks = list(value_mapping.keys())
            if not ks:
                return f"{key}: {{}}" if key else "{}"
            if len(ks) <= 5:
                r = repr(value_mapping)
                if len(r) <= 200:
                    return f"{key}: {r}" if key else r
            preview = ", ".join(str(k) for k in ks[:15])
            suffix = ", ..." if len(ks) > 15 else ""
            return f"{key}: {{{preview}{suffix}}}" if key else f"{{{preview}{suffix}}}"
        # List/tuple — count for large, repr for small
        if isinstance(val, (list, tuple)):
            sequence = cast(list[object] | tuple[object, ...], val)
            if len(sequence) > 20:
                return f"{key}: [{len(sequence)} items]" if key else f"[{len(sequence)} items]"
            r = repr(sequence)
            return f"{key}: {r}" if key else r
        r = repr(val)
        return f"{key}: {r}" if key else r

    # ------------------------------------------------------------------
    # Action dispatch
    # ------------------------------------------------------------------

    async def execute(
        self,
        action: str,
        key: str | None = None,
        value: Any = None,
        **_kwargs: Any,
    ) -> str:
        if action in ("inspect", "check"):
            return self._inspect(key)
        if not self._modify_allowed:
            return ToolResult.error("Error: set is disabled (tools.my.allow_set is false)")
        if action in ("modify", "set"):
            return self._modify(key, value)
        return f"Unknown action: {action}"

    # -- inspect --

    def _current_runtime_value(self, key: str) -> tuple[bool, Any]:
        request_ctx = current_request_context()
        runtime = request_ctx.runtime if request_ctx is not None else None
        if runtime is None or key not in self._MODEL_RUNTIME_FIELDS:
            return False, None
        values: dict[str, object] = {
            "model": runtime.model,
            "model_preset": runtime.model_preset,
            "context_window_tokens": runtime.context_window_tokens,
        }
        return True, values[key]

    def _inspect(self, key: str | None) -> str:
        if not key:
            return self._inspect_all()
        if key == "request" or key.startswith("request."):
            request_ctx = current_request_context()
            if request_ctx is None:
                return ToolResult.error("Error: current request context is unavailable")
            request_values: dict[str, str | None] = {
                "channel": request_ctx.channel,
                "chat_id": request_ctx.chat_id,
                "sender_id": request_ctx.sender_id,
            }
            if key == "request":
                return self._format_value(request_values, key)
            field = key.removeprefix("request.")
            if field not in self._REQUEST_FIELDS:
                return ToolResult.error(f"Error: '{key}' not found")
            return self._format_value(request_values[field], key)
        if "." not in key:
            found, value = self._current_runtime_value(key)
            if found:
                return self._format_value(value, key)
        snapshot = self._runtime_control.snapshot()
        top = key.split(".")[0]
        if top in self._DENIED_ATTRS or top.startswith("__"):
            return ToolResult.error(f"Error: '{top}' is not accessible")
        obj, err = self._resolve_path(snapshot, key)
        if err:
            if key == "scratchpad":
                return (
                    self._format_value(snapshot.scratchpad, "scratchpad")
                    if snapshot.scratchpad
                    else "scratchpad is empty"
                )
            if "." not in key and key in snapshot.scratchpad:
                return self._format_value(snapshot.scratchpad[key], key)
            return ToolResult.error(f"Error: {err}")
        return self._format_value(obj, key)

    def _inspect_all(self) -> str:
        snapshot = self._runtime_control.snapshot()
        values = snapshot.as_mapping()
        parts: list[str] = []
        for k in self.RESTRICTED:
            found, value = self._current_runtime_value(k)
            parts.append(self._format_value(value if found else values[k], k))
        found, value = self._current_runtime_value("model_preset")
        parts.append(self._format_value(
            value if found else snapshot.model_preset,
            "model_preset",
        ))
        for k in (
            "workspace",
            "provider_retry_mode",
            "max_tool_result_chars",
            "_current_iteration",
            "web_config",
            "exec_config",
            "subagents",
        ):
            parts.append(self._format_value(values[k], k))
        if snapshot.last_usage:
            parts.append(self._format_value(snapshot.last_usage, "_last_usage"))
        if snapshot.scratchpad:
            parts.append(self._format_value(snapshot.scratchpad, "scratchpad"))
        return "\n".join(parts)

    # -- modify --

    def _modify(self, key: str | None, value: Any) -> str:
        if err := self._validate_key(key):
            return err
        key = cast(str, key)
        top = key.split(".")[0]
        if top in self.BLOCKED or top in self._DENIED_ATTRS or top.startswith("__") or top.lower() in self._SENSITIVE_NAMES:
            self._audit("modify", f"BLOCKED {key}")
            return ToolResult.error(f"Error: '{key}' is protected and cannot be modified")
        if top in self.READ_ONLY:
            self._audit("modify", f"READ_ONLY {key}")
            return ToolResult.error(f"Error: '{key}' is read-only and cannot be modified")
        if "." in key:
            parent_path, leaf = key.rsplit(".", 1)
            if leaf in self._DENIED_ATTRS or leaf.startswith("__"):
                self._audit("modify", f"BLOCKED leaf '{leaf}'")
                return ToolResult.error(f"Error: '{leaf}' is not accessible")
            if leaf.lower() in self._SENSITIVE_NAMES:
                self._audit("modify", f"BLOCKED sensitive leaf '{leaf}'")
                return ToolResult.error(f"Error: '{leaf}' is not accessible")
            snapshot = self._runtime_control.snapshot()
            _parent, err = self._resolve_path(snapshot, parent_path)
            if err:
                return ToolResult.error(f"Error: {err}")
            self._audit("modify", f"READ_ONLY {key}")
            return ToolResult.error(f"Error: '{key}' is read-only and cannot be modified")
        if key == "model_preset":
            return self._modify_model_preset(value)
        if key in self.RESTRICTED:
            return self._modify_restricted(key, value)
        if key in RUNTIME_COMMAND_KEYS:
            return self._modify_runtime_setting(key, value)
        if key in RUNTIME_SNAPSHOT_KEYS:
            self._audit("modify", f"READ_ONLY {key}")
            return ToolResult.error(f"Error: '{key}' is read-only and cannot be modified")
        return self._modify_scratchpad(key, value)

    def _modify_model_preset(self, value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            return ToolResult.error("Error: 'model_preset' must be a non-empty string")
        name = value.strip()
        session_key = current_request_session_key()
        old = self._runtime_control.snapshot().model_preset
        try:
            runtime = self._runtime_control.set_model_preset(
                name,
                session_key=session_key,
            )
        except (KeyError, ValueError) as exc:
            message = str(exc.args[0]) if exc.args else str(exc)
            punctuation = "" if message.endswith((".", "!", "?")) else "."
            return ToolResult.error(f"Error: {message}{punctuation}")
        if session_key:
            self._audit("modify", f"model_preset = {name!r}")
            return (
                f"Set model_preset = {name!r} for the next turn; "
                f"model will be {runtime.model!r}; "
                f"context_window_tokens will be {runtime.context_window_tokens!r}"
            )
        self._audit("modify", f"model_preset: {old!r} -> {name!r}")
        return (
            f"Set model_preset = {name!r} (was {old!r}); model is now {runtime.model!r}; "
            f"context_window_tokens is now {runtime.context_window_tokens!r}"
        )

    def _modify_restricted(self, key: str, value: Any) -> str:
        spec = self.RESTRICTED[key]
        expected = cast(type[Any], spec["type"])
        if expected is int and isinstance(value, bool):
            return ToolResult.error(f"Error: '{key}' must be {expected.__name__}, got bool")
        if not isinstance(value, expected):
            try:
                value = expected(value)
            except (ValueError, TypeError):
                return ToolResult.error(f"Error: '{key}' must be {expected.__name__}, got {type(value).__name__}")
        old = self._runtime_control.snapshot().as_mapping()[key]
        if "min" in spec and value < spec["min"]:
            return ToolResult.error(f"Error: '{key}' must be >= {spec['min']}")
        if "max" in spec and value > spec["max"]:
            return ToolResult.error(f"Error: '{key}' must be <= {spec['max']}")
        if "min_len" in spec and len(str(value)) < spec["min_len"]:
            return ToolResult.error(f"Error: '{key}' must be at least {spec['min_len']} characters")
        if key in {"model", "context_window_tokens"} and current_request_session_key():
            return ToolResult.error(
                f"Error: direct '{key}' changes are instance-wide and disabled "
                "during an active session; use a configured model_preset"
            )
        if key == "model":
            self._runtime_control.set_model(cast(str, value))
        elif key == "context_window_tokens":
            self._runtime_control.set_context_window_tokens(cast(int, value))
        else:
            self._runtime_control.set_max_iterations(cast(int, value))
        self._audit("modify", f"{key}: {old!r} -> {value!r}")
        return f"Set {key} = {value!r} (was {old!r})"

    def _modify_runtime_setting(self, key: str, value: Any) -> str:
        old = self._runtime_control.snapshot().as_mapping()[key]
        if key == "workspace":
            if not isinstance(value, str):
                return ToolResult.error(
                    f"Error: 'workspace' expects str, got {type(value).__name__}"
                )
            self._runtime_control.set_workspace_display(value)
            self._audit("modify", f"workspace: {old!r} -> {value!r}")
            return f"Set workspace = {value!r} (was {old!r})"
        old_t = type(old)
        new_t = cast(type[Any], type(value))
        if old_t is float and new_t is int:
            pass
        elif old_t is not new_t:
            self._audit(
                "modify",
                f"REJECTED type mismatch {key}: expects {old_t.__name__}, got {new_t.__name__}",
            )
            return ToolResult.error(
                f"Error: '{key}' expects {old_t.__name__}, got {new_t.__name__}"
            )
        if key == "provider_retry_mode":
            self._runtime_control.set_provider_retry_mode(cast(str, value))
        elif key == "max_tool_result_chars":
            self._runtime_control.set_max_tool_result_chars(cast(int, value))
        else:
            raise AssertionError(f"Unhandled runtime command: {key}")
        self._audit("modify", f"{key}: {old!r} -> {value!r}")
        return f"Set {key} = {value!r} (was {old!r})"

    def _modify_scratchpad(self, key: str, value: Any) -> str:
        if callable(value):
            self._audit("modify", f"REJECTED callable {key}")
            return ToolResult.error("Error: cannot store callable values")
        err = self._validate_json_safe(value)
        if err:
            self._audit("modify", f"REJECTED {key}: {err}")
            return ToolResult.error(f"Error: {err}")
        try:
            self._runtime_control.set_scratchpad(
                key,
                cast(JsonValue, value),
                max_keys=self._MAX_RUNTIME_KEYS,
            )
        except ValueError as exc:
            self._audit("modify", f"REJECTED {key}: max keys ({self._MAX_RUNTIME_KEYS}) reached")
            return ToolResult.error(f"Error: {exc}. Remove unused keys first.")
        self._audit("modify", f"scratchpad.{key} = {value!r}")
        return f"Set scratchpad.{key} = {value!r}"

    @classmethod
    def _validate_json_safe(cls, value: Any, depth: int = 0) -> str | None:
        if depth > 10:
            return "value nesting too deep (max 10 levels)"
        if isinstance(value, (str, int, float, bool, type(None))):
            return None
        if isinstance(value, list):
            for i, item in enumerate(cast(list[Any], value)):
                if err := cls._validate_json_safe(item, depth + 1):
                    return f"list[{i}] contains {err}"
            return None
        if isinstance(value, dict):
            for k, v in cast(dict[Any, Any], value).items():
                if not isinstance(k, str):
                    return f"dict key must be str, got {type(k).__name__}"
                if err := cls._validate_json_safe(v, depth + 1):
                    return f"dict key '{k}' contains {err}"
            return None
        return f"unsupported type {type(value).__name__}"
