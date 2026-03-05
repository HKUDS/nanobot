"""Tool registry for dynamic tool management.

``ToolRegistry`` is the central hub for agent tool execution.  It handles:

- **Registration** — tools are added via ``register()``; duplicates overwrite.
- **Schema export** — ``get_tools_schema()`` returns OpenAI-compatible
  function definitions for LLM tool-use prompting.
- **Validation** — incoming tool-call arguments are validated against the
  tool's JSON Schema ``parameters`` before execution.
- **Execution** — ``execute()`` runs a single tool; the agent loop decides
  whether to run readonly tools in parallel (``asyncio.gather``) or
  sequentially for write tools.
- **Error wrapping** — failures are caught and wrapped in ``ToolResult.fail``
  with a retry hint appended so the LLM can self-correct.
"""

from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool, ToolResult
from nanobot.errors import ToolExecutionError, ToolNotFoundError, ToolValidationError


class ToolRegistry:
    """
    Registry for agent tools.

    Allows dynamic registration and execution of tools.
    """

    _HINT = "\n\n[Analyze the error above and try a different approach.]"

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        """Unregister a tool by name."""
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def get_definitions(self) -> list[dict[str, Any]]:
        """Get all tool definitions in OpenAI format."""
        return [tool.to_schema() for tool in self._tools.values()]

    async def execute(self, name: str, params: dict[str, Any]) -> ToolResult:
        """Execute a tool by name with given parameters.

        Always returns a ``ToolResult``.  Legacy tools that still return a
        bare string are automatically wrapped.
        """
        tool = self._tools.get(name)
        if not tool:
            not_found_err = ToolNotFoundError(name, self.tool_names)
            return ToolResult.fail(str(not_found_err), error_type="not_found")

        try:
            errors = tool.validate_params(params)
            if errors:
                validation_err = ToolValidationError(name, errors)
                return ToolResult.fail(str(validation_err) + self._HINT, error_type="validation")

            raw = await tool.execute(**params)

            # Normalise into ToolResult (supports legacy str returns)
            if isinstance(raw, ToolResult):
                result = raw
            elif isinstance(raw, str):
                # Backward compat: detect old-style "Error…" strings.
                if raw.startswith("Error"):
                    result = ToolResult.fail(raw)
                else:
                    result = ToolResult.ok(raw)
            else:
                result = ToolResult.ok(str(raw))

            # Append retry hint for failures
            if not result.success:
                if not result.output.endswith(self._HINT):
                    result.output += self._HINT

            return result

        except ToolExecutionError as e:
            logger.opt(exception=True).debug("Tool '{}' raised {}", name, e.error_type)
            return ToolResult.fail(str(e) + self._HINT, error_type=e.error_type)
        except Exception as e:
            logger.opt(exception=True).debug("Tool '{}' raised", name)
            return ToolResult.fail(
                f"Error executing {name}: {str(e)}" + self._HINT, error_type="unknown"
            )

    @property
    def tool_names(self) -> list[str]:
        """Get list of registered tool names."""
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
