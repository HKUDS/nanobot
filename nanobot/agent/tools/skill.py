"""Tool wrapper for skill.py functions."""

import asyncio
import inspect
from pathlib import Path
from typing import Any, Callable

from nanobot.agent.tools.base import Tool


def _py_type_to_json_schema(annotation: type) -> dict[str, Any]:
    """Convert Python type annotation to JSON schema."""
    if annotation is inspect.Parameter.empty:
        return {"type": "string", "description": ""}
    origin = getattr(annotation, "__origin__", None)
    args = getattr(annotation, "__args__", ())

    if origin is None:
        if annotation in (str, type(None)) or annotation is type(None):
            return {"type": "string", "description": ""}
        if annotation in (int,):
            return {"type": "integer", "description": ""}
        if annotation in (float,):
            return {"type": "number", "description": ""}
        if annotation in (bool,):
            return {"type": "boolean", "description": ""}
        if annotation in (list,):
            return {"type": "array", "description": "", "items": {"type": "string"}}
        if annotation in (dict,):
            return {"type": "object", "description": ""}
    if origin is type(None) or (origin is type and None in args):
        return {"type": "string", "description": ""}
    if origin is list and args:
        return {"type": "array", "description": "", "items": _py_type_to_json_schema(args[0])}
    if origin is dict and len(args) >= 2:
        return {"type": "object", "description": ""}
    return {"type": "string", "description": ""}


class SkillFunctionTool(Tool):
    """
    Wraps a Python callable from skill.py as a Tool.
    
    Discovers parameters from the function signature and builds
    a JSON schema for the LLM.
    """

    def __init__(
        self,
        skill_name: str,
        func: Callable[..., Any],
        working_dir: Path | None = None,
    ):
        self._skill_name = skill_name
        self._func = func
        self._working_dir = Path(working_dir) if working_dir else None
        self._name = f"{skill_name}_{func.__name__}"
        self._description = (inspect.getdoc(func) or f"Call {func.__name__} from {skill_name} skill.").strip()
        self._parameters = self._build_parameters()

    def _build_parameters(self) -> dict[str, Any]:
        """Build JSON schema from function signature."""
        sig = inspect.signature(self._func)
        properties: dict[str, Any] = {}
        required: list[str] = []

        for name, param in sig.parameters.items():
            if name in ("self", "cls"):
                continue
            if param.kind in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL):
                continue
            prop = _py_type_to_json_schema(param.annotation)
            if param.default is not inspect.Parameter.empty:
                prop["description"] = prop.get("description", "") or f"Optional. Default: {param.default!r}"
            else:
                required.append(name)
            properties[name] = prop

        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    async def execute(self, **kwargs: Any) -> str:
        """Execute the wrapped function."""
        try:
            if asyncio.iscoroutinefunction(self._func):
                result = await self._func(**kwargs)
            else:
                result = self._func(**kwargs)
            if result is None:
                return ""
            return str(result)
        except Exception as e:
            return f"Error: {e}"
