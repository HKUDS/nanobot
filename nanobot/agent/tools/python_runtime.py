"""Stateful Python code execution tools wrapping cave-agent's IPython/IPyKernel runtime.

Provides a ``PythonRuntimeManager`` that owns the cave-agent runtime lifecycle,
and three ``Tool`` subclasses that share a single manager instance:

- ``PythonExecuteTool`` (name="python") — main code execution with dynamic description
- ``PythonResetTool`` (name="python_reset") — resets the runtime
- ``PythonDescribeTool`` (name="python_describe") — returns current namespace description

``PythonRuntimeTool`` is kept as a backward-compatibility alias for ``PythonExecuteTool``.
"""

from __future__ import annotations

import asyncio
import traceback
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema

if TYPE_CHECKING:
    from nanobot.config.schema import SecurityRulesConfig

# ---------------------------------------------------------------------------
# Lazy import helpers — cave-agent may not be installed, so we import
# conditionally and give clear error messages.
# ---------------------------------------------------------------------------

_RUNTIME_IMPORT_ERROR = None
_IPythonRuntime = None
_IPyKernelRuntime = None
_Variable = None
_Function = None
_Type = None
_SecurityChecker = None


def _ensure_cave_agent() -> None:
    """Lazy-import cave-agent core types; raise clear error if missing."""
    global _RUNTIME_IMPORT_ERROR, _IPythonRuntime, _IPyKernelRuntime
    global _Variable, _Function, _Type, _SecurityChecker

    if _IPythonRuntime is not None:
        return

    try:
        from cave_agent.runtime.ipython_runtime import IPythonRuntime
        from cave_agent.runtime.primitives import Function, Type, Variable
        from cave_agent.security import SecurityChecker

        _IPythonRuntime = IPythonRuntime
        _IPyKernelRuntime = None
        _Variable = Variable
        _Function = Function
        _Type = Type
        _SecurityChecker = SecurityChecker
        _RUNTIME_IMPORT_ERROR = None
    except ImportError as exc:
        _RUNTIME_IMPORT_ERROR = ImportError(
            "cave-agent is required for PythonRuntimeTool. "
            "Install it with: pip install 'cave-agent[all]'"
        )
        raise _RUNTIME_IMPORT_ERROR from exc


def _get_ipykernel_runtime() -> type:
    try:
        from cave_agent.runtime.ipykernel_runtime import IPyKernelRuntime

        return IPyKernelRuntime
    except ImportError:
        raise ImportError(
            "IPyKernelRuntime requires ipykernel and dill. "
            "Install with: pip install 'cave-agent[ipykernel]'"
        )


# ---------------------------------------------------------------------------
# PythonRuntimeManager — owns the cave-agent runtime lifecycle
# ---------------------------------------------------------------------------


