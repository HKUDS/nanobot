"""Model management tools for changing, listing, testing, and adding LLM models."""

import json
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool


class ChangeModelTool(Tool):
    """Tool to change the current LLM model."""

    def __init__(self, agent: Any):
        self.agent = agent

    @property
    def name(self) -> str:
        return "change_model"

    @property
    def description(self) -> str:
        return (
            "Change the current LLM model being used by the agent. "
            "The model will be used for all subsequent conversations. "
            "Use list_models to see available models first."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "The model identifier to switch to (e.g., 'anthropic/claude-sonnet-4-5', 'openai/gpt-4o', 'deepseek/deepseek-chat')",
                },
            },
            "required": ["model"],
        }

    async def execute(self, **kwargs) -> str:
        model = kwargs.get("model", "")
        if not model:
            return "❌ Error: No model specified"

        try:
            old_model = self.agent.model
            self.agent.model = model

            # Also update subagent manager's model
            self.agent.subagents.model = model

            logger.info(f"Model changed from {old_model} to {model}")
            return f"✅ Model changed successfully!\n\nPrevious: `{old_model}`\nCurrent: `{model}`"
        except Exception as e:
            logger.exception("Error changing model")
            return f"❌ Error changing model: {str(e)}"


class ListModelsTool(Tool):
    """Tool to list available LLM models and get current model."""

    def __init__(self, models_file: Path | None = None, agent: Any = None):
        self.models_file = models_file or Path.home() / ".nanobot" / "models.json"
        self.agent = agent
        self._ensure_default_models()

    def _ensure_default_models(self) -> None:
        """Ensure default models exist in the models file."""
        default_models = {
            "anthropic/claude-opus-4-5": {
                "name": "Claude Opus 4.5",
                "provider": "anthropic",
                "description": "Most capable Claude model for complex tasks",
            },
            "anthropic/claude-sonnet-4-5": {
                "name": "Claude Sonnet 4.5",
                "provider": "anthropic",
                "description": "Balanced performance and speed",
            },
            "anthropic/claude-haiku-4-5": {
                "name": "Claude Haiku 4.5",
                "provider": "anthropic",
                "description": "Fast and cost-effective",
            },
            "openai/gpt-4o": {
                "name": "GPT-4o",
                "provider": "openai",
                "description": "OpenAI's most capable multimodal model",
            },
            "openai/gpt-4o-mini": {
                "name": "GPT-4o Mini",
                "provider": "openai",
                "description": "Smaller, faster GPT-4o variant",
            },
            "deepseek/deepseek-chat": {
                "name": "DeepSeek Chat",
                "provider": "deepseek",
                "description": "DeepSeek's chat model",
            },
            "google/gemini-2.5-flash": {
                "name": "Gemini 2.5 Flash",
                "provider": "google",
                "description": "Google's fast multimodal model",
            },
            "google/gemini-2.5-pro": {
                "name": "Gemini 2.5 Pro",
                "provider": "google",
                "description": "Google's most capable model",
            },
            # OpenCode Zen free models (no auth required)
            "opencode/big-pickle": {
                "name": "Big Pickle",
                "provider": "opencode",
                "description": "FREE - GLM-4.6 backend, general purpose",
            },
            "opencode/gpt-5-nano": {
                "name": "GPT 5 Nano",
                "provider": "opencode",
                "description": "FREE - Lightweight GPT-5 variant",
            },
            "opencode/glm-4.7-free": {
                "name": "GLM 4.7 Free",
                "provider": "opencode",
                "description": "FREE - Latest Zhipu AI model",
            },
            "opencode/kimi-k2.5-free": {
                "name": "Kimi K2.5 Free",
                "provider": "opencode",
                "description": "FREE - Moonshot's Kimi K2.5",
            },
        }

        try:
            if not self.models_file.exists():
                self.models_file.parent.mkdir(parents=True, exist_ok=True)
                self._save_models(default_models)
            else:
                # Merge with existing models
                existing = self._load_models()
                for model_id, info in default_models.items():
                    if model_id not in existing:
                        existing[model_id] = info
                self._save_models(existing)
        except Exception as e:
            logger.error(f"Error ensuring default models: {e}")

    def _load_models(self) -> dict[str, dict[str, Any]]:
        """Load models from file."""
        try:
            if self.models_file.exists():
                return json.loads(self.models_file.read_text())
        except Exception as e:
            logger.error(f"Error loading models: {e}")
        return {}

    def _save_models(self, models: dict[str, dict[str, Any]]) -> None:
        """Save models to file."""
        try:
            self.models_file.write_text(json.dumps(models, indent=2))
        except Exception as e:
            logger.error(f"Error saving models: {e}")

    @property
    def name(self) -> str:
        return "list_models"

    @property
    def description(self) -> str:
        return (
            "List all available LLM models that can be used, or get the current model. "
            "Shows model IDs, names, providers, and descriptions. "
            "Use these IDs with the change_model tool."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "provider": {
                    "type": "string",
                    "description": "Optional: Filter by provider (e.g., 'anthropic', 'openai', 'google')",
                },
                "current": {
                    "type": "boolean",
                    "description": "If true, show the currently active model instead of listing all",
                },
                "search": {
                    "type": "string",
                    "description": "Optional: Search pattern to filter models by name, ID, or description (case-insensitive)",
                },
            },
        }

    async def execute(self, **kwargs) -> str:
        provider_filter = kwargs.get("provider", "").lower()
        show_current = kwargs.get("current", False)
        search_pattern = kwargs.get("search", "").lower()

        # If current=True, show the current model
        if show_current:
            if not self.agent:
                return "❌ Cannot get current model: agent not available"
            try:
                current_model = self.agent.model
                provider = self.agent.provider

                # Get provider info
                provider_name = type(provider).__name__
                default_model = (
                    provider.get_default_model()
                    if hasattr(provider, "get_default_model")
                    else "unknown"
                )

                return (
                    f"📌 **Current Model**\n\n"
                    f"**Active Model**: `{current_model}`\n"
                    f"**Provider**: {provider_name}\n"
                    f"**Default Model**: `{default_model}`"
                )
            except Exception as e:
                logger.exception("Error getting current model")
                return f"❌ Error getting current model: {str(e)}"

        try:
            models = self._load_models()

            if not models:
                return "❌ No models found in the database"

            # Filter by provider if specified
            if provider_filter:
                models = {
                    k: v
                    for k, v in models.items()
                    if v.get("provider", "").lower() == provider_filter
                }

            # Filter by search pattern if specified
            if search_pattern:
                models = {
                    k: v
                    for k, v in models.items()
                    if (
                        search_pattern in k.lower()  # Match model ID
                        or search_pattern in v.get("name", "").lower()  # Match name
                        or search_pattern in v.get("description", "").lower()  # Match description
                        or search_pattern in v.get("provider", "").lower()  # Match provider
                    )
                }

            # Format output
            lines = ["📋 Available Models:\n"]

            # Group by provider
            by_provider: dict[str, list[tuple[str, dict[str, Any]]]] = {}
            for model_id, info in models.items():
                prov = info.get("provider", "unknown")
                if prov not in by_provider:
                    by_provider[prov] = []
                by_provider[prov].append((model_id, info))

            # Sort providers alphabetically
            for provider in sorted(by_provider.keys()):
                lines.append(f"\n**{provider.title()}**:")
                for model_id, info in by_provider[provider]:
                    name = info.get("name", model_id)
                    desc = info.get("description", "No description")
                    lines.append(f"  • `{model_id}` - {name}")
                    lines.append(f"    {desc}")

            lines.append("\n💡 Use `change_model` with the model ID to switch models")
            return "\n".join(lines)

        except Exception as e:
            logger.exception("Error listing models")
            return f"❌ Error listing models: {str(e)}"


