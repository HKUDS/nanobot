"""Direct OpenAI-compatible provider — bypasses LiteLLM."""

from __future__ import annotations

import uuid
from typing import Any

import json_repair
from openai import AsyncOpenAI

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class CustomProvider(LLMProvider):

    def __init__(
        self,
        api_key: str = "no-key",
        api_base: str = "http://localhost:8000/v1",
        default_model: str = "default",
        strip_model_prefix: bool = False,
        extra_headers: dict[str, str] | None = None,
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self._strip_model_prefix = strip_model_prefix
        # Keep affinity stable for this provider instance to improve backend cache locality,
        # while still letting users attach provider-specific headers for custom gateways.
        default_headers = {
            "x-session-affinity": uuid.uuid4().hex,
            **(extra_headers or {}),
        }
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=api_base,
            default_headers=default_headers,
        )

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                   model: str | None = None, max_tokens: int = 4096, temperature: float = 0.7,
                   reasoning_effort: str | None = None,
                   tool_choice: str | dict[str, Any] | None = None) -> LLMResponse:
        effective_model = model or self.default_model
        if self._strip_model_prefix and "/" in effective_model:
            effective_model = effective_model.split("/", 1)[-1]
        kwargs: dict[str, Any] = {
            "model": effective_model,
            "messages": self._sanitize_empty_content(messages),
            "max_tokens": max(1, max_tokens),
            "temperature": temperature,
        }
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
        if tools:
            kwargs.update(tools=tools, tool_choice=tool_choice or "auto")
        try:
            raw = await self._client.chat.completions.with_raw_response.create(**kwargs)
            import json
            data = json.loads(raw.text)
            # Some gateways (e.g. AICodewith) return OpenAI Responses API format
            # at the /chat/completions path. Detect and convert.
            if data.get("object") == "response" and data.get("output"):
                return self._parse_responses_api(data)
            return self._parse(raw.parse())
        except Exception as e:
            # JSONDecodeError.doc / APIError.response.text may carry the raw body
            # (e.g. "unsupported model: xxx") which is far more useful than the
            # generic "Expecting value …" message.  Truncate to avoid huge HTML pages.
            body = getattr(e, "doc", None) or getattr(getattr(e, "response", None), "text", None)
            if body and body.strip():
                return LLMResponse(content=f"Error: {body.strip()[:500]}", finish_reason="error")
            return LLMResponse(content=f"Error: {e}", finish_reason="error")

    @staticmethod
    def _parse_responses_api(data: dict[str, Any]) -> LLMResponse:
        """Parse OpenAI Responses API format into LLMResponse."""
        content = None
        tool_calls: list[ToolCallRequest] = []
        for item in data.get("output", []):
            if item.get("type") == "message":
                for block in item.get("content", []):
                    if block.get("type") == "output_text" and block.get("text"):
                        content = (content or "") + block["text"]
            elif item.get("type") == "function_call":
                args = item.get("arguments", "{}")
                if isinstance(args, str):
                    args = json_repair.loads(args)
                tool_calls.append(ToolCallRequest(
                    id=item.get("call_id", item.get("id", "")),
                    name=item.get("name", ""),
                    arguments=args,
                ))

        usage = {}
        if data.get("usage"):
            u = data["usage"]
            usage = {
                "prompt_tokens": u.get("input_tokens", 0),
                "completion_tokens": u.get("output_tokens", 0),
                "total_tokens": u.get("total_tokens", 0),
            }

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason="tool_calls" if tool_calls else "stop",
            usage=usage,
        )

    def _parse(self, response: Any) -> LLMResponse:
        if not response.choices:
            return LLMResponse(
                content="Error: API returned empty choices. This may indicate a temporary service issue or an invalid model response.",
                finish_reason="error"
            )
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

    def get_default_model(self) -> str:
        return self.default_model
