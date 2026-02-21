"""Tool wrapper for Python functions defined in skill.py files."""

import asyncio
import inspect
from typing import Any, Callable

from nanobot.agent.tools.base import Tool


class SkillFunctionTool(Tool):
    """Wraps a Python callable from a skill's skill.py as an agent tool."""

    def __init__(self, skill_name: str, func: Callable, func_name: str | None = None):
        self._skill_name = skill_name
        self._func = func
        self._func_name = func_name or func.__name__
        self._tool_name = f"{skill_name}_{self._func_name}"
        self._doc = (func.__doc__ or "").strip()
        self._params = self._build_params()

    @property
    def name(self) -> str:
        return self._tool_name

    @property
    def description(self) -> str:
        return self._doc or f"Run {self._func_name} from skill {self._skill_name}"

    @property
    def parameters(self) -> dict[str, Any]:
        return self._params

    def _build_params(self) -> dict[str, Any]:
        sig = inspect.signature(self._func)
        props: dict[str, Any] = {}
        required: list[str] = []
        type_map = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}
        for pname, param in sig.parameters.items():
            if pname in ("self", "cls"):
                continue
            annotation = param.annotation
            json_type = "string"
            if annotation != inspect.Parameter.empty:
                json_type = type_map.get(annotation, "string")
            props[pname] = {"type": json_type, "description": pname}
            if param.default is inspect.Parameter.empty:
                required.append(pname)
        return {"type": "object", "properties": props, "required": required}

    async def execute(self, **kwargs: Any) -> str:
        try:
            if asyncio.iscoroutinefunction(self._func):
                result = await self._func(**kwargs)
            else:
                result = self._func(**kwargs)
            return str(result) if result is not None else "OK"
        except Exception as e:
            return f"Error in {self._tool_name}: {e}"