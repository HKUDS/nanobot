"""Antigravity OAuth LLM Provider."""

from __future__ import annotations

import asyncio
import hashlib
import json
import base64
from typing import Any, AsyncGenerator

import httpx
from loguru import logger

from oauth_cli_kit import get_token as get_ag_token
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

DEFAULT_ANTIGRAVITY_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class AntigravityProvider(LLMProvider):
    """Use Antigravity OAuth to call the Google Gemini endpoints."""

    def __init__(self, default_model: str = "antigravity/gemini-2.5-flash"):
        super().__init__(api_key=None, api_base=None)
        self.default_model = default_model

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        model = model or self.default_model
        bare_model = _strip_model_prefix(model)
        
        system_instruction, contents = _convert_messages(messages)

        token = await asyncio.to_thread(_get_token_safe)
        headers = _build_headers(token)

        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            }
        }
        
        if system_instruction:
            body["systemInstruction"] = system_instruction
           
        # Handle reasoning parameters
        if "thinking" in bare_model or "pro" in bare_model or "flash" in bare_model:
            body["generationConfig"]["thinkingConfig"] = {
                "thinkingBudget": 4096,
                "includeThoughts": True
            }

        if tools:
            body["tools"] = _convert_tools(tools)

        # Build url for streaming contents
        url = f"{DEFAULT_ANTIGRAVITY_URL}/{bare_model}:streamGenerateContent"

        try:
            try:
                content, tool_calls, finish_reason = await _request_ag(url, headers, body, verify=True)
            except Exception as e:
                if "CERTIFICATE_VERIFY_FAILED" not in str(e):
                    raise
                logger.warning("SSL certificate verification failed for Antigravity API; retrying with verify=False")
                content, tool_calls, finish_reason = await _request_ag(url, headers, body, verify=False)
            
            return LLMResponse(
                content=content,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
            )
        except Exception as e:
            return LLMResponse(
                content=f"Error calling Antigravity API: {str(e)}",
                finish_reason="error",
            )

    def get_default_model(self) -> str:
        return self.default_model


