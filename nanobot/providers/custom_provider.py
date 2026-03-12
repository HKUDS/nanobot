"""Direct OpenAI-compatible provider — bypasses LiteLLM."""

from __future__ import annotations

import json
import uuid
from typing import Any

import json_repair
from openai import AsyncOpenAI

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class CustomProvider(LLMProvider):

    def __init__(self, api_key: str = "no-key", api_base: str = "http://localhost:8000/v1", default_model: str = "default"):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        # Keep affinity stable for this provider instance to improve backend cache locality.
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=api_base,
            default_headers={"x-session-affinity": uuid.uuid4().hex},
        )

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                   model: str | None = None, max_tokens: int = 4096, temperature: float = 0.7,
                   reasoning_effort: str | None = None,
                   tool_choice: str | dict[str, Any] | None = None) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": self._sanitize_empty_content(messages),
            "max_tokens": max(1, max_tokens),
            "temperature": temperature,
        }
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
        if tools:
            kwargs.update(tools=tools, tool_choice=tool_choice or "auto")
        try:
            return self._parse(await self._client.chat.completions.create(**kwargs))
        except Exception as e:
            try:
                return self._parse_responses(
                    await self._client.responses.create(
                        **self._build_responses_kwargs(
                            messages=messages,
                            tools=tools,
                            model=model,
                            max_tokens=max_tokens,
                            temperature=temperature,
                            reasoning_effort=reasoning_effort,
                            tool_choice=tool_choice,
                        )
                    )
                )
            except Exception as responses_error:
                return LLMResponse(
                    content=f"Error: chat.completions failed: {e}; responses failed: {responses_error}",
                    finish_reason="error",
                )

    def _parse(self, response: Any) -> LLMResponse:
        choice = response.choices[0]
        msg = choice.message
        tool_calls = [
            ToolCallRequest(id=tc.id, name=tc.function.name,
                            arguments=json_repair.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments)
            for tc in (msg.tool_calls or [])
        ]
        u = response.usage
        return LLMResponse(
            content=msg.content, tool_calls=tool_calls, finish_reason=choice.finish_reason or "stop",
            usage={"prompt_tokens": u.prompt_tokens, "completion_tokens": u.completion_tokens, "total_tokens": u.total_tokens} if u else {},
            reasoning_content=getattr(msg, "reasoning_content", None) or None,
        )

    def _build_responses_kwargs(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        max_tokens: int,
        temperature: float,
        reasoning_effort: str | None,
        tool_choice: str | dict[str, Any] | None,
    ) -> dict[str, Any]:
        system_prompt, input_items = self._convert_messages(self._sanitize_empty_content(messages))
        kwargs: dict[str, Any] = {
            "model": model or self.default_model,
            "input": input_items,
            "max_output_tokens": max(1, max_tokens),
            "temperature": temperature,
            "store": False,
            "parallel_tool_calls": True,
        }
        if system_prompt:
            kwargs["instructions"] = system_prompt
        if reasoning_effort:
            kwargs["reasoning"] = {"effort": reasoning_effort}
        if tools:
            kwargs["tools"] = self._convert_tools(tools)
            kwargs["tool_choice"] = tool_choice or "auto"
        return kwargs

    def _parse_responses(self, response: Any) -> LLMResponse:
        content_parts: list[str] = []
        tool_calls: list[ToolCallRequest] = []

        for item in getattr(response, "output", None) or []:
            item_type = getattr(item, "type", None)
            if item_type == "message":
                for content_item in getattr(item, "content", None) or []:
                    if getattr(content_item, "type", None) in {"output_text", "text"} and getattr(content_item, "text", None):
                        content_parts.append(content_item.text)
            elif item_type == "function_call":
                raw_arguments = getattr(item, "arguments", None) or "{}"
                tool_calls.append(
                    ToolCallRequest(
                        id=f"{getattr(item, 'call_id', None) or 'call_0'}|{getattr(item, 'id', None) or 'fc_0'}",
                        name=getattr(item, "name", None) or "",
                        arguments=json_repair.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments,
                    )
                )

        usage = getattr(response, "usage", None)
        return LLMResponse(
            content="".join(content_parts) or getattr(response, "output_text", None) or None,
            tool_calls=tool_calls,
            finish_reason=self._map_responses_finish_reason(getattr(response, "status", None)),
            usage={
                "prompt_tokens": usage.input_tokens,
                "completion_tokens": usage.output_tokens,
                "total_tokens": usage.total_tokens,
            } if usage else {},
        )

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for tool in tools:
            fn = (tool.get("function") or {}) if tool.get("type") == "function" else tool
            name = fn.get("name")
            if not name:
                continue
            params = fn.get("parameters") or {}
            converted.append({
                "type": "function",
                "name": name,
                "description": fn.get("description") or "",
                "parameters": params if isinstance(params, dict) else {},
            })
        return converted

    def _convert_messages(self, messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        system_prompt = ""
        input_items: list[dict[str, Any]] = []

        for idx, msg in enumerate(messages):
            role = msg.get("role")
            content = msg.get("content")

            if role == "system":
                system_prompt = content if isinstance(content, str) else ""
                continue

            if role == "user":
                input_items.append(self._convert_user_message(content))
                continue

            if role == "assistant":
                if isinstance(content, str) and content:
                    input_items.append(
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": content}],
                            "status": "completed",
                            "id": f"msg_{idx}",
                        }
                    )
                for tool_call in msg.get("tool_calls", []) or []:
                    fn = tool_call.get("function") or {}
                    call_id, item_id = self._split_tool_call_id(tool_call.get("id"))
                    call_id = call_id or f"call_{idx}"
                    item_id = item_id or f"fc_{idx}"
                    input_items.append(
                        {
                            "type": "function_call",
                            "id": item_id,
                            "call_id": call_id,
                            "name": fn.get("name"),
                            "arguments": fn.get("arguments") or "{}",
                        }
                    )
                continue

            if role == "tool":
                call_id, _ = self._split_tool_call_id(msg.get("tool_call_id"))
                output_text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": output_text,
                    }
                )

        return system_prompt, input_items

    def _convert_user_message(self, content: Any) -> dict[str, Any]:
        if isinstance(content, str):
            return {"role": "user", "content": [{"type": "input_text", "text": content}]}
        if isinstance(content, list):
            converted: list[dict[str, Any]] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text":
                    converted.append({"type": "input_text", "text": item.get("text", "")})
                elif item.get("type") == "image_url":
                    url = (item.get("image_url") or {}).get("url")
                    if url:
                        converted.append({"type": "input_image", "image_url": url, "detail": "auto"})
            if converted:
                return {"role": "user", "content": converted}
        return {"role": "user", "content": [{"type": "input_text", "text": ""}]}

    def _split_tool_call_id(self, tool_call_id: Any) -> tuple[str, str | None]:
        if isinstance(tool_call_id, str) and tool_call_id:
            if "|" in tool_call_id:
                call_id, item_id = tool_call_id.split("|", 1)
                return call_id, item_id or None
            return tool_call_id, None
        return "call_0", None

    def _map_responses_finish_reason(self, status: str | None) -> str:
        return {
            "completed": "stop",
            "incomplete": "length",
            "failed": "error",
            "cancelled": "error",
        }.get(status or "completed", "stop")

    def get_default_model(self) -> str:
        return self.default_model

