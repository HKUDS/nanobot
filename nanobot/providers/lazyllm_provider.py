"""LazyLLM provider implementation using OnlineModule."""

import asyncio
import copy
import json
import os
import uuid
from typing import Any

from lazyllm import OnlineModule
from lazyllm.components import FunctionCallFormatter


from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class LazyLLMProvider(LLMProvider):
    """
    LLM provider using LazyLLM OnlineModule.

    Supports chat models with `type="LLM"` and vision-language models with `type="VLM"`.
    """

    SUPPORTED_TYPES = {"LLM", "VLM"}

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "qwen-plus",
        source: str | None = None,
        type: str = "LLM",
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.source = source
        self.model_type = self._normalize_type(type)
        self.client = self._create_client(
            model=self.default_model,
            source=self.source,
            model_type=self.model_type,
        )

    def _normalize_type(self, model_type: str) -> str:
        normalized = model_type.upper()
        if normalized not in self.SUPPORTED_TYPES:
            raise ValueError(
                f"Unsupported LazyLLM model type: {model_type}. "
                f"Supported values: {sorted(self.SUPPORTED_TYPES)}"
            )
        return normalized

    def _create_client(self, model: str, source: str | None, model_type: str) -> Any:
        if OnlineModule is None:
            raise ImportError(
                "lazyllm is not installed. Install it first to use LazyLLMProvider."
            )
        kwargs: dict[str, Any] = {
            "model": model,
            "type": model_type,
        }
        if source:
            kwargs["source"] = source
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["url"] = self.api_base
        return OnlineModule(**kwargs)

    def _get_client_for_model(self, model: str) -> tuple[Any, str]:
        if model == self.default_model:
            return self.client, model
        return (
            self._create_client(model=model, source=self.source, model_type=self.model_type),
            model,
        )

    def _messages_to_lazyllm_payload(
        self, messages: list[dict[str, Any]]
    ) -> tuple[str, list[dict[str, Any]], str | dict[str, Any]]:
        system_parts: list[str] = []
        conversation: list[dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role")
            if role == "system":
                content = msg.get("content", "")
                if isinstance(content, str):
                    system_parts.append(content)
                else:
                    system_parts.append(json.dumps(content, ensure_ascii=False))
            else:
                conversation.append(copy.deepcopy(msg))

        system_prompt = "\n\n".join(part for part in system_parts if part).strip()

        if not conversation:
            return system_prompt, [], ""
        current_message = conversation[-1]
        current_role = str(current_message.get("role", "user"))
        current_content = current_message.get("content", "")
        if isinstance(current_content, list):
            # For multimodal OpenAI-style content, keep structured payload.
            return system_prompt, conversation[:-1], {
                "messages": [{"role": current_role, "content": current_content}]
            }
        if isinstance(current_content, dict):
            current_content = json.dumps(current_content, ensure_ascii=False)
        elif current_content is None:
            current_content = ""
        else:
            current_content = str(current_content)

        return system_prompt, conversation[:-1], current_content

    def _parse_response(self, response: Any) -> LLMResponse:
        if not isinstance(response, dict):
            return LLMResponse(content=str(response), finish_reason="stop")

        content = response.get("content")
        if isinstance(content, list):
            content = json.dumps(content, ensure_ascii=False)
        elif content is not None and not isinstance(content, str):
            content = str(content)

        tool_calls: list[ToolCallRequest] = []
        for idx, tc in enumerate(response.get("tool_calls") or []):
            if not isinstance(tc, dict):
                continue

            function = tc.get("function", {})
            if not isinstance(function, dict):
                function = {}
            name = function.get("name") or tc.get("name")
            if not name:
                continue

            arguments = function.get("arguments", tc.get("arguments", {}))
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {"raw": arguments}
            if arguments is None:
                arguments = {}
            if not isinstance(arguments, dict):
                arguments = {"value": arguments}

            tool_calls.append(
                ToolCallRequest(
                    id=tc.get("id") or f"call_{uuid.uuid4().hex[:8]}_{idx}",
                    name=name,
                    arguments=arguments,
                )
            )

        finish_reason = response.get("finish_reason")
        if not finish_reason:
            finish_reason = "tool_calls" if tool_calls else "stop"

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage={},
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """
        Send a chat completion request via LazyLLM OnlineModule.

        Args:
            messages: List of message dicts with OpenAI-compatible roles/content.
            tools: Optional list of tool definitions in OpenAI format.
            model: Optional model override.
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.

        Returns:
            LLMResponse with content and/or tool calls.
        """
        target_model = model or self.default_model
        client, runtime_model = self._get_client_for_model(target_model)
        system_prompt, history, current_input = self._messages_to_lazyllm_payload(messages)

        # Reset/update prompt for this turn so system context stays aligned with the current message set.
        client = client.share(prompt=system_prompt, format=FunctionCallFormatter())

        kwargs: dict[str, Any] = {
            "llm_chat_history": history,
            "model": runtime_model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream_output": False,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            response = await asyncio.to_thread(client, current_input, **kwargs)
            parsed = self._parse_response(response)
            return parsed
        except Exception as e:
            return LLMResponse(
                content=f"Error calling LLM: {str(e)}",
                finish_reason="error",
            )

    def get_default_model(self) -> str:
        """Get the default model."""
        return self.default_model
