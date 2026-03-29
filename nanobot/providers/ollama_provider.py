"""Ollama provider using the ollama Python library."""

from __future__ import annotations

import uuid
from typing import Any

import json_repair

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from ollama import Message

_STRIP_PREFIXES = ("ollama/", "ollama_chat/")


class OllamaProvider(LLMProvider):
    """Ollama provider using ollama.AsyncClient."""

    def __init__(
        self,
        api_base: str = "http://localhost:11434",
        default_model: str = "llama3.2",
        api_key: str | None = None,
    ):
        import os
        resolved_key = api_key or os.environ.get("OLLAMA_API_KEY")
        super().__init__(api_key=resolved_key, api_base=api_base)
        self.default_model = default_model
        self._api_base = api_base.rstrip("/")

    def _get_client(self) -> Any:
        from ollama import Client
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        return Client(host=self._api_base, headers=headers)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        resolved_model = model or self.default_model
        for prefix in _STRIP_PREFIXES:
            if resolved_model.startswith(prefix):
                resolved_model = resolved_model[len(prefix):]

        try:
            client = self._get_client()

            if isinstance(tool_choice, dict) and tools:
                forced_name = (tool_choice.get("function") or {}).get("name")
                filtered = [t for t in tools if t.get("function", {}).get("name") == forced_name]
                converted_tools = self._convert_tools(filtered) if filtered else []
            else:
                converted_tools = self._convert_tools(tools) if tools else []

            chunks: list[Message] = []
            last_chunk = None
            for chunk in client.chat(
                model=resolved_model,
                think=reasoning_effort,
                messages=self._convert_messages(self._sanitize_empty_content(messages)),
                tools=converted_tools,
                stream=True,
                options={"temperature": temperature, "num_predict": max(1, max_tokens)},
            ):
                if chunk.message:
                    chunks.append(chunk.message)
                last_chunk = chunk
            response = self._parse(chunks)
            response.finish_reason = last_chunk.done_reason
            response.usage = {
                'prompt_tokens': last_chunk.prompt_eval_count,
                'competion_tokens': last_chunk.eval_count,
                'total_tokens': last_chunk.prompt_eval_count + last_chunk.eval_count
            }
            return response
        except Exception as e:
            return LLMResponse(content=f"Error: {e}", finish_reason="error")

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list[Any]:
        """Convert OpenAI-format tools to ollama Tool objects.

        The ollama Property type only supports type/description/enum/items —
        extra JSON Schema fields (minimum, maximum, minLength, etc.) must be dropped.
        """
        from ollama import Tool

        result = []
        for t in tools:
            fn = t.get("function", {})
            params = fn.get("parameters", {})
            properties = {
                name: Tool.Function.Parameters.Property(
                    type=prop.get("type"),
                    description=prop.get("description"),
                    enum=prop.get("enum"),
                    items=prop.get("items"),
                )
                for name, prop in params.get("properties", {}).items()
            }
            result.append(Tool(
                type="function",
                function=Tool.Function(
                    name=fn.get("name", ""),
                    description=fn.get("description", ""),
                    parameters=Tool.Function.Parameters(
                        type="object",
                        properties=properties,
                        required=params.get("required", []),
                    ),
                ),
            ))
        return result

    @staticmethod
    def _convert_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert OpenAI-format messages for the ollama client.

        - tool_calls[].function.arguments must be a dict, not a JSON string.
        - content may be a list (multimodal); flatten to a string and extract
          images into the separate `images` field that ollama expects.
        """
        import json
        result = []
        for msg in messages:
            msg = dict(msg)

            # --- handle multimodal content (list of parts) ---
            content = msg.get("content")
            if isinstance(content, list):
                texts: list[str] = []
                images: list[str] = []
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "text":
                        texts.append(part.get("text", ""))
                    elif part.get("type") == "image_url":
                        url = (part.get("image_url") or {}).get("url", "")
                        # Strip the data-URI prefix so ollama gets raw base64
                        if url.startswith("data:"):
                            url = url.split(",", 1)[-1]
                        images.append(url)
                msg["content"] = " ".join(texts)
                if images:
                    msg["images"] = images

            # --- handle tool_calls arguments ---
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                converted_tcs = []
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    args = fn.get("arguments")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}
                    converted_tcs.append({
                        **tc,
                        "function": {**fn, "arguments": args},
                    })
                msg["tool_calls"] = converted_tcs

            result.append(msg)
        return result

    def _parse(
            self, 
            msgs: list[Message], 
            ) -> LLMResponse:
        content = ''
        tool_calls: list[ToolCallRequest] = []
        for msg in msgs:
            content += msg.content
            for tc in msg.tool_calls or []:
                args = tc.function.arguments
                if isinstance(args, str):
                    args = json_repair.loads(args)
                tool_calls.append(
                    ToolCallRequest(
                        id=uuid.uuid4().hex[:9],
                        name=tc.function.name,
                        arguments=args if isinstance(args, dict) else {},
                    )
                )

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=None,
            usage=None,
        )

    def get_default_model(self) -> str:
        return self.default_model
