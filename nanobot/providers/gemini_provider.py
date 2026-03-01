"""Direct Gemini provider using google-genai SDK — bypasses LiteLLM."""

from __future__ import annotations

import base64
import secrets
import string
from typing import Any

from google import genai
from google.genai import types
from loguru import logger

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

_ALNUM = string.ascii_letters + string.digits


def _short_id() -> str:
    return "".join(secrets.choice(_ALNUM) for _ in range(9))


class GeminiProvider(LLMProvider):
    """LLM provider using the google-genai SDK directly."""

    def __init__(self, api_key: str | None = None, default_model: str = "gemini-2.5-flash"):
        super().__init__(api_key)
        self.default_model = default_model
        self._client = genai.Client(api_key=api_key)

    def get_default_model(self) -> str:
        return self.default_model

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
    ) -> LLMResponse:
        model_name = self._resolve_model(model or self.default_model)
        messages = self._sanitize_empty_content(messages)

        system_instruction, contents = self._convert_messages(messages)
        gemini_tools = self._convert_tools(tools) if tools else None

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max(1, max_tokens),
        )
        if gemini_tools:
            config.tools = gemini_tools
            config.tool_config = types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="AUTO"),
            )

        try:
            response = await self._client.aio.models.generate_content(
                model=model_name,
                contents=contents,
                config=config,
            )
            return self._parse_response(response)
        except Exception as e:
            logger.error("Gemini API error: {}", e)
            return LLMResponse(content=f"Error calling Gemini: {e}", finish_reason="error")

    # ------------------------------------------------------------------
    # Model name resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_model(model: str) -> str:
        """Strip provider prefix (e.g. 'gemini/gemini-2.5-flash' → 'gemini-2.5-flash')."""
        if model.startswith("gemini/"):
            model = model[len("gemini/"):]
        return model

    # ------------------------------------------------------------------
    # Message conversion (OpenAI → Gemini)
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_messages(
        messages: list[dict[str, Any]],
    ) -> tuple[str | None, list[types.Content]]:
        """Convert OpenAI-format messages to Gemini Content list.

        Returns (system_instruction, contents).
        """
        system_parts: list[str] = []
        contents: list[types.Content] = []

        # Map tool_call IDs to function names for FunctionResponse
        tc_id_to_name: dict[str, str] = {}

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content")

            if role == "system":
                if isinstance(content, str) and content:
                    system_parts.append(content)
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("text"):
                            system_parts.append(block["text"])
                continue

            if role == "user":
                parts = GeminiProvider._user_content_to_parts(content)
                if parts:
                    contents.append(types.Content(role="user", parts=parts))
                continue

            if role == "assistant":
                parts: list[types.Part] = []
                if isinstance(content, str) and content:
                    parts.append(types.Part(text=content))

                # Tool calls → FunctionCall parts
                for tc in msg.get("tool_calls", []):
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    args = fn.get("arguments", {})
                    if isinstance(args, str):
                        import json_repair
                        args = json_repair.loads(args)
                    tc_id_to_name[tc.get("id", "")] = name
                    parts.append(types.Part(
                        function_call=types.FunctionCall(name=name, args=args),
                    ))

                if parts:
                    contents.append(types.Content(role="model", parts=parts))
                continue

            if role == "tool":
                # Tool result → FunctionResponse
                tc_id = msg.get("tool_call_id", "")
                fn_name = msg.get("name") or tc_id_to_name.get(tc_id, "unknown")
                result_text = content if isinstance(content, str) else str(content or "")
                parts = [types.Part(
                    function_response=types.FunctionResponse(
                        name=fn_name,
                        response={"result": result_text},
                    ),
                )]
                contents.append(types.Content(role="user", parts=parts))
                continue

        system_instruction = "\n\n".join(system_parts) if system_parts else None
        return system_instruction, contents

    @staticmethod
    def _user_content_to_parts(content: Any) -> list[types.Part]:
        """Convert user message content (str or list) to Gemini Parts."""
        if isinstance(content, str):
            return [types.Part(text=content)] if content else []

        if not isinstance(content, list):
            return [types.Part(text=str(content))] if content else []

        parts: list[types.Part] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type", "")
            if btype == "text":
                text = block.get("text", "")
                if text:
                    parts.append(types.Part(text=text))
            elif btype == "image_url":
                url_data = block.get("image_url", {}).get("url", "")
                if url_data.startswith("data:"):
                    # Base64 inline image
                    header, _, b64 = url_data.partition(",")
                    mime = header.split(";")[0].split(":")[1] if ":" in header else "image/png"
                    parts.append(types.Part(
                        inline_data=types.Blob(mime_type=mime, data=base64.b64decode(b64)),
                    ))
        return parts

    # ------------------------------------------------------------------
    # Tool conversion (OpenAI → Gemini)
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_tools(tools: list[dict[str, Any]]) -> list[types.Tool]:
        """Convert OpenAI-format tool definitions to Gemini FunctionDeclarations."""
        declarations: list[types.FunctionDeclaration] = []
        for tool_def in tools:
            fn = tool_def.get("function", {})
            name = fn.get("name", "")
            desc = fn.get("description", "")
            params = fn.get("parameters")
            if not name:
                continue
            declarations.append(types.FunctionDeclaration(
                name=name,
                description=desc,
                parameters=params,
            ))
        return [types.Tool(function_declarations=declarations)] if declarations else []

    # ------------------------------------------------------------------
    # Response parsing (Gemini → LLMResponse)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_response(response: types.GenerateContentResponse) -> LLMResponse:
        """Parse Gemini response into LLMResponse."""
        if not response.candidates:
            return LLMResponse(content="No response from Gemini.", finish_reason="error")

        candidate = response.candidates[0]
        text_parts: list[str] = []
        tool_calls: list[ToolCallRequest] = []

        for part in candidate.content.parts:
            if part.text:
                text_parts.append(part.text)
            if part.function_call:
                fc = part.function_call
                tool_calls.append(ToolCallRequest(
                    id=fc.id or _short_id(),
                    name=fc.name,
                    arguments=dict(fc.args) if fc.args else {},
                ))

        content = "\n".join(text_parts) if text_parts else None
        finish = "tool_calls" if tool_calls else "stop"

        usage: dict[str, int] = {}
        if response.usage_metadata:
            um = response.usage_metadata
            usage = {
                "prompt_tokens": getattr(um, "prompt_token_count", 0) or 0,
                "completion_tokens": getattr(um, "candidates_token_count", 0) or 0,
                "total_tokens": getattr(um, "total_token_count", 0) or 0,
            }

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish,
            usage=usage,
        )
