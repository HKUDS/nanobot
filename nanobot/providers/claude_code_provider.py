"""LLM provider using Claude Code CLI's OAuth authentication.

Calls the Anthropic API directly with the correct OAuth headers,
so nanobot can use a Claude Max/Pro subscription without a separate API key.
"""

import json
from typing import Any

import httpx
from loguru import logger

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

CLAUDE_CODE_HEADERS = {
    "anthropic-version": "2023-06-01",
    "anthropic-beta": "claude-code-20250219,oauth-2025-04-20,interleaved-thinking-2025-05-14",
}

CLAUDE_CODE_SYSTEM_PREFIX = "You are Claude Code, Anthropic's official CLI for Claude."


# Tool names that the OAuth API rejects — map to Claude Code-compatible names.
_TOOL_NAME_TO_API: dict[str, str] = {
    "read_file": "ReadFile",
}
_TOOL_NAME_FROM_API: dict[str, str] = {v: k for k, v in _TOOL_NAME_TO_API.items()}


class ClaudeCodeProvider(LLMProvider):
    """LLM provider that uses Claude Code CLI's OAuth token.

    Sends requests directly to api.anthropic.com with the required
    Claude Code headers and system prompt prefix.
    """

    def __init__(self, oauth_token: str, default_model: str = "claude-sonnet-4-5-20250929"):
        super().__init__(api_key=oauth_token)
        self.oauth_token = oauth_token
        self.default_model = default_model
        # Strip provider prefix for direct API calls (e.g. "anthropic/claude-..." -> "claude-...")
        if "/" in self.default_model:
            self.default_model = self.default_model.split("/", 1)[1]

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        model = model or self.default_model
        # Strip provider prefix if present
        if "/" in model:
            model = model.split("/", 1)[1]

        body = self._build_body(messages, tools, model, max_tokens, temperature)

        try:
            async with httpx.AsyncClient(timeout=300) as client:
                resp = await client.post(
                    ANTHROPIC_API_URL,
                    headers={
                        **CLAUDE_CODE_HEADERS,
                        "Authorization": f"Bearer {self.oauth_token}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )

            if resp.status_code != 200:
                error_text = resp.text
                logger.error(f"Anthropic API error {resp.status_code}: {error_text[:200]}")
                return LLMResponse(
                    content=f"Error from Anthropic API ({resp.status_code}): {error_text[:500]}",
                    finish_reason="error",
                )

            return self._parse_response(resp.json())

        except Exception as e:
            return LLMResponse(content=f"Error calling Anthropic API: {e}", finish_reason="error")

    def get_default_model(self) -> str:
        return self.default_model

    def _build_body(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        """Build Anthropic Messages API request body from OpenAI-style inputs."""
        # Extract system messages and convert to Anthropic format
        system_parts: list[str] = [CLAUDE_CODE_SYSTEM_PREFIX]
        anthropic_messages: list[dict[str, Any]] = []

        for msg in messages:
            if msg["role"] == "system":
                content = msg["content"]
                if isinstance(content, str):
                    system_parts.append(content)
                continue

            if msg["role"] == "tool":
                # Convert OpenAI tool result to Anthropic tool_result content block
                anthropic_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "content": msg.get("content", ""),
                    }],
                })
                continue

            if msg["role"] == "assistant":
                converted = self._convert_assistant_msg(msg)
                anthropic_messages.append(converted)
                continue

            # User messages — pass through (string content works directly)
            anthropic_messages.append({"role": "user", "content": msg["content"]})

        # Build system as array of content blocks — OAuth tokens require the
        # Claude Code prefix to be a separate first block (not concatenated).
        system_blocks = [{"type": "text", "text": part} for part in system_parts]

        body: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_blocks,
            "messages": anthropic_messages,
        }

        if tools:
            body["tools"] = self._convert_tools(tools)

        return body

    def _convert_assistant_msg(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Convert an OpenAI assistant message to Anthropic format."""
        content_blocks: list[dict[str, Any]] = []

        # Text content
        if msg.get("content"):
            content_blocks.append({"type": "text", "text": msg["content"]})

        # Tool calls -> tool_use blocks
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                args = tc["function"]["arguments"]
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw": args}
                name = tc["function"]["name"]
                content_blocks.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": _TOOL_NAME_TO_API.get(name, name),
                    "input": args,
                })

        return {"role": "assistant", "content": content_blocks or msg.get("content", "")}

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert OpenAI tool definitions to Anthropic format.

        Renames tools that the OAuth API rejects to Claude Code-compatible names.
        """
        result = []
        for tool in tools:
            func = tool.get("function", tool)
            name = func["name"]
            result.append({
                "name": _TOOL_NAME_TO_API.get(name, name),
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {}),
            })
        return result

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        """Parse Anthropic Messages API response into LLMResponse."""
        content_text: list[str] = []
        tool_calls: list[ToolCallRequest] = []

        for block in data.get("content", []):
            if block["type"] == "text":
                content_text.append(block["text"])
            elif block["type"] == "tool_use":
                # Map API tool names back to nanobot names
                api_name = block["name"]
                tool_calls.append(ToolCallRequest(
                    id=block["id"],
                    name=_TOOL_NAME_FROM_API.get(api_name, api_name),
                    arguments=block.get("input", {}),
                ))

        # Map stop reason
        stop_reason = data.get("stop_reason", "end_turn")
        finish_map = {"end_turn": "stop", "tool_use": "tool_calls", "max_tokens": "length"}
        finish_reason = finish_map.get(stop_reason, "stop")

        usage = {}
        if "usage" in data:
            usage = {
                "prompt_tokens": data["usage"].get("input_tokens", 0),
                "completion_tokens": data["usage"].get("output_tokens", 0),
                "total_tokens": data["usage"].get("input_tokens", 0) + data["usage"].get("output_tokens", 0),
            }

        return LLMResponse(
            content="\n".join(content_text) if content_text else None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
        )
