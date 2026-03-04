"""Feishu document tool stub."""
from nanobot.agent.tools.base import Tool
from nanobot.config.schema import FeishuConfig
from typing import Any


class FeishuDocTool(Tool):
    def __init__(self, cfg: FeishuConfig):
        self._cfg = cfg

    @property
    def name(self) -> str:
        return "feishu_doc"

    @property
    def description(self) -> str:
        return "Feishu document operations."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"action": {"type": "string"}}, "required": ["action"]}

    async def execute(self, **kwargs: Any) -> str:
        return "not implemented"