class PythonRuntimeManager:
    """Manages the cave-agent IPython/IPyKernel runtime lifecycle.

    Provides execution, namespace management, and cleanup APIs.
    Shared by all Python-related Tool classes.
    """

    _MAX_OUTPUT = 10_000
    _MAX_TRACEBACK = 2_000

    def __init__(
        self,
        *,
        backend: str = "ipython",
        security_rules: list | None = None,
        security_config: SecurityRulesConfig | None = None,
        max_output_chars: int = 10_000,
        timeout: int = 60,
        inject_functions: list[dict] | None = None,
        inject_variables: list[dict] | None = None,
        inject_types: list[dict] | None = None,
    ):
        _ensure_cave_agent()

        if security_config and not security_rules:
            from cave_agent.security import AttributeRule, FunctionRule, ImportRule

            rules: list = []
            if security_config.blocked_imports:
                rules.append(ImportRule(set(security_config.blocked_imports)))
            if security_config.blocked_functions:
                rules.append(FunctionRule(set(security_config.blocked_functions)))
            if security_config.blocked_attributes:
                rules.append(AttributeRule(set(security_config.blocked_attributes)))
            security_rules = rules or None

        self._backend = backend
        self._security_rules = security_rules
        self._max_output = max_output_chars
        self._timeout = timeout
        self._inject_functions = inject_functions or []
        self._inject_variables = inject_variables or []
        self._inject_types = inject_types or []
        self._runtime: Any = None  # initialized lazily in _ensure_runtime()
        self._started = False

    # ------------------------------------------------------------------
    # Runtime lifecycle
    # ------------------------------------------------------------------

    async def _ensure_runtime(self) -> Any:
        """Lazily initialize the cave-agent runtime."""
        if self._runtime is not None:
            return self._runtime

        _ensure_cave_agent()

        checker = None
        if self._security_rules:
            checker = _SecurityChecker(self._security_rules)

        if self._backend == "ipykernel":
            IPyKernelRuntime = _get_ipykernel_runtime()
            self._runtime = IPyKernelRuntime(security_checker=checker)
            # NOTE: _executor.start() is a private API of IPyKernelRuntime — file upstream issue if it breaks
            await self._runtime._executor.start()
        else:
            self._runtime = _IPythonRuntime(security_checker=checker)

        # Pre-inject configured objects
        for item in self._inject_variables:
            self._runtime.inject_variable(
                _Variable(item["name"], item["value"], item.get("description", ""))
            )
        for item in self._inject_functions:
            self._runtime.inject_function(
                _Function(item["func"], description=item.get("description", ""))
            )
        for item in self._inject_types:
            self._runtime.inject_type(_Type(item["cls"], description=item.get("description", "")))

        self._started = True
        logger.info("PythonRuntimeManager initialized (backend={})", self._backend)
        return self._runtime

    async def reset(self) -> None:
        """Reset the runtime kernel. Registered injections (variables/functions/types) are preserved and will be re-injected on next execute."""
        if self._runtime is not None:
            await self._runtime.reset()
            for item in self._inject_variables:
                self._runtime.inject_variable(
                    _Variable(item["name"], item["value"], item.get("description", ""))
                )
            for item in self._inject_functions:
                self._runtime.inject_function(
                    _Function(item["func"], description=item.get("description", ""))
                )
            for item in self._inject_types:
                self._runtime.inject_type(
                    _Type(item["cls"], description=item.get("description", ""))
                )
            logger.info("PythonRuntimeManager reset")

    async def cleanup(self) -> None:
        if self._runtime is None:
            return
        if hasattr(self._runtime, "shutdown"):
            await self._runtime.shutdown()
        else:
            await self.reset()
        self._runtime = None
        self._started = False
        logger.info("PythonRuntimeManager cleaned up")

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(self, code: str) -> str:
        """Execute Python code in the stateful runtime.

        Args:
            code: Python code to execute.

        Returns:
            stdout output or error message.
        """
        runtime = await self._ensure_runtime()

        try:
            result = await asyncio.wait_for(runtime.execute(code), timeout=self._timeout)
        except asyncio.TimeoutError:
            return f"Error: Code execution timed out after {self._timeout}s"
        except Exception as exc:
            logger.warning("PythonRuntime execution error: {}", exc)
            if await self._is_runtime_dead():
                logger.info("PythonRuntime appears dead, attempting restart...")
                self._runtime = None
                self._started = False
                try:
                    runtime = await self._ensure_runtime()
                    return f"Runtime crashed and was restarted. Previous error: {exc}\nPlease retry your code."
                except Exception as restart_exc:
                    return self._format_error(restart_exc)
            return self._format_error(exc)

        if result.success:
            output = result.stdout or "(no output)"
        else:
            output = self._format_error(result.error)

        if len(output) > self._max_output:
            half = self._max_output // 2
            output = (
                output[:half]
                + f"\n\n... ({len(output) - self._max_output:,} chars truncated) ...\n\n"
                + output[-half:]
            )

        return output

    # ------------------------------------------------------------------
    # Namespace management (public API for nanobot integration)
    # ------------------------------------------------------------------

    def inject_variable(self, name: str, value: Any, description: str = "") -> None:
        """Inject a Python object into the runtime namespace.

        The object will be available as a global variable in subsequent code.
        If the runtime hasn't started yet, the injection is deferred.
        """
        if self._runtime is not None:
            self._runtime.inject_variable(_Variable(name, value, description))
        else:
            self._inject_variables.append(
                {"name": name, "value": value, "description": description}
            )

    def inject_function(self, func: Any, description: str = "") -> None:
        """Inject a callable into the runtime namespace."""
        if self._runtime is not None:
            self._runtime.inject_function(_Function(func, description=description))
        else:
            self._inject_functions.append({"func": func, "description": description})

    def inject_type(self, cls: type, description: str = "") -> None:
        """Inject a type/class into the runtime namespace."""
        if self._runtime is not None:
            self._runtime.inject_type(_Type(cls, description=description))
        else:
            self._inject_types.append({"cls": cls, "description": description})

    async def retrieve(self, name: str) -> Any:
        """Retrieve a variable value from the namespace."""
        runtime = await self._ensure_runtime()
        return await runtime.retrieve(name)

    def describe_namespace(self, max_chars: int = 2000) -> str:
        """Generate a text description of the namespace for system prompt injection."""
        if self._runtime is None:
            description = self._describe_pending_injections()
        else:
            description = self._describe_active_runtime()
        if len(description) > max_chars:
            lines = description.split("\n")
            truncated = []
            total = 0
            skipped = 0
            for line in lines:
                if total + len(line) + 1 > max_chars:
                    skipped += 1
                else:
                    truncated.append(line)
                    total += len(line) + 1
            description = "\n".join(truncated)
            if skipped:
                description += (
                    f"\n... ({skipped} more items, description truncated at {max_chars} chars)"
                )
        return description

    def _describe_pending_injections(self) -> str:
        """Describe objects that will be injected on first use."""
        parts = []
        if self._inject_functions:
            lines = []
            for item in self._inject_functions:
                func = item["func"]
                desc = item.get("description", "") or (func.__doc__ or "").strip().split("\n")[0]
                sig = getattr(func, "__annotations__", {})
                params = ", ".join(
                    f"{k}: {v.__name__ if hasattr(v, '__name__') else v}"
                    for k, v in sig.items()
                    if k != "return"
                )
                lines.append(f"  {func.__name__}({params}) — {desc}")
            parts.append("Functions:\n" + "\n".join(lines))
        if self._inject_variables:
            lines = []
            for item in self._inject_variables:
                vtype = type(item["value"]).__name__
                desc = item.get("description", "")
                lines.append(f"  {item['name']} ({vtype}): {desc}")
            parts.append("Variables:\n" + "\n".join(lines))
        if self._inject_types:
            lines = []
            for item in self._inject_types:
                desc = item.get("description", "")
                lines.append(f"  {item['cls'].__name__}: {desc}")
            parts.append("Types:\n" + "\n".join(lines))
        return "\n\n".join(parts) if parts else "Empty namespace"

    def _describe_active_runtime(self) -> str:
        """Describe objects currently in the active runtime."""
        try:
            parts = []
            funcs = self._runtime.describe_functions()
            vars_ = self._runtime.describe_variables()
            types = self._runtime.describe_types()
            if funcs and "No functions" not in funcs:
                parts.append(f"Functions:\n{funcs}")
            if vars_ and "No variables" not in vars_:
                parts.append(f"Variables:\n{vars_}")
            if types and "No types" not in types:
                parts.append(f"Types:\n{types}")
            return "\n\n".join(parts) if parts else "Empty namespace"
        except Exception:
            logger.warning("Failed to describe active runtime namespace", exc_info=True)
            return "Namespace unavailable (runtime error)"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _is_runtime_dead(self) -> bool:
        if self._runtime is None:
            return True
        try:
            result = await asyncio.wait_for(self._runtime.execute("1"), timeout=5)
            return not result.success
        except (asyncio.TimeoutError, Exception):
            return True

    def _format_error(self, exc: BaseException | None) -> str:
        """Format an error for LLM consumption."""
        if exc is None:
            return "Error: unknown execution failure"
        name = type(exc).__name__
        msg = str(exc)
        tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
        tb_str = "".join(tb)
        if len(tb_str) > self._MAX_TRACEBACK:
            tb_str = tb_str[: self._MAX_TRACEBACK] + "\n... (traceback truncated)"
        return f"Error: {name}: {msg}\n\nTraceback:\n{tb_str}"