def _get_token_safe() -> str | None:
    try:
        from oauth_cli_kit import get_token
        # Try to use existing token retrieval assuming it supports Antigravity
        token = get_token()
        return getattr(token, 'access', getattr(token, 'token', str(token)))
    except Exception as e:
        logger.warning(f"Could not retrieve OAuth token using oauth_cli_kit: {e}")
        # As a fallback, we can try invoking opencode if it's installed via subprocess
        import subprocess
        try:
            result = subprocess.run(['opencode', 'auth', 'print-access-token'], capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except:
            return None


def _strip_model_prefix(model: str) -> str:
    if model.startswith("antigravity/"):
        return model.split("/", 1)[1]
    if model.startswith("google/"): # Sometimes models come with google/ prefix
        return model.split("/", 1)[1]
    return model


def _build_headers(token: str | None) -> dict[str, str]:
    headers = {
        "User-Agent": "nanobot (python)",
        "Content-Type": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def _request_ag(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    verify: bool,
) -> tuple[str, list[ToolCallRequest], str]:
    
    url_with_query = f"{url}?alt=sse"
    
    async with httpx.AsyncClient(timeout=60.0, verify=verify) as client:
        async with client.stream("POST", url_with_query, headers=headers, json=body) as response:
            if response.status_code != 200:
                text = await response.aread()
                raise RuntimeError(_friendly_error(response.status_code, text.decode("utf-8", "ignore")))
            return await _consume_sse(response)


def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert OpenAI function-calling schema to Google Gemini format."""
    function_declarations: list[dict[str, Any]] = []
    
    for tool in tools:
        fn = (tool.get("function") or {}) if tool.get("type") == "function" else tool
        name = fn.get("name")
        if not name:
            continue
        params = fn.get("parameters") or {"type": "object", "properties": {}}
        function_declarations.append({
            "name": name,
            "description": fn.get("description") or "",
            "parameters": params,
        })
        
    return [{"functionDeclarations": function_declarations}]


def _convert_messages(messages: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Convert OpenAI message format to Gemini parts format."""
    system_prompt = None
    contents: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")

        if role == "system":
            if isinstance(content, str) and content:
                system_prompt = {"role": "system", "parts": [{"text": content}]}
            continue
            
        if role == "user":
            parts = []
            if isinstance(content, str):
                parts.append({"text": content})
            elif isinstance(content, list):
                for item in content:
                    if item.get("type") == "text":
                        parts.append({"text": item.get("text", "")})
                    elif item.get("type") == "image_url":
                        url = (item.get("image_url") or {}).get("url")
                        if url and url.startswith("data:"):
                            parts.append({
                                "inlineData": {
                                    "data": url.split(",", 1)[1],
                                    "mimeType": url.split(";")[0].split(":")[1]
                                }
                            })
            if parts:
                contents.append({"role": "user", "parts": parts})
            continue

        if role == "assistant":
            parts = []
            if isinstance(content, str) and content:
                parts.append({"text": content})
            
            for tool_call in msg.get("tool_calls", []) or []:
                fn = tool_call.get("function") or {}
                call_id = tool_call.get("id") or "call_0"
                args_str = fn.get("arguments") or "{}"
                
                try:
                    args = json.loads(args_str)
                except Exception:
                    args = {}
                    
                parts.append({
                    "functionCall": {
                        "name": fn.get("name"),
                        "args": args
                    }
                })
            if parts:
                contents.append({"role": "model", "parts": parts})
            continue

        if role == "tool":
            call_id = msg.get("tool_call_id") or "call_0"
            output_data = content if isinstance(content, dict) else {"result": content}
            
            contents.append({
                "role": "function",
                "parts": [{
                    "functionResponse": {
                        "name": call_id,  # Simplified logic
                        "response": output_data
                    }
                }]
            })

    return system_prompt, contents


async def _iter_sse(response: httpx.Response) -> AsyncGenerator[dict[str, Any], None]:
    buffer: list[str] = []
    async for line in response.aiter_lines():
        if line == "":
            if buffer:
                data_lines = [l[5:].strip() for l in buffer if l.startswith("data:")]
                buffer = []
                if not data_lines:
                    continue
                data = "\n".join(data_lines).strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    yield json.loads(data)
                except Exception:
                    continue
            continue
        buffer.append(line)


async def _consume_sse(response: httpx.Response) -> tuple[str, list[ToolCallRequest], str]:
    text_content = ""
    tool_calls: list[ToolCallRequest] = []
    finish_reason = "stop"

    async for event in _iter_sse(response):
        candidates = event.get("candidates", [])
        if not candidates:
            continue
            
        candidate = candidates[0]
        content = candidate.get("content", {})
        parts = content.get("parts", [])
        
        for part in parts:
            if "text" in part:
                text_content += part["text"]
            if "executableCode" in part:
                code_text = part["executableCode"].get("code", "")
                text_content += f"\n```python\n{code_text}\n```\n"
            if "functionCall" in part:
                fn_call = part["functionCall"]
                name = fn_call.get("name")
                args = fn_call.get("args") or {}
                # Mock an ID for LiteLLM compatibility
                call_id = f"call_{len(tool_calls)}" 
                tool_calls.append(
                    ToolCallRequest(
                        id=call_id,
                        name=name,
                        arguments=args,
                    )
                )
                
        if "finishReason" in candidate:
            reason = candidate["finishReason"]
            if reason == "STOP":
                finish_reason = "stop"
            elif reason == "MAX_TOKENS":
                finish_reason = "length"
            else:
                finish_reason = reason.lower()

    return text_content, tool_calls, finish_reason


def _friendly_error(status_code: int, raw: str) -> str:
    if status_code == 401:
        return f"Authentication failed (401). Is the OAuth token valid?\nDetails: {raw}"
    if status_code == 403:
        return f"Permission denied (403).\nDetails: {raw}"
    if status_code == 429:
        return "Rate limit exceeded or quota exhausted. Please try again later."
    return f"HTTP {status_code}: {raw}"
