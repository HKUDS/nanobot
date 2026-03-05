"""Base class for agent tools."""

from abc import ABC, abstractmethod
from typing import Any

from loguru import logger


class Tool(ABC):
    """
    Abstract base class for agent tools.

    Tools are capabilities that the agent can use to interact with
    the environment, such as reading files, executing commands, etc.
    """

    _TYPE_MAP = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name used in function calls."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Description of what the tool does."""
        pass

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        pass

    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """
        Execute the tool with given parameters.

        Args:
            **kwargs: Tool-specific parameters.

        Returns:
            String result of the tool execution.
        """
        pass

    def cast_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        Attempt to cast parameters to match schema types.
        Returns modified params dict. Raises ValueError if casting is impossible.
        """
        schema = self.parameters or {}
        if schema.get("type", "object") != "object":
            return params

        return self._cast_object(params, schema)

    def _cast_object(self, obj: Any, schema: dict[str, Any]) -> dict[str, Any]:
        """Cast an object (dict) according to schema."""
        if not isinstance(obj, dict):
            return obj

        props = schema.get("properties", {})
        result = {}

        for key, value in obj.items():
            if key in props:
                result[key] = self._cast_value(value, props[key])
            else:
                result[key] = value

        return result

    def _cast_value(self, val: Any, schema: dict[str, Any]) -> Any:
        """Cast a single value according to schema."""
        target_type = schema.get("type")

        # Already correct type
        # Note: check bool before int since bool is subclass of int
        if target_type == "boolean" and isinstance(val, bool):
            return val
        if target_type == "integer" and isinstance(val, int) and not isinstance(val, bool):
            return val
        # For array/object, don't early-return - we need to recurse into contents
        if target_type in self._TYPE_MAP and target_type not in (
            "boolean",
            "integer",
            "array",
            "object",
        ):
            expected = self._TYPE_MAP[target_type]
            if isinstance(val, expected):
                return val

        # Attempt casting
        try:
            if target_type == "integer":
                if isinstance(val, bool):
                    # Don't silently convert bool to int
                    raise ValueError(f"Cannot cast bool to integer")
                if isinstance(val, str):
                    return int(val)
                if isinstance(val, (int, float)):
                    return int(val)

            elif target_type == "number":
                if isinstance(val, bool):
                    # Don't silently convert bool to number
                    raise ValueError(f"Cannot cast bool to number")
                if isinstance(val, str):
                    return float(val)
                if isinstance(val, (int, float)):
                    return float(val)

            elif target_type == "string":
                # Preserve None vs empty string distinction
                if val is None:
                    return val
                return str(val)

            elif target_type == "boolean":
                if isinstance(val, str):
                    return val.lower() in ("true", "1", "yes")
                return bool(val)

            elif target_type == "array":
                if isinstance(val, list):
                    # Recursively cast array items if schema defines items
                    if "items" in schema:
                        return [self._cast_value(item, schema["items"]) for item in val]
                    return val
                # Preserve None vs empty array distinction
                if val is None:
                    return val
                # Try to convert single value to array
                if val == "":
                    return []
                return [val]

            elif target_type == "object":
                if isinstance(val, dict):
                    return self._cast_object(val, schema)
                # Preserve None vs empty object distinction
                if val is None:
                    return val
                # Empty string → empty object
                if val == "":
                    return {}
                # Cannot cast to object
                raise ValueError(f"Cannot cast {type(val).__name__} to object")

        except (ValueError, TypeError) as e:
            # Log failed casts for debugging, return original value
            # Let validation catch the error
            logger.debug("Failed to cast value %r to %s: %s", val, target_type, e)

        return val

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        """Validate tool parameters against JSON schema. Returns error list (empty if valid)."""
        if not isinstance(params, dict):
            return [f"parameters must be an object, got {type(params).__name__}"]
        schema = self.parameters or {}
        if schema.get("type", "object") != "object":
            raise ValueError(f"Schema must be object type, got {schema.get('type')!r}")
        return self._validate(params, {**schema, "type": "object"}, "")

    def _validate(self, val: Any, schema: dict[str, Any], path: str) -> list[str]:
        t, label = schema.get("type"), path or "parameter"
        if t in self._TYPE_MAP and not isinstance(val, self._TYPE_MAP[t]):
            return [f"{label} should be {t}"]

        errors = []
        if "enum" in schema and val not in schema["enum"]:
            errors.append(f"{label} must be one of {schema['enum']}")
        if t in ("integer", "number"):
            if "minimum" in schema and val < schema["minimum"]:
                errors.append(f"{label} must be >= {schema['minimum']}")
            if "maximum" in schema and val > schema["maximum"]:
                errors.append(f"{label} must be <= {schema['maximum']}")
        if t == "string":
            if "minLength" in schema and len(val) < schema["minLength"]:
                errors.append(f"{label} must be at least {schema['minLength']} chars")
            if "maxLength" in schema and len(val) > schema["maxLength"]:
                errors.append(f"{label} must be at most {schema['maxLength']} chars")
        if t == "object":
            props = schema.get("properties", {})
            for k in schema.get("required", []):
                if k not in val:
                    errors.append(f"missing required {path + '.' + k if path else k}")
            for k, v in val.items():
                if k in props:
                    errors.extend(self._validate(v, props[k], path + "." + k if path else k))
        if t == "array" and "items" in schema:
            for i, item in enumerate(val):
                errors.extend(
                    self._validate(item, schema["items"], f"{path}[{i}]" if path else f"[{i}]")
                )
        return errors

    def to_schema(self) -> dict[str, Any]:
        """Convert tool to OpenAI function schema format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
