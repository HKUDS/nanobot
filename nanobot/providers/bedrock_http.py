"""AWS Bedrock provider via Converse API (HTTP + Bearer token only, no boto3)."""

import json
from typing import Any

import httpx

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


# Default region endpoint if api_base not set
DEFAULT_BEDROCK_BASE = "https://bedrock-runtime.us-east-1.amazonaws.com"


def _messages_to_bedrock(messages: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """Convert OpenAI-style messages to Bedrock format. Returns (system_blocks, messages)."""
    system_blocks: list[dict] = []
    bedrock_messages: list[dict] = []
    i = 0

    while i < len(messages):
        m = messages[i]
        role = m.get("role", "user")
        content = m.get("content", "")

        if role == "system":
            text = content if isinstance(content, str) else ""
            if text:
                system_blocks.append({"text": text})
            i += 1
            continue

        if role == "assistant":
            blocks: list[dict] = []
            if content:
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and ("text" in block or block.get("type") == "text"):
                            text = block.get("text", "")
                            if text:
                                blocks.append({"text": text})
                else:
                    text = str(content)
                    if text:
                        blocks.append({"text": text})
            for tc in m.get("tool_calls") or []:
                tid = tc.get("id") or tc.get("toolUseId", "")
                name = tc.get("function", {}).get("name") or tc.get("name", "")
                args = tc.get("function", {}).get("arguments") or tc.get("input") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                if tid and name:
                    blocks.append({"toolUse": {"toolUseId": tid, "name": name, "input": args}})
            if blocks:
                bedrock_messages.append({"role": "assistant", "content": blocks})
            i += 1
            continue

        if role == "tool":
            tool_result_blocks: list[dict] = []
            while i < len(messages) and messages[i].get("role") == "tool":
                t = messages[i]
                tool_result_blocks.append({
                    "toolResult": {
                        "toolUseId": t.get("tool_call_id", ""),
                        "content": [{"text": t.get("content", "") or ""}],
                    }
                })
                i += 1
            if tool_result_blocks:
                bedrock_messages.append({"role": "user", "content": tool_result_blocks})
            continue

        # user
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    if "text" in block:
                        parts.append({"text": block["text"]})
                    elif block.get("type") == "text" and "text" in block:
                        parts.append({"text": block["text"]})
            content = [{"text": " ".join(p.get("text", "") for p in parts)}] if parts else [{"text": ""}]
        else:
            if not isinstance(content, str):
                content = str(content)
            content = [{"text": content}]
        bedrock_messages.append({"role": "user", "content": content})
        i += 1

    return system_blocks, bedrock_messages


def _tools_to_bedrock(tools: list[dict[str, Any]]) -> dict[str, Any]:
    """Convert OpenAI-style tools to Bedrock toolConfig."""
    bedrock_tools = []
    for t in tools:
        if t.get("type") != "function":
            continue
        fn = t.get("function", {})
        name = fn.get("name", "")
        description = fn.get("description", "")
        parameters = fn.get("parameters") or {"type": "object", "properties": {}}
        if "type" not in parameters:
            parameters = {"type": "object", "properties": parameters.get("properties", {})}
        bedrock_tools.append({
            "toolSpec": {
                "name": name,
                "description": description,
                "inputSchema": {"json": parameters},
            }
        })
    if not bedrock_tools:
        return {}
    return {
        "tools": bedrock_tools,
        "toolChoice": {"auto": {}},
    }


def _parse_bedrock_response(data: dict) -> LLMResponse:
    """Parse Converse API response into LLMResponse."""
    output = data.get("output", {})
    message = output.get("message", {})
    content_blocks = message.get("content", [])
    text_parts = []
    tool_calls: list[ToolCallRequest] = []

    for block in content_blocks:
        if "text" in block:
            text_parts.append(block["text"])
        if "toolUse" in block:
            tu = block["toolUse"]
            tool_calls.append(ToolCallRequest(
                id=tu.get("toolUseId", ""),
                name=tu.get("name", ""),
                arguments=tu.get("input") or {},
            ))

    usage = {}
    if "usage" in output:
        u = output["usage"]
        usage = {
            "prompt_tokens": u.get("inputTokens", 0),
            "completion_tokens": u.get("outputTokens", 0),
            "total_tokens": u.get("totalTokens", 0),
        }

    stop_reason = output.get("stopReason", "end_turn")
    finish_reason = "tool_use" if stop_reason == "tool_use" else "stop"

    return LLMResponse(
        content="\n".join(text_parts).strip() or None,
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        usage=usage,
    )


class BedrockProvider(LLMProvider):
    """
    AWS Bedrock via Converse API using only the Bedrock API key (Bearer token).
    No boto3 or AWS credentials required.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "anthropic.claude-3-5-sonnet-20241022-v2:0",
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self._base = (api_base or "").rstrip("/") or DEFAULT_BEDROCK_BASE

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        model_id = (model or self.default_model).strip()
        if model_id.startswith("bedrock/"):
            model_id = model_id[8:]
        url = f"{self._base}/model/{model_id}/converse"

        system_blocks, bedrock_messages = _messages_to_bedrock(messages)
        payload: dict[str, Any] = {
            "messages": bedrock_messages,
            "inferenceConfig": {
                "maxTokens": max_tokens,
                "temperature": temperature,
            },
        }
        if system_blocks:
            payload["system"] = system_blocks
        tool_config = _tools_to_bedrock(tools) if tools else {}
        if tool_config:
            payload["toolConfig"] = tool_config

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key or ''}",
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            return _parse_bedrock_response(data)
        except httpx.HTTPStatusError as e:
            try:
                err_body = e.response.json()
                msg = err_body.get("message", err_body.get("error", str(err_body)))
            except Exception:
                msg = e.response.text or str(e)
            return LLMResponse(
                content=f"Error calling Bedrock: {msg}",
                finish_reason="error",
            )
        except Exception as e:
            return LLMResponse(
                content=f"Error calling Bedrock: {str(e)}",
                finish_reason="error",
            )

    def get_default_model(self) -> str:
        return self.default_model
