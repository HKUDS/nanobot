"""Base class for agent tools.

This module provides the abstract base class for all agent tools, including
support for multimodal tool results (text + images).

Key Components:
- ToolResult: A dataclass for tool execution results that can include images
- Tool: Abstract base class that all tools must implement

Example:
    class MyTool(Tool):
        name = "my_tool"
        description = "Does something useful"

        async def execute(self, **kwargs) -> ToolResult | str:
            # Return string for backward compatibility
            return "Result text"

            # Or return ToolResult for multimodal support
            # return ToolResult(
            #     content="Result text",
            #     images=[{"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}]
            # )
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    """Tool execution result with optional multimodal content.

    This dataclass represents the result of a tool execution. It supports
    both plain text results and multimodal results that include images.

    Attributes:
        content: The text content of the result. This is always required
            and will be sent to the LLM as part of the tool response.
        images: Optional list of image content blocks in OpenAI format.
            Each image should be a dict with format:
            {"type": "image_url", "image_url": {"url": "data:image/...;base64,..."}}

    Example:
        # Text-only result
        result = ToolResult(content="File read successfully")

        # Multimodal result with screenshot
        result = ToolResult(
            content="Screenshot captured",
            images=[{
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{base64_data}"}
            }]
        )

    Note:
        When images are present, the to_message_content() method returns
        a list format suitable for LLM multimodal messages. Otherwise,
        it returns just the text content for backward compatibility.
    """

    content: str
    images: list[dict[str, Any]] | None = None

    def to_message_content(self) -> str | list[dict[str, Any]]:
        """Convert the result to LLM message content format.

        Returns:
            - If no images: returns the content string directly (backward compatible)
            - If images present: returns a list of content blocks in OpenAI format
              [image1, image2, ..., text_block]

        Note:
            Images are placed before text in the returned list, following
            OpenAI's convention for multimodal messages.
        """
        if not self.images:
            return self.content

        # Build multimodal content: images first, then text
        content_blocks: list[dict[str, Any]] = list(self.images)
        content_blocks.append({"type": "text", "text": self.content})
        return content_blocks


class Tool(ABC):
    """
    Abstract base class for agent tools.

    Tools are capabilities that the agent can use to interact with
    the environment, such as reading files, executing commands, etc.

    All tools must implement the following abstract properties and methods:
    - name: A unique identifier for the tool
    - description: A human-readable description of what the tool does
    - parameters: JSON Schema defining the tool's parameters
    - execute: The async method that performs the tool's action

    Return Types:
        The execute() method can return either:
        - str: A plain text result (backward compatible with all existing tools)
        - ToolResult: A structured result that can include images for multimodal
          capable models (e.g., screenshot tools)

    Example:
        class EchoTool(Tool):
            name = "echo"
            description = "Echo back the input message"
            parameters = {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Message to echo"}
                },
                "required": ["message"]
            }

            async def execute(self, message: str, **kwargs) -> str:
                return f"Echo: {message}"
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
    async def execute(self, **kwargs: Any) -> ToolResult | str:
        """Execute the tool with given parameters.

        This is the main entry point for tool execution. Implementations
        should perform the tool's action and return the result.

        Args:
            **kwargs: Tool-specific parameters as defined in the parameters
                property. These are validated against the JSON Schema before
                being passed to this method.

        Returns:
            Either:
            - str: A plain text result (backward compatible)
            - ToolResult: A structured result with optional images for
              multimodal support

        Raises:
            Exception: Implementations may raise exceptions, which will
                be caught by the tool registry and returned as error strings.

        Example:
            async def execute(self, path: str, **kwargs) -> str:
                # Simple text result
                return f"File {path} read successfully"

            async def execute(self, **kwargs) -> ToolResult:
                # Multimodal result with screenshot
                screenshot_bytes = await capture_screenshot()
                b64 = base64.b64encode(screenshot_bytes).decode()
                return ToolResult(
                    content="Screenshot captured",
                    images=[{
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"}
                    }]
                )
        """
        pass

    def cast_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Apply safe schema-driven casts before validation."""
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

        if target_type == "boolean" and isinstance(val, bool):
            return val
        if target_type == "integer" and isinstance(val, int) and not isinstance(val, bool):
            return val
        if target_type in self._TYPE_MAP and target_type not in (
            "boolean",
            "integer",
            "array",
            "object",
        ):
            expected = self._TYPE_MAP[target_type]
            if isinstance(val, expected):
                return val

        if target_type == "integer" and isinstance(val, str):
            try:
                return int(val)
            except ValueError:
                return val

        if target_type == "number" and isinstance(val, str):
            try:
                return float(val)
            except ValueError:
                return val

        if target_type == "string":
            return val if val is None else str(val)

        if target_type == "boolean" and isinstance(val, str):
            val_lower = val.lower()
            if val_lower in ("true", "1", "yes"):
                return True
            if val_lower in ("false", "0", "no"):
                return False
            return val

        if target_type == "array" and isinstance(val, list):
            item_schema = schema.get("items")
            return [self._cast_value(item, item_schema) for item in val] if item_schema else val

        if target_type == "object" and isinstance(val, dict):
            return self._cast_object(val, schema)

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
        if t == "integer" and (not isinstance(val, int) or isinstance(val, bool)):
            return [f"{label} should be integer"]
        if t == "number" and (not isinstance(val, self._TYPE_MAP[t]) or isinstance(val, bool)):
            return [f"{label} should be number"]
        if (
            t in self._TYPE_MAP
            and t not in ("integer", "number")
            and not isinstance(val, self._TYPE_MAP[t])
        ):
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