class TestModelTool(Tool):
    """Tool to test a model with a simple prompt."""

    def __init__(self, agent: Any):
        self.agent = agent

    @property
    def name(self) -> str:
        return "test_model"

    @property
    def description(self) -> str:
        return (
            "Test a model by sending a simple prompt and checking if it responds. "
            "Useful for verifying that a model is working before switching to it. "
            "Tests the model without changing the current active model."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "The model ID to test (e.g., 'anthropic/claude-sonnet-4-5')",
                },
                "prompt": {
                    "type": "string",
                    "description": "Optional: Custom test prompt. Default: 'Say hello and tell me your name.'",
                    "default": "Say hello and tell me your name.",
                },
            },
            "required": ["model"],
        }

    async def execute(self, **kwargs) -> str:
        model = kwargs.get("model", "")
        prompt = kwargs.get("prompt", "Say hello and tell me your name.")

        if not model:
            return "❌ Error: No model specified"

        try:
            import asyncio
            from nanobot.config.loader import load_config
            from nanobot.providers.base import LLMResponse
            from nanobot.providers.litellm_provider import LiteLLMProvider

            logger.info(f"Testing model: {model}")

            # Create a simple test message
            messages = [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ]

            # Create a provider specifically for this model
            # This ensures we use the correct API key/base for the model being tested
            config = load_config()
            api_key = config.get_api_key(model)
            api_base = config.get_api_base(model)
            provider_name = config.get_provider_name(model)

            if not api_key:
                return f"❌ No API key configured for model `{model}`"

            # Create a new provider instance for testing this specific model
            test_provider = LiteLLMProvider(
                api_key=api_key,
                api_base=api_base,
                default_model=model,
                provider_name=provider_name,
            )

            # Call the provider with the test model
            response = await test_provider.chat(
                messages=messages,
                model=model,
                max_tokens=1000,
            )

            if response.finish_reason == "error":
                return f"❌ Model test failed for `{model}`\n\nError: {response.content}"

            content = response.content or "(No response)"
            usage_info = ""
            if response.usage:
                usage_info = f"\nTokens: {response.usage.get('total_tokens', 'N/A')} total"

            # Include thinking/reasoning if available
            thinking_info = ""
            if response.thinking:
                thinking_info = f"\n\n**Thinking**:\n```\n{response.thinking[:1000]}{'...' if len(response.thinking) > 1000 else ''}\n```"
            elif response.reasoning_content:
                thinking_info = f"\n\n**Reasoning**:\n```\n{response.reasoning_content[:1000]}{'...' if len(response.reasoning_content) > 1000 else ''}\n```"

            return (
                f"✅ Model test successful!\n\n"
                f"**Model**: `{model}`\n"
                f"**Provider**: {provider_name or 'default'}\n"
                f"**Response**: {content[:500]}{'...' if len(content) > 500 else ''}"
                f"{usage_info}"
                f"{thinking_info}"
            )

        except Exception as e:
            logger.exception("Error testing model")
            return f"❌ Error testing model `{model}`: {str(e)}"


