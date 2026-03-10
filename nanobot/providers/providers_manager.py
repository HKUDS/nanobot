"""Providers manager for handling multiple LLM providers and modes."""

from typing import Any
from loguru import logger

from nanobot.config.schema import Config
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.providers.litellm_provider import LiteLLMProvider


class ProvidersManager:
    """
    Manager for multiple LLM providers with mode-based selection.

    This class handles provider initialization and routing based on modes
    (main, coding, multimodal) to optimize for different use cases.
    """

    def __init__(self, config: Config, modes: dict, default_mode: str = "auto"):
        """
        Initialize the providers manager.

        Args:
            modes: AgentModes instance with mode configurations (main, coding, multimodal)
            default_mode: Default mode to use when none is specified ("auto" by default)
        """
        self._modes = modes
        self._default_mode = default_mode
        self._config = config

    def _create_provider(self, model_id: str, provider_name: str = "auto") -> LLMProvider:
        """
        Create a provider for the given model.

        Args:
            model_id: Model identifier (e.g., "anthropic/claude-opus-4-5")

        Returns:
            Initialized LLMProvider instance
        """
        p = self._config.get_provider(model_id)
        return LiteLLMProvider(
            api_key=p.api_key if p else None,
            api_base=self._config.get_api_base(model_id),
            default_model=model_id,
            extra_headers=p.extra_headers if p else None,
            provider_name=provider_name,
        )

    async def chat_with_retry(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        mode: str = "",
    ) -> LLMResponse:
        """
        Send a chat completion request using the provider for the specified mode.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions in OpenAI format.
            model: Model identifier (overrides mode's model if provided).
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.
            mode: Mode to use for this chat ("main", "coding", "multimodal", or "auto")

        Returns:
            LLMResponse with content and/or tool calls.

        Raises:
            ValueError: If mode is not recognized or no modes are configured.
        """

        mode = mode or self._default_mode
        user_content = messages[-1]["content"]
        if mode == "auto":
            assert "main" in self._modes, "No main mode configured for auto mode"
            # For auto mode, use decider to choose the best mode
            decider = self.get_provider("main")
            system_prompt = f"You are mode decider. You can choose the best mode for process the user's task. The modes are:\n{self.summary_modes()}"
            # Create messages for decider
            decider_messages = [{"role": "system", "content": system_prompt}]
            decider_messages.append(
                {
                    "role": "user",
                    "content": f"Which mode is best to process the task `{user_content}`? The answer should only has one word!",
                }
            )
            # Get decider's response - it should return only a mode name
            decider_response = await decider.chat_with_retry(
                messages=decider_messages,
                tools=None,
                model=decider.get_default_model(),
                max_tokens=50,
                temperature=0.1,
            )
            # Extract mode from decider response (should be just one word)
            selected_mode = decider_response.content.strip() if decider_response.content else "main"
            # Use the selected mode's provider
            if selected_mode in self._modes:
                logger.info(f"Choose {selected_mode} for task: {user_content[:20]}")
                provider = self.get_provider(selected_mode)
            else:
                # Fallback to main if selected mode not found
                logger.info(f"Fallback to main for task: {user_content[:20]}")
                provider = self.get_provider("main")
        elif mode in self._modes:
            logger.info(f"Use specified {mode} for task: {user_content[:20]}")
            provider = self.get_provider(mode)
        elif "main" in self._modes:
            logger.info(f"Fallback to main for task: {user_content[:20]}")
            provider = self.get_provider("main")
        else:
            raise ValueError(f"Unknown mode: {mode} and no fallback available")

        # Make the chat request
        return await provider.chat_with_retry(
            messages=messages,
            tools=tools,
            model=model or provider.get_default_model(),
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
        )

    def add_mode(self, mode: str, model_id: str, describe: str) -> None:
        """
        Add a new mode with the given configuration.

        Args:
            mode: Mode name (e.g., "main", "coding", "multimodal")
            model_id: Model identifier for this mode
            describe: Description of this mode's purpose
        """
        # Add to mode data
        self._modes[mode] = {"provider": self._create_provider(model_id), "describe": describe}

    def update_mode(self, mode: str, model_id: str) -> None:
        """
        Update an existing mode's configuration.

        Args:
            mode: Mode name to update
            model_id: New model identifier for this mode
        """
        if mode not in self._modes:
            raise ValueError(f"Mode '{mode}' does not exist. Use add_mode to create it first.")

        # Check if we need to create a new provider
        current_model = self.get_model(mode)
        if model_id != current_model:
            # Create new provider for the new model
            self._modes[mode].update({"provider": self._create_provider(model_id)})

    def remove_mode(self, mode: str) -> None:
        """
        Remove a mode from the modes configuration.

        Args:
            mode: Mode name to remove
        """
        if mode in self._modes:
            self._modes.pop(mode)

    def summary_modes(self) -> str:
        """
        Generate a summary string describing all available modes.

        Returns:
            A string describing each mode's model_id and describe, suitable for
            passing to provider.chat for mode selection decisions.
        """
        if not self._modes:
            return "No modes configured."

        summary_parts = []
        for mode_name, m_info in self._modes.items():
            summary_parts.append(
                f"Mode '{mode_name}'({self.get_model(mode_name)}) : {m_info['describe']}"
            )
        return "\n".join(summary_parts)

    def get_provider(self, mode: str):
        """
        Returns the provider for the given mode.
        Args:
            mode: Mode name (e.g., "main", "coding", "multimodal")
        """

        assert mode in self._modes, "Mode not found"
        assert "provider" in self._modes[mode], "Provider not found in mode configuration"
        return self._modes[mode]["provider"]

    def get_model(self, mode: str):
        """
        Returns the model for the given mode.
        Args:
            mode: Mode name (e.g., "main", "coding", "multimodal")
        """

        return self.get_provider(mode).get_default_model()

    def get_default_model(self) -> str:
        """Get the default model."""
        return self.get_model("main")

    def get_default_mode(self):
        """Get the default mode."""
        return self._default_mode

    def set_default_mode(self, mode):
        """Set the default mode."""
        self._default_mode = mode

    def list_models(self) -> list[str]:
        """List all available models."""

        return [
            {"name": k, "model": self.get_model(k), "describe": v["describe"]}
            for k, v in self._modes.items()
        ]