# ---------------------------------------------------------------------------
# Tool implementations — thin wrappers that delegate to the manager
# ---------------------------------------------------------------------------


@tool_parameters(
    tool_parameters_schema(
        code=StringSchema(
            "Python code to execute in the stateful runtime. "
            "Variables, imports, and functions persist across calls. "
            "Use print() to see output.",
        ),
        required=["code"],
    )
)
class PythonExecuteTool(Tool):
    """Stateful Python execution backed by cave-agent's IPython/IPyKernel runtime."""

    def __init__(self, *, manager: PythonRuntimeManager) -> None:
        self._manager = manager

    @property
    def name(self) -> str:
        return "python"

    @property
    def description(self) -> str:
        base = (
            "Execute Python code in a STATEFUL runtime. "
            "Variables, imports, and functions persist across calls — "
            "like a Jupyter notebook where each call is a new cell. "
            "Use print() to see output. "
            "Prefer this over exec for data analysis, object manipulation, "
            "and multi-step Python workflows."
        )
        ns = self._manager.describe_namespace(max_chars=1500)
        if ns and "Empty namespace" not in ns:
            return f"{base}\n\nCurrent namespace:\n{ns}"
        return base

    @property
    def exclusive(self) -> bool:
        return True  # modifies namespace state

    @property
    def read_only(self) -> bool:
        return False

    async def execute(self, code: str, **kwargs: Any) -> str:
        return await self._manager.execute(code)