class AddModelTool(Tool):
    """Tool to add a new model to the available models list."""

    def __init__(self, models_file: Path | None = None):
        self.models_file = models_file or Path.home() / ".nanobot" / "models.json"

    def _load_models(self) -> dict[str, dict[str, Any]]:
        """Load models from file."""
        try:
            if self.models_file.exists():
                return json.loads(self.models_file.read_text())
        except Exception as e:
            logger.error(f"Error loading models: {e}")
        return {}

    def _save_models(self, models: dict[str, dict[str, Any]]) -> None:
        """Save models to file."""
        try:
            self.models_file.parent.mkdir(parents=True, exist_ok=True)
            self.models_file.write_text(json.dumps(models, indent=2))
        except Exception as e:
            logger.error(f"Error saving models: {e}")

    @property
    def name(self) -> str:
        return "add_model"

    @property
    def description(self) -> str:
        return (
            "Add a new model to the available models list. "
            "Useful for adding custom models, vLLM endpoints, or new providers. "
            "After adding, you can test it with test_model and use it with change_model."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "model_id": {
                    "type": "string",
                    "description": "The model identifier (e.g., 'anthropic/claude-opus-4-5', 'hosted_vllm/my-model')",
                },
                "name": {
                    "type": "string",
                    "description": "Human-readable name for the model",
                },
                "provider": {
                    "type": "string",
                    "description": "Provider name (e.g., 'anthropic', 'openai', 'vllm', 'custom')",
                },
                "description": {
                    "type": "string",
                    "description": "Brief description of the model",
                },
            },
            "required": ["model_id", "name", "provider"],
        }

    async def execute(self, **kwargs) -> str:
        model_id = kwargs.get("model_id", "")
        name = kwargs.get("name", "")
        provider = kwargs.get("provider", "")
        description = kwargs.get("description", "")

        if not all([model_id, name, provider]):
            return "❌ Error: model_id, name, and provider are required"

        try:
            models = self._load_models()

            # Check if model already exists
            if model_id in models:
                return f"⚠️ Model `{model_id}` already exists. Use list_models to see it."

            # Add the new model
            models[model_id] = {
                "name": name,
                "provider": provider,
                "description": description or f"Custom {provider} model",
            }

            self._save_models(models)

            logger.info(f"Added new model: {model_id}")
            return (
                f"✅ Model added successfully!\n\n"
                f"**ID**: `{model_id}`\n"
                f"**Name**: {name}\n"
                f"**Provider**: {provider}\n"
                f"**Description**: {description or 'Custom model'}\n\n"
                f"💡 You can now:\n"
                f"  1. Test it: `/test_model {model_id}`\n"
                f"  2. Use it: `/change_model {model_id}`"
            )

        except Exception as e:
            logger.exception("Error adding model")
            return f"❌ Error adding model: {str(e)}"
