"""Agent tools: unified mode management with add, remove, update, list, and switch methods."""

from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.providers.providers_manager import ProvidersManager


class AgentModeTool(Tool):
    """
    Unified tool for agent mode management.

    Supports 5 methods:
    - add: Add a new model configuration
    - remove: Remove an existing model configuration
    - update: Update an existing model configuration
    - list: List all available models
    - switch: Switch to a specific model mode
    """

    def __init__(self, provider: ProvidersManager):
        """Initialize the agent mode tool with workspace and provider."""
        self.provider = provider

    @property
    def name(self) -> str:
        return "agent_mode"

    @property
    def description(self) -> str:
        return (
            "Unified tool for managing agent LLM modes. "
            "Supports: add (add model), remove (remove model), update (update model), "
            "list (list all models), switch (switch to a mode)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "enum": ["add", "remove", "update", "list", "switch"],
                    "description": "The method to perform: add, remove, update, list, or switch",
                },
                "mode": {
                    "type": "string",
                    "description": "Mode name (e.g., 'common', 'coding', 'multimodal'). Required for all methods except list.",
                    "default": "common",
                },
                # Additional parameters for add/update
                "model": {
                    "type": "string",
                    "description": "Model identifier (e.g., 'openai/qwen3.5:cloud'). Required for add and update methods.",
                },
                # Additional parameters for add
                "describe": {
                    "type": "string",
                    "description": "Description of the model. Required for add and update methods.",
                },
            },
            "required": ["method"],
        }

    async def execute(self, method: str, mode: str = "common", **kwargs: Any) -> str:
        """Execute the specified method."""

        method = method.lower()
        if method == "list":
            return await self._list_modes()
        elif method == "switch":
            return await self._switch_mode(mode)
        elif method == "add":
            return await self._add_model(mode, kwargs.get("model"), kwargs.get("describe"))
        elif method == "remove":
            return await self._remove_model(mode)
        elif method == "update":
            return await self._update_model(mode, kwargs.get("model"), kwargs.get("describe"))
        else:
            return f"Error: Unknown method '{method}'. Supported methods: add, remove, update, list, switch"

    async def _list_modes(self) -> str:
        """List all available modes."""
        models = self.provider.list_models()
        lines = [
            "## Available Models",
            "",
            "| Mode | Model | Description |",
            "|------|-------|-------------|",
        ]
        for model in models:
            name = model.get("name", "unknown")
            model_id = model.get("model", "unknown")
            desc = model.get("describe", "unknown")
            lines.append(f"| {name} | {model_id} | {desc} |")
        lines.append(f"**Default Mode**: {self.provider.get_default_mode()}")
        return "\n".join(lines)

    async def _switch_mode(self, mode: str) -> str:
        """Switch to a specific mode."""
        old_mode = self.provider.get_default_mode()
        self.provider.set_default_mode(mode)
        return f"✓ Mode switched: {old_mode} → {mode}"

    async def _add_model(self, mode: str, model_id: str | None, describe: str | None) -> str:
        """Add a new model configuration."""
        self.provider.add_mode(mode, model_id, describe)
        return f"✓ Model added: {mode}\n  Model: {model_id}\n  Description: {describe}"

    async def _remove_model(self, mode: str) -> str:
        """Remove a model configuration."""
        if not mode:
            return "Error: 'mode' parameter is required for remove method"
        self.provider.remove_mode(mode)

    async def _update_model(self, mode: str, model_id: str | None) -> str:
        """Update an existing model configuration."""
        if not mode:
            return "Error: 'mode' parameter is required for update method"

        if not model_id:
            return "Error: 'model_id' parameter is required for update method"
        self.provider.update_mode(mode, model_id)
        return f"✓ Model updated: {mode}\n  Model: {model_id}"
