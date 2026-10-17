"""Base class for agent tools."""
from __future__ import annotations

import json
import math
import typing
import urllib.parse
from abc import ABC, abstractmethod
from collections.abc import Callable
from copy import deepcopy
from typing import Any, TypeVar, cast

if typing.TYPE_CHECKING:
    from pydantic import BaseModel

    from nanobot.agent.tools.context import ToolContext
    from nanobot.runtime_context import RuntimeContextProvider

_ToolT = TypeVar("_ToolT", bound="Tool")

# Matches :meth:`Tool._cast_value` / :meth:`Schema.validate_json_schema_value` behavior
_JSON_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}
_CONTAINER_JSON_TYPES = frozenset(("object", "array"))
_SCHEMA_COMBINATORS = ("oneOf", "anyOf", "allOf")


class Schema(ABC):
    """Abstract base for JSON Schema fragments describing tool parameters.

    Concrete types live in :mod:`nanobot.agent.tools.schema`; all implement
    :meth:`to_json_schema` and :meth:`validate_value`. Class methods
    :meth:`validate_json_schema_value` and :meth:`fragment` are the shared validation and normalization entry points.
    """

    @staticmethod
    def resolve_json_schema_type(t: Any) -> str | None:
        """Resolve the non-null type name from JSON Schema ``type`` (e.g. ``['string','null']`` -> ``'string'``)."""
        if isinstance(t, list):
            types = cast(list[Any], t)
            return cast(str | None, next((x for x in types if x != "null"), None))
        return cast(str | None, t)

    @staticmethod
    def match_json_schema_type(val: Any, types: list[Any]) -> str | None:
        """Select a union member matching the value without coercion."""
        for t in types:
            if not isinstance(t, str) or t not in _JSON_TYPE_MAP:
                continue
            if t in ("integer", "number") and isinstance(val, bool):
                continue
            if isinstance(val, _JSON_TYPE_MAP[t]):
                return t
        return None

    @staticmethod
    def subpath(path: str, key: str) -> str:
        return f"{path}.{key}" if path else key

    @staticmethod
    def validate_json_schema_value(
        val: Any, schema: dict[str, Any] | bool, path: str = "",
    ) -> list[str]:
        """Validate ``val`` against a JSON Schema fragment; returns error messages (empty means valid).

        Used by :class:`Tool` and each concrete Schema's :meth:`validate_value`.
        """
        label = path or "parameter"
        if isinstance(schema, bool):
            return [] if schema else [f"{label} is not allowed by schema"]

        raw_type = schema.get("type")
        nullable = (isinstance(raw_type, list) and "null" in raw_type) or schema.get("nullable", False)
        t = Schema.resolve_json_schema_type(raw_type)

        if (raw_type == "null" or raw_type == ["null"]) and val is not None:
            return [f"{label} should be null"]
        if nullable and val is None:
            if "enum" in schema and val not in schema["enum"]:
                return [f"{label} must be one of {schema['enum']}"]
            return []
        if isinstance(raw_type, list):
            types = [item for item in cast(list[Any], raw_type) if item != "null"]
            if len(types) > 1:
                t = Schema.match_json_schema_type(val, types)
                if t is None:
                    return [f"{label} should match one of the types {types}"]
        if t == "integer" and (not isinstance(val, int) or isinstance(val, bool)):
            return [f"{label} should be integer"]
        if t == "number" and (
            not isinstance(val, _JSON_TYPE_MAP["number"]) or isinstance(val, bool)
        ):
            return [f"{label} should be number"]
        if t in _JSON_TYPE_MAP and t not in ("integer", "number") and not isinstance(val, _JSON_TYPE_MAP[t]):
            return [f"{label} should be {t}"]
        if t == "number" and isinstance(val, float) and not math.isfinite(val):
            return [f"{label} must be finite"]

        errors: list[str] = []
        if "enum" in schema and val not in schema["enum"]:
            errors.append(f"{label} must be one of {schema['enum']}")
        if t in ("integer", "number"):
            if "minimum" in schema and val < schema["minimum"]:
                errors.append(f"{label} must be >= {schema['minimum']}")
            if "maximum" in schema and val > schema["maximum"]:
                errors.append(f"{label} must be <= {schema['maximum']}")
        if t == "string":
            string_value = cast(str, val)
            if "minLength" in schema and len(string_value) < schema["minLength"]:
                errors.append(f"{label} must be at least {schema['minLength']} chars")
            if "maxLength" in schema and len(string_value) > schema["maxLength"]:
                errors.append(f"{label} must be at most {schema['maxLength']} chars")
        if t == "object":
            object_value = cast(dict[str, Any], val)
            props = cast(dict[str, Any], schema.get("properties", {}))
            required = cast(list[Any], schema.get("required", []))
            for k in required:
                if k not in object_value:
                    errors.append(f"missing required {Schema.subpath(path, k)}")
            additional = schema.get("additionalProperties", True)
            for k, v in object_value.items():
                if k in props:
                    errors.extend(Schema.validate_json_schema_value(v, props[k], Schema.subpath(path, k)))
                elif additional is False:
                    errors.append(f"unexpected parameter {Schema.subpath(path, k)}")
                elif isinstance(additional, dict):
                    errors.extend(
                        Schema.validate_json_schema_value(
                            v,
                            cast(dict[str, Any], additional),
                            Schema.subpath(path, k),
                        )
                    )
        if t == "array":
            array_value = cast(list[Any], val)
            if "minItems" in schema and len(array_value) < schema["minItems"]:
                errors.append(f"{label} must have at least {schema['minItems']} items")
            if "maxItems" in schema and len(array_value) > schema["maxItems"]:
                errors.append(f"{label} must be at most {schema['maxItems']} items")
            if "items" in schema:
                prefix = f"{path}[{{}}]" if path else "[{}]"
                for i, item in enumerate(array_value):
                    errors.extend(
                        Schema.validate_json_schema_value(item, schema["items"], prefix.format(i))
                    )
        return errors

    @staticmethod
    def fragment(value: Any) -> dict[str, Any]:
        """Normalize a Schema instance or an existing JSON Schema dict to a fragment dict."""
        # Try to_json_schema first: Schema instances must be distinguished from dicts that are already JSON Schema
        to_js = getattr(value, "to_json_schema", None)
        if callable(to_js):
            return cast(dict[str, Any], to_js())
        if isinstance(value, dict):
            return cast(dict[str, Any], value)
        raise TypeError(f"Expected schema object or dict, got {type(value).__name__}")

    @abstractmethod
    def to_json_schema(self) -> dict[str, Any]:
        """Return a fragment dict compatible with :meth:`validate_json_schema_value`."""
        ...

    def validate_value(self, value: Any, path: str = "") -> list[str]:
        """Validate a single value; returns error messages (empty means pass). Subclasses may override for extra rules."""
        return Schema.validate_json_schema_value(value, self.to_json_schema(), path)


