"""LLM provider that calls Anthropic API directly using Claude Code OAuth token."""

import json
from typing import Any

import httpx
import json_repair
from loguru import logger

from nanobot.api.claude_direct import (
    ANTHROPIC_API_URL,
    CLAUDE_CODE_HEADERS,
    CLAUDE_CODE_SYSTEM_PREFIX,
)
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

# Tool name remapping — OAuth API rejects some nanobot tool names
_TOOL_NAME_TO_API: dict[str, str] = {
    "read_file": "ReadFile",
}
_TOOL_NAME_FROM_API: dict[str, str] = {v: k for k, v in _TOOL_NAME_TO_API.items()}

# Map Anthropic stop_reason -> OpenAI-style finish_reason
_FINISH_MAP = {"end_turn": "stop", "tool_use": "tool_calls", "max_tokens": "length"}


class ClaudeCodeProvider(LLMProvider):
    """Provider that uses Claude Code CLI OAuth token to call Anthropic API directly."""

    def __init__(self, oauth_token: str, default_model: str = "claude-sonnet-4-5-20250929"):
        super().__init__(api_key=oauth_token)
        self.oauth_token = oauth_token
        self.default_model = default_model
        # Strip provider prefix if present (e.g. "anthropic/claude-sonnet-4-5" -> "claude-sonnet-4-5")
        if "/" in self.default_model:
            self.default_model = self.default_model.split("/", 1)[1]

    def _build_body(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        """Convert OpenAI-style messages/tools to Anthropic Messages API format."""
        system_parts: list[str] = [CLAUDE_CODE_SYSTEM_PREFIX]
        anthropic_messages: list[dict[str, Any]] = []

        for msg in messages:
            role = msg["role"]
            content = msg.get("content")

            if role == "system":
                if isinstance(content, str) and content:
                    system_parts.append(content)
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            system_parts.append(block["text"])
                continue

            if role == "assistant":
                blocks: list[dict[str, Any]] = []
                if content:
                    blocks.append({"type": "text", "text": content})
                # Convert tool_calls to Anthropic tool_use blocks
                for tc in msg.get("tool_calls") or []:
                    fn = tc.get("function", {})
                    args = fn.get("arguments", "{}")
                    if isinstance(args, str):
                        args = json_repair.loads(args)
                    name = fn.get("name", "")
                    blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": _TOOL_NAME_TO_API.get(name, name),
                        "input": args,
                    })
                if blocks:
                    anthropic_messages.append({"role": "assistant", "content": blocks})
                continue

            if role == "tool":
                # Tool result message
                anthropic_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "content": content or "",
                    }],
                })
                continue

            # user message
            if isinstance(content, str):
                anthropic_messages.append({"role": "user", "content": content})
            elif isinstance(content, list):
                # Convert image_url blocks to Anthropic format
                blocks = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "image_url":
                        url = item["image_url"]["url"]
                        if url.startswith("data:"):
                            # data:image/png;base64,ABC... -> media_type + data
                            header, data = url.split(",", 1)
                            media_type = header.split(":")[1].split(";")[0]
                            blocks.append({
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": data,
                                },
                            })
                        else:
                            blocks.append({"type": "text", "text": f"[image: {url}]"})
                    elif isinstance(item, dict) and item.get("type") == "text":
                        blocks.append({"type": "text", "text": item["text"]})
                    else:
                        blocks.append(item)
                anthropic_messages.append({"role": "user", "content": blocks})
            elif content is not None:
                anthropic_messages.append({"role": "user", "content": str(content)})

        # Build system as array of content blocks
        system_blocks = [{"type": "text", "text": part} for part in system_parts]

        body: dict[str, Any] = {
            "model": model,
            "max_tokens": max(1, max_tokens),
            "temperature": temperature,
            "system": system_blocks,
            "messages": anthropic_messages,
        }

        # Convert OpenAI tool definitions to Anthropic format
        if tools:
            anthropic_tools = []
            for tool_def in tools:
                fn = tool_def.get("function", tool_def)
                name = fn.get("name", "")
                anthropic_tools.append({
                    "name": _TOOL_NAME_TO_API.get(name, name),
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                })
            body["tools"] = anthropic_tools

        return body

    async def _send_request(self, body: dict[str, Any]) -> httpx.Response:
        """Send request to Anthropic API."""
        async with httpx.AsyncClient(timeout=300) as client:
            return await client.post(
                ANTHROPIC_API_URL,
                headers={
                    **CLAUDE_CODE_HEADERS,
                    "Authorization": f"Bearer {self.oauth_token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Send a chat completion request to Anthropic API using OAuth token."""
        resolved_model = model or self.default_model
        if "/" in resolved_model:
            resolved_model = resolved_model.split("/", 1)[1]

        messages = self._sanitize_empty_content(messages)
        body = self._build_body(messages, tools, resolved_model, max_tokens, temperature)

        try:
            resp = await self._send_request(body)

            if resp.status_code == 401:
                logger.error("Claude Code OAuth token rejected (401). Run: claude setup-token")
                return LLMResponse(
                    content="OAuth token expired or invalid. Run `claude setup-token` to get a new one.",
                    finish_reason="error",
                )

            if resp.status_code != 200:
                error_text = resp.text
                logger.error("Anthropic API error {}: {}", resp.status_code, error_text[:500])
                return LLMResponse(
                    content=f"Error calling Anthropic API: {resp.status_code} - {error_text[:300]}",
                    finish_reason="error",
                )

            return self._parse_response(resp.json())
        except Exception as e:
            logger.error("Claude Code provider error: {}", e)
            return LLMResponse(
                content=f"Error calling LLM: {e}",
                finish_reason="error",
            )

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        """Parse Anthropic API response into LLMResponse."""
        content_text: list[str] = []
        tool_calls: list[ToolCallRequest] = []

        for block in data.get("content", []):
            if block.get("type") == "text":
                content_text.append(block["text"])
            elif block.get("type") == "tool_use":
                name = block.get("name", "")
                tool_calls.append(ToolCallRequest(
                    id=block.get("id", ""),
                    name=_TOOL_NAME_FROM_API.get(name, name),
                    arguments=block.get("input", {}),
                ))

        stop_reason = data.get("stop_reason", "end_turn")
        finish_reason = _FINISH_MAP.get(stop_reason, "stop")

        usage_data = data.get("usage", {})
        usage = {
            "prompt_tokens": usage_data.get("input_tokens", 0),
            "completion_tokens": usage_data.get("output_tokens", 0),
            "total_tokens": usage_data.get("input_tokens", 0) + usage_data.get("output_tokens", 0),
        }

        return LLMResponse(
            content="\n".join(content_text) if content_text else None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
        )

    def get_default_model(self) -> str:
        """Get the default model."""
        return self.default_model