class PythonResetTool(Tool):
    """Reset the Python runtime state."""

    def __init__(self, *, manager: PythonRuntimeManager) -> None:
        self._manager = manager

    @property
    def name(self) -> str:
        return "python_reset"

    @property
    def description(self) -> str:
        return (
            "Reset the Python runtime. Clears all variables, imports, and functions "
            "from the namespace. Use when the runtime is in a bad state or you want "
            "a clean slate."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_parameters_schema()

    @property
    def exclusive(self) -> bool:
        return True

    @property
    def read_only(self) -> bool:
        return False

    async def execute(self, **kwargs: Any) -> str:
        try:
            await self._manager.reset()
            return (
                "Runtime reset. All variables and imports cleared. Configured injections preserved."
            )
        except Exception as exc:
            logger.warning("PythonResetTool error: {}", exc)
            return f"Error: Failed to reset runtime — {exc}"


class PythonDescribeTool(Tool):
    """Show the current Python namespace."""

    def __init__(self, *, manager: PythonRuntimeManager) -> None:
        self._manager = manager

    @property
    def name(self) -> str:
        return "python_describe"

    @property
    def description(self) -> str:
        return "Show the current Python namespace — all variables, functions, and types available in the runtime."

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_parameters_schema()

    @property
    def exclusive(self) -> bool:
        return False

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        try:
            return self._manager.describe_namespace()
        except Exception as exc:
            logger.warning("PythonDescribeTool error: {}", exc)
            return f"Error: Failed to describe namespace — {exc}"


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

# PythonRuntimeTool is now constructed via PythonRuntimeManager.
# We provide a factory-like constructor that creates a manager and delegates.
# This preserves the existing constructor signature so downstream code
# (loop.py, tests) can keep doing PythonRuntimeTool(backend=..., ...) unchanged.


class PythonRuntimeTool(PythonExecuteTool):
    """Backward-compatible alias for PythonExecuteTool.

    Accepts the same constructor parameters as the original PythonRuntimeTool
    and internally creates a PythonRuntimeManager + PythonExecuteTool.
    """

    def __init__(
        self,
        *,
        backend: str = "ipython",
        security_rules: list | None = None,
        security_config: SecurityRulesConfig | None = None,
        max_output_chars: int = 10_000,
        timeout: int = 60,
        inject_functions: list[dict] | None = None,
        inject_variables: list[dict] | None = None,
        inject_types: list[dict] | None = None,
    ):
        self._runtime_manager = PythonRuntimeManager(
            backend=backend,
            security_rules=security_rules,
            security_config=security_config,
            max_output_chars=max_output_chars,
            timeout=timeout,
            inject_functions=inject_functions,
            inject_variables=inject_variables,
            inject_types=inject_types,
        )
        super().__init__(manager=self._runtime_manager)