class ToolResult(str):
    """String-compatible tool output with structured status."""

    is_error: bool

    def __new__(cls, content: str, *, is_error: bool = False) -> ToolResult:
        obj = str.__new__(cls, content)
        obj.is_error = is_error
        return obj

    @classmethod
    def error(cls, content: str) -> ToolResult:
        return cls(content, is_error=True)


class Tool(ABC):
    """Agent capability: read files, run commands, etc."""

    _TYPE_MAP = _JSON_TYPE_MAP
    _BOOL_TRUE = frozenset(("true", "1", "yes"))
    _BOOL_FALSE = frozenset(("false", "0", "no"))

    @staticmethod
    def _resolve_type(t: Any) -> str | None:
        """Pick first non-null type from JSON Schema unions like ``['string','null']``."""
        return Schema.resolve_json_schema_type(t)

    @staticmethod
    def _resolve_local_schema_pointer(root: dict[str, Any], ref: str) -> dict[str, Any] | None:
        """Resolve a local ``#/`` pointer. Remote and broken refs return None."""
        if not ref.startswith("#/"):
            return None
        try:
            pointer = urllib.parse.unquote(ref[1:], errors="strict")
        except (UnicodeDecodeError, ValueError):
            return None
        if not pointer.startswith("/"):
            return None
        current: Any = root
        try:
            for raw_part in pointer[1:].split("/"):
                part = raw_part.replace("~1", "/").replace("~0", "~")
                if isinstance(current, dict):
                    current = cast(dict[str, Any], current)[part]
                elif isinstance(current, list):
                    current = cast(list[Any], current)[int(part)]
                else:
                    return None
        except (KeyError, IndexError, TypeError, ValueError):
            return None
        if not isinstance(current, dict):
            return None
        return cast(dict[str, Any], current)

    @staticmethod
    def _is_null_schema(schema: dict[str, Any]) -> bool:
        raw_type = schema.get("type")
        return raw_type == "null" or raw_type == ["null"]

    @staticmethod
    def _type_names(schema: dict[str, Any]) -> frozenset[str] | None:
        """Non-null ``type`` names, or None when the keyword is absent."""
        raw_type = schema.get("type")
        if isinstance(raw_type, str):
            if raw_type == "null":
                return frozenset()
            return frozenset((raw_type,))
        if isinstance(raw_type, list):
            return frozenset(
                item
                for item in cast(list[Any], raw_type)
                if isinstance(item, str) and item != "null"
            )
        return None

    @staticmethod
    def _schema_allows_string(
        schema: dict[str, Any],
        root: dict[str, Any] | None,
        seen: frozenset[str],
    ) -> bool:
        """True when a branch explicitly accepts a string, not merely a typeless schema."""
        ref = schema.get("$ref")
        if isinstance(ref, str):
            if root is None or ref in seen or not ref.startswith("#/"):
                return False
            resolved = Tool._resolve_local_schema_pointer(root, ref)
            if resolved is None:
                return False
            next_seen = seen | {ref}
            if Tool._schema_allows_string(resolved, root, next_seen):
                return True
            if any(key in schema for key in ("type", *_SCHEMA_COMBINATORS)):
                sibling = {key: value for key, value in schema.items() if key != "$ref"}
                return Tool._schema_allows_string(sibling, root, next_seen)
            return False
        names = Tool._type_names(schema)
        if names is not None and "string" in names:
            return True
        for key in _SCHEMA_COMBINATORS:
            branches = schema.get(key)
            if not isinstance(branches, list):
                continue
            for item in cast(list[Any], branches):
                if isinstance(item, dict) and Tool._schema_allows_string(
                    cast(dict[str, Any], item), root, seen,
                ):
                    return True
        return False

    @staticmethod
    def _declared_type_names(
        schema: dict[str, Any],
        root: dict[str, Any] | None,
        seen: frozenset[str],
    ) -> frozenset[str] | None:
        """Declared types after local ref resolution. Empty means the ref is unusable."""
        own = Tool._type_names(schema)
        ref = schema.get("$ref")
        if not isinstance(ref, str):
            return own
        if root is None or ref in seen or not ref.startswith("#/"):
            return frozenset() if own is None else own
        resolved = Tool._resolve_local_schema_pointer(root, ref)
        if resolved is None:
            return frozenset() if own is None else own
        resolved_names = Tool._declared_type_names(resolved, root, seen | {ref})
        if own is None:
            return resolved_names
        if resolved_names is None:
            return own
        return own & resolved_names

    @staticmethod
    def _container_type_names(schema: dict[str, Any]) -> frozenset[str] | None:
        """Container types from ``type``. None when the keyword is absent.

        Empty when ``type`` is present but is not only ``object`` and/or ``array``.
        """
        names = Tool._type_names(schema)
        if names is None:
            return None
        if not names or not names <= _CONTAINER_JSON_TYPES:
            return frozenset()
        return names

    @staticmethod
    def _union_container_targets(
        branches: list[Any],
        root: dict[str, Any] | None,
        seen: frozenset[str],
    ) -> frozenset[str] | None:
        """Union of container types when every non-null branch is a container."""
        targets: set[str] = set()
        saw_branch = False
        for item in branches:
            if not isinstance(item, dict):
                return None
            branch = cast(dict[str, Any], item)
            if Tool._is_null_schema(branch):
                continue
            saw_branch = True
            branch_targets = Tool._structured_json_targets(branch, root, seen)
            if not branch_targets:
                return None
            targets.update(branch_targets)
        if not saw_branch:
            return None
        return frozenset(targets)

    @staticmethod
    def _branches_allow_string(
        branches: list[Any],
        root: dict[str, Any] | None,
        seen: frozenset[str],
    ) -> bool:
        for item in branches:
            if not isinstance(item, dict):
                return True
            if Tool._schema_allows_string(cast(dict[str, Any], item), root, seen):
                return True
        return False

    @staticmethod
    def _intersection_container_targets(
        branches: list[Any],
        root: dict[str, Any] | None,
        seen: frozenset[str],
    ) -> frozenset[str] | None:
        """Containers required by an ``allOf`` intersection.

        None when no branch requires a container. Empty when decoding is unsafe:
        a branch allows a string, excludes containers, or the intersection is empty.
        """
        collected: list[frozenset[str]] = []
        for item in branches:
            if not isinstance(item, dict):
                return frozenset()
            branch = cast(dict[str, Any], item)
            if Tool._schema_allows_string(branch, root, seen):
                return frozenset()
            declared = Tool._declared_type_names(branch, root, seen)
            if declared is not None and declared.isdisjoint(_CONTAINER_JSON_TYPES):
                return frozenset()
            branch_targets = Tool._structured_json_targets(branch, root, seen)
            if branch_targets:
                collected.append(branch_targets)
        if not collected:
            return None
        result = collected[0]
        for item_targets in collected[1:]:
            result &= item_targets
        return result

    @staticmethod
    def _structured_json_targets(
        schema: dict[str, Any],
        root: dict[str, Any] | None = None,
        seen: frozenset[str] | None = None,
    ) -> frozenset[str]:
        """Object or array types a JSON string may be decoded into.

        Empty when a string is allowed, the schema does not require a container,
        or a local ref cannot be resolved. ``allOf`` intersects container
        constraints instead of unioning them like ``oneOf`` and ``anyOf``.
        """
        if seen is None:
            seen = frozenset()
        ref = schema.get("$ref")
        if isinstance(ref, str):
            if root is None or ref in seen or not ref.startswith("#/"):
                return frozenset()
            resolved = Tool._resolve_local_schema_pointer(root, ref)
            if resolved is None:
                return frozenset()
            next_seen = seen | {ref}
            if not any(key in schema for key in ("type", *_SCHEMA_COMBINATORS)):
                return Tool._structured_json_targets(resolved, root, next_seen)
            sibling = {key: value for key, value in schema.items() if key != "$ref"}
            return Tool._structured_json_targets(
                {"allOf": [resolved, sibling]}, root, next_seen,
            )

        pieces: list[frozenset[str]] = []
        type_targets = Tool._container_type_names(schema)
        if type_targets is not None:
            if not type_targets:
                return frozenset()
            pieces.append(type_targets)

        all_of = schema.get("allOf")
        if isinstance(all_of, list) and all_of:
            intersected = Tool._intersection_container_targets(
                cast(list[Any], all_of), root, seen,
            )
            if intersected is not None:
                if not intersected:
                    return frozenset()
                pieces.append(intersected)

        for key in ("oneOf", "anyOf"):
            raw_branches = schema.get(key)
            if not isinstance(raw_branches, list) or not raw_branches:
                continue
            branches = cast(list[Any], raw_branches)
            union = Tool._union_container_targets(branches, root, seen)
            if union:
                pieces.append(union)
                continue
            # Not every branch is a container. A sibling container type still
            # applies when no branch explicitly allows a string.
            if Tool._branches_allow_string(branches, root, seen):
                return frozenset()

        if not pieces:
            return frozenset()
        result = pieces[0]
        for piece in pieces[1:]:
            result &= piece
        return result

    def _decode_structured_json(self, val: str, schema: dict[str, Any]) -> Any:
        """Parse a JSON object/array string when the schema expects that container."""
        targets = self._structured_json_targets(schema, self.parameters, frozenset())
        if not targets:
            return val
        stripped = val.strip()
        if not stripped.startswith(("{", "[")):
            return val
        try:
            parsed: object = json.loads(stripped)
        except Exception:
            return val
        if isinstance(parsed, dict) and "object" in targets:
            return cast(dict[str, Any], parsed)
        if isinstance(parsed, list) and "array" in targets:
            return cast(list[Any], parsed)
        return val

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name used in function calls."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Description of what the tool does."""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        ...

    @property
    def read_only(self) -> bool:
        """Whether this tool is side-effect free and safe to parallelize."""
        return False

    @property
    def concurrency_safe(self) -> bool:
        """Whether this tool can run alongside other concurrency-safe tools."""
        return self.read_only and not self.exclusive

    @property
    def exclusive(self) -> bool:
        """Whether this tool should run alone even if concurrency is enabled."""
        return False

    # --- Plugin metadata ---

    config_key: str = ""
    _plugin_discoverable: bool = True
    _scopes: set[str] = {"core"}

    @classmethod
    def config_cls(cls) -> type[BaseModel] | None:
        return None

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return True

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        return cls()

    def runtime_context_provider(self) -> RuntimeContextProvider | None:
        """Return optional per-turn prompt context owned by this tool."""
        return None

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Any:
        """Run the tool; return content, or ``ToolResult.error(...)`` for failures."""
        ...

    @staticmethod
    def error(content: str) -> ToolResult:
        return ToolResult.error(content)

    def _cast_object(self, obj: Any, schema: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(obj, dict):
            return obj
        props = cast(dict[str, Any], schema.get("properties", {}))
        additional = schema.get("additionalProperties")
        casted: dict[str, Any] = {}
        object_value = cast(dict[str, Any], obj)
        for k, v in object_value.items():
            if k in props:
                casted[k] = self._cast_value(v, props[k])
            elif isinstance(additional, dict):
                casted[k] = self._cast_value(v, cast(dict[str, Any], additional))
            else:
                casted[k] = v
        return casted

    def cast_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Apply safe schema-driven casts before validation."""
        schema = self.parameters or {}
        if schema.get("type", "object") != "object":
            return params
        return self._cast_object(params, schema)

    def _cast_value(self, val: Any, schema: dict[str, Any] | bool) -> Any:
        if isinstance(schema, bool):
            return val
        if isinstance(val, str):
            val = self._decode_structured_json(val, schema)
        raw_type = schema.get("type")
        t = self._resolve_type(raw_type)
        if isinstance(raw_type, list):
            types = [item for item in cast(list[Any], raw_type) if item != "null"]
            if len(types) > 1:
                # A union does not imply a preferred type or a safe conversion target.
                t = Schema.match_json_schema_type(val, types)
                if t is None:
                    return val

        if t == "boolean" and isinstance(val, bool):
            return val
        if t == "integer" and isinstance(val, int) and not isinstance(val, bool):
            return val
        if t in self._TYPE_MAP and t not in ("boolean", "integer", "array", "object"):
            expected = self._TYPE_MAP[t]
            if isinstance(val, expected):
                return val

        if isinstance(val, str) and t in ("integer", "number"):
            try:
                return int(val) if t == "integer" else float(val)
            except ValueError:
                return val

        if t == "string":
            return val if val is None else str(val)

        if t == "boolean" and isinstance(val, str):
            low = val.lower()
            if low in self._BOOL_TRUE:
                return True
            if low in self._BOOL_FALSE:
                return False
            return val

        if t == "array" and isinstance(val, list):
            items = schema.get("items")
            array_value = cast(list[Any], val)
            return [self._cast_value(x, items) for x in array_value] if items else array_value

        if t == "object" and isinstance(val, dict):
            return self._cast_object(val, schema)

        return val

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        """Validate against JSON schema; empty list means valid."""
        if not isinstance(cast(object, params), dict):
            return [f"parameters must be an object, got {type(params).__name__}"]
        schema = self.parameters or {}
        if schema.get("type", "object") != "object":
            raise ValueError(f"Schema must be object type, got {schema.get('type')!r}")
        return Schema.validate_json_schema_value(params, {**schema, "type": "object"}, "")

    def to_schema(self) -> dict[str, Any]:
        """OpenAI function schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def tool_parameters(schema: dict[str, Any]) -> Callable[[type[_ToolT]], type[_ToolT]]:
    """Class decorator: attach JSON Schema and inject a concrete ``parameters`` property.

    Use on ``Tool`` subclasses instead of writing ``@property def parameters``. The
    schema is stored on the class and returned as a fresh copy on each access.

    Example::

        @tool_parameters({
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        })
        class ReadFileTool(Tool):
            ...
    """

    def decorator(cls: type[_ToolT]) -> type[_ToolT]:
        frozen = deepcopy(schema)

        @property
        def parameters(self: Any) -> dict[str, Any]:
            return deepcopy(frozen)

        cls.parameters = parameters  # type: ignore[assignment]

        abstract = getattr(cls, "__abstractmethods__", None)
        if abstract is not None and "parameters" in abstract:
            cls.__abstractmethods__ = frozenset(abstract - {"parameters"})  # type: ignore[misc]

        return cls

    return decorator
