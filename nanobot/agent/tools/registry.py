"""Tool registry for dynamic tool management."""

import json
import re
from difflib import SequenceMatcher
from typing import Any

from nanobot.agent.tools.base import Tool

_CAMEL_BOUNDARY_RE = re.compile(r"([a-z0-9])([A-Z])")
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_SUGGESTION_MIN_SCORE = 0.84
_SUGGESTION_TIE_MARGIN = 0.08
_SUGGESTION_BIGRAM_MIN_OVERLAP = 0.45
_SUGGESTION_NOISE_TOKENS = frozenset({"call", "function", "tool"})
_SUGGESTION_TOKEN_ALIASES = {
    "cmd": "command",
}
_SuggestionEntry = tuple[str, str, tuple[str, ...], frozenset[str]]


class ToolRegistry:
    """
    Registry for agent tools.

    Allows dynamic registration and execution of tools.
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._cached_definitions: list[dict[str, Any]] | None = None
        self._cached_suggestion_entries: list[_SuggestionEntry] | None = None

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool
        self._cached_definitions = None
        self._cached_suggestion_entries = None

    def unregister(self, name: str) -> None:
        """Unregister a tool by name."""
        self._tools.pop(name, None)
        self._cached_definitions = None
        self._cached_suggestion_entries = None

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    @staticmethod
    def _lookup_key(name: str) -> str:
        """Normalize names for suggestions only; never for execution."""
        return "".join(ch.lower() for ch in name if ch.isalnum())

    @staticmethod
    def _name_tokens(name: str) -> tuple[str, ...]:
        spaced = _CAMEL_BOUNDARY_RE.sub(r"\1 \2", str(name or ""))
        return tuple(
            _SUGGESTION_TOKEN_ALIASES.get(token.lower(), token.lower())
            for token in _TOKEN_RE.findall(spaced)
        )

    @staticmethod
    def _trim_noise_tokens(tokens: tuple[str, ...]) -> tuple[str, ...]:
        end = len(tokens)
        while end and tokens[end - 1] in _SUGGESTION_NOISE_TOKENS:
            end -= 1
        return tokens[:end]

    @classmethod
    def _suggestion_parts(cls, name: str) -> tuple[str, tuple[str, ...], frozenset[str]]:
        tokens = cls._trim_noise_tokens(cls._name_tokens(name))
        key = "".join(tokens) if tokens else cls._lookup_key(name)
        return key, tokens, cls._key_bigrams(key)

    @staticmethod
    def _key_bigrams(key: str) -> frozenset[str]:
        if not key:
            return frozenset()
        if len(key) == 1:
            return frozenset({key})
        return frozenset(key[idx:idx + 2] for idx in range(len(key) - 1))

    @staticmethod
    def _candidate_allowed(
        key: str,
        bigrams: frozenset[str],
        registered_key: str,
        registered_bigrams: frozenset[str],
    ) -> bool:
        if key == registered_key:
            return True
        if abs(len(key) - len(registered_key)) > max(2, len(key) // 3):
            return False
        if not bigrams or not registered_bigrams:
            return False
        overlap = len(bigrams & registered_bigrams) / max(len(bigrams), len(registered_bigrams))
        return overlap >= _SUGGESTION_BIGRAM_MIN_OVERLAP

    @staticmethod
    def _suggestion_score(
        key: str,
        tokens: tuple[str, ...],
        registered_key: str,
        registered_tokens: tuple[str, ...],
    ) -> float:
        key_score = (
            1.0
            if key == registered_key
            else SequenceMatcher(None, key, registered_key).ratio()
        )
        token_score = SequenceMatcher(
            None,
            tokens,
            registered_tokens,
        ).ratio()
        return max(key_score, token_score)

    def _suggestion_entries(self) -> list[_SuggestionEntry]:
        if self._cached_suggestion_entries is None:
            entries = []
            for registered in self._tools:
                key, tokens, bigrams = self._suggestion_parts(registered)
                entries.append((registered, key, tokens, bigrams))
            self._cached_suggestion_entries = entries
        return self._cached_suggestion_entries

    def _suggest_name(self, name: str) -> str | None:
        raw_name = str(name or "")
        key, tokens, bigrams = self._suggestion_parts(raw_name)
        if not key:
            return None
        scored = []
        for registered, registered_key, registered_tokens, registered_bigrams in (
            self._suggestion_entries()
        ):
            if not self._candidate_allowed(key, bigrams, registered_key, registered_bigrams):
                continue
            score = self._suggestion_score(key, tokens, registered_key, registered_tokens)
            scored.append((score, registered))
        if not scored:
            return None
        scored.sort(key=lambda item: item[0], reverse=True)
        best_score, best_name = scored[0]
        if best_score < _SUGGESTION_MIN_SCORE:
            return None
        if len(scored) > 1 and best_score - scored[1][0] < _SUGGESTION_TIE_MARGIN:
            return None
        return best_name

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    @staticmethod
    def _schema_name(schema: dict[str, Any]) -> str:
        """Extract a normalized tool name from either OpenAI or flat schemas."""
        fn = schema.get("function")
        if isinstance(fn, dict):
            name = fn.get("name")
            if isinstance(name, str):
                return name
        name = schema.get("name")
        return name if isinstance(name, str) else ""

    def get_definitions(self) -> list[dict[str, Any]]:
        """Get tool definitions with stable ordering for cache-friendly prompts.

        Built-in tools are sorted first as a stable prefix, then MCP tools are
        sorted and appended.  The result is cached until the next
        register/unregister call.
        """
        if self._cached_definitions is not None:
            return self._cached_definitions

        definitions = [tool.to_schema() for tool in self._tools.values()]
        builtins: list[dict[str, Any]] = []
        mcp_tools: list[dict[str, Any]] = []
        for schema in definitions:
            name = self._schema_name(schema)
            if name.startswith("mcp_"):
                mcp_tools.append(schema)
            else:
                builtins.append(schema)

        builtins.sort(key=self._schema_name)
        mcp_tools.sort(key=self._schema_name)
        self._cached_definitions = builtins + mcp_tools
        return self._cached_definitions

    def prepare_call(
        self,
        name: str,
        params: Any,
    ) -> tuple[Tool | None, Any, str | None]:
        """Resolve, cast, and validate one tool call."""
        tool = self._tools.get(name)
        if not tool:
            suggestion = self._suggest_name(str(name))
            hint = f" Did you mean '{suggestion}'? Tool names must match exactly." if suggestion else ""
            return None, params, (
                f"Error: Tool '{name}' not found.{hint} Available: {', '.join(self.tool_names)}"
            )

        params = self._coerce_params(tool, params)
        if not isinstance(params, dict):
            return tool, params, (
                f"Error: Tool '{name}' parameters must be a JSON object, got "
                f"{type(params).__name__}. Use named parameters matching the tool schema."
            )

        cast_params = tool.cast_params(params)
        errors = tool.validate_params(cast_params)
        if errors:
            return tool, cast_params, (
                f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors)
            )
        return tool, cast_params, None

    @classmethod
    def _coerce_argument_value(cls, value: Any) -> Any:
        if value is None:
            return {}
        if not isinstance(value, str):
            return value

        stripped = value.strip()
        if not stripped:
            return {}

        if not stripped.startswith(("{", "[")) and stripped != "null":
            return value

        try:
            parsed = json.loads(stripped)
        except Exception:
            return value

        return {} if parsed is None else parsed

    @classmethod
    def _coerce_params(cls, tool: Tool, params: Any) -> Any:
        params = cls._coerce_argument_value(params)
        return cls._unwrap_arguments_payload(tool, params)

    @classmethod
    def _unwrap_arguments_payload(cls, tool: Tool, params: Any) -> Any:
        if not isinstance(params, dict) or set(params) != {"arguments"}:
            return params
        properties = (tool.parameters or {}).get("properties", {})
        if isinstance(properties, dict) and "arguments" in properties:
            return params
        return cls._coerce_argument_value(params.get("arguments"))

    async def execute(self, name: str, params: Any) -> Any:
        """Execute a tool by name with given parameters."""
        hint = "\n\n[Analyze the error above and try a different approach.]"
        tool, params, error = self.prepare_call(name, params)
        if error:
            return error + hint

        try:
            assert tool is not None  # guarded by prepare_call()
            result = await tool.execute(**params)
            if isinstance(result, str) and result.startswith("Error"):
                return result + hint
            return result
        except Exception as e:
            return f"Error executing {name}: {str(e)}" + hint

    @property
    def tool_names(self) -> list[str]:
        """Get list of registered tool names."""
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
