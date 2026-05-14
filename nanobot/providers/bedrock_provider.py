"""AWS Bedrock Converse provider."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

import json_repair

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

_IMAGE_DATA_URL = re.compile(r"^data:image/([a-zA-Z0-9.+-]+);base64,(.*)$", re.DOTALL)
_TEXT_BLOCK_TYPES = {"text", "input_text", "output_text"}
_TEMPERATURE_UNSUPPORTED_MODEL_TOKENS = ("claude-opus-4-7",)
_ADAPTIVE_THINKING_ONLY_MODEL_TOKENS = ("claude-opus-4-7",)
_NOOP_TOOL_NAME = "nanobot_noop"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _next_or_none(iterator: Iterator[dict[str, Any]]) -> dict[str, Any] | None:
    try:
        return next(iterator)
    except StopIteration:
        return None


class BedrockProvider(LLMProvider):
    """LLM provider using AWS Bedrock Runtime's Converse APIs."""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "bedrock/global.anthropic.claude-opus-4-7",
        *,
        region: str | None = None,
        profile: str | None = None,
        extra_body: dict[str, Any] | None = None,
        client: Any | None = None,
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.region = region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
        self.profile = profile
        self._extra_body = extra_body or {}
        self._client = client if client is not None else self._make_client()

    def _make_client(self) -> Any:
        if self.api_key:
            os.environ["AWS_BEARER_TOKEN_BEDROCK"] = self.api_key
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - exercised only without boto3 installed
            raise RuntimeError(
                "AWS Bedrock provider requires boto3. Install it with `pip install boto3`."
            ) from exc

        session_kwargs: dict[str, Any] = {}
        if self.profile:
            session_kwargs["profile_name"] = self.profile
        session = boto3.Session(**session_kwargs)

        client_kwargs: dict[str, Any] = {}
        if self.region:
            client_kwargs["region_name"] = self.region
        if self.api_base:
            client_kwargs["endpoint_url"] = self.api_base
        return session.client("bedrock-runtime", **client_kwargs)

    @staticmethod
    def _strip_prefix(model: str) -> str:
        if model.startswith("bedrock/"):
            return model[len("bedrock/"):]
        return model

    @staticmethod
    def _matches_model_token(model: str, tokens: tuple[str, ...]) -> bool:
        model_lower = model.lower()
        return any(token in model_lower for token in tokens)

    @classmethod
    def _supports_temperature(cls, model: str) -> bool:
        return not cls._matches_model_token(model, _TEMPERATURE_UNSUPPORTED_MODEL_TOKENS)

    @classmethod
    def _uses_adaptive_thinking_only(cls, model: str) -> bool:
        return cls._matches_model_token(model, _ADAPTIVE_THINKING_ONLY_MODEL_TOKENS)

    @staticmethod
    def _image_url_block(block: dict[str, Any]) -> dict[str, Any] | None:
        url = (block.get("image_url") or {}).get("url", "")
        if not isinstance(url, str) or not url:
            return None
        match = _IMAGE_DATA_URL.match(url)
        if not match:
            return {"text": f"(image URL: {url})"}
        fmt = match.group(1).lower()
        if fmt == "jpg":
            fmt = "jpeg"
        try:
            data = base64.b64decode(match.group(2), validate=False)
        except Exception:
            return {"text": "(invalid image data)"}
        return {"image": {"format": fmt, "source": {"bytes": data}}}

    @classmethod
    def _content_blocks(cls, content: Any, *, for_tool_result: bool = False) -> list[dict[str, Any]]:
        if isinstance(content, str) or content is None:
            return [{"text": content or "(empty)"}]
        if not isinstance(content, list):
            if for_tool_result and isinstance(content, dict):
                return [{"json": content}]
            return [{"text": str(content)}]

        blocks: list[dict[str, Any]] = []
        for item in content:
            if not isinstance(item, dict):
                blocks.append({"text": str(item)})
                continue

            item_type = item.get("type")
            if item_type in _TEXT_BLOCK_TYPES or "text" in item:
                text = item.get("text")
                if text:
                    blocks.append({"text": str(text)})
                continue
            if item_type == "image_url":
                converted = cls._image_url_block(item)
                if converted:
                    blocks.append(converted)
                continue

            # Preserve already-Bedrock-shaped content where possible.
            for key in ("text", "image", "document", "video", "json", "searchResult"):
                if key in item:
                    blocks.append({key: item[key]})
                    break
            else:
                blocks.append({"json": item} if for_tool_result else {"text": json.dumps(item)})

        return blocks or [{"text": "(empty)"}]

    @classmethod
    def _system_blocks(cls, content: Any) -> list[dict[str, Any]]:
        return [
            block for block in cls._content_blocks(content)
            if "text" in block or "cachePoint" in block or "guardContent" in block
        ]

    @classmethod
    def _tool_result_block(cls, msg: dict[str, Any]) -> dict[str, Any]:
        return {
            "toolResult": {
                "toolUseId": str(msg.get("tool_call_id") or ""),
                "content": cls._content_blocks(msg.get("content"), for_tool_result=True),
                "status": "success",
            }
        }

    @staticmethod
    def _tool_use_block(tool_call: dict[str, Any]) -> dict[str, Any] | None:
        function = tool_call.get("function")
        if not isinstance(function, dict):
            return None
        args = function.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json_repair.loads(args) if args.strip() else {}
            except Exception:
                args = {}
        if not isinstance(args, dict):
            args = {}
        return {
            "toolUse": {
                "toolUseId": str(tool_call.get("id") or ""),
                "name": str(function.get("name") or ""),
                "input": args,
            }
        }

    @staticmethod
    def _reasoning_block(block: dict[str, Any]) -> dict[str, Any] | None:
        if block.get("type") not in {"thinking", "reasoning", "redacted_thinking"}:
            return None
        text = block.get("thinking") or block.get("text")
        signature = block.get("signature")
        if text and signature:
            return {
                "reasoningContent": {
                    "reasoningText": {"text": str(text), "signature": str(signature)}
                }
            }
        redacted = block.get("redactedContent")
        if redacted is None and isinstance(block.get("redactedContentBase64"), str):
            try:
                redacted = base64.b64decode(block["redactedContentBase64"])
            except Exception:
                redacted = None
        if redacted is not None:
            return {"reasoningContent": {"redactedContent": redacted}}
        return None

    @classmethod
    def _assistant_blocks(cls, msg: dict[str, Any]) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []

        for thinking in msg.get("thinking_blocks") or []:
            if isinstance(thinking, dict):
                reasoning = cls._reasoning_block(thinking)
                if reasoning:
                    blocks.append(reasoning)

        content = msg.get("content")
        if isinstance(content, str) and content:
            blocks.append({"text": content})
        elif isinstance(content, list):
            blocks.extend(block for block in cls._content_blocks(content) if "text" in block)

        for tool_call in msg.get("tool_calls") or []:
            if isinstance(tool_call, dict):
                block = cls._tool_use_block(tool_call)
                if block:
                    blocks.append(block)

        return blocks or [{"text": ""}]

    @staticmethod
    def _has_tool_use(msg: dict[str, Any]) -> bool:
        content = msg.get("content")
        return isinstance(content, list) and any(
            isinstance(block, dict) and "toolUse" in block for block in content
        )

    @staticmethod
    def _merge_consecutive(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        for msg in messages:
            if merged and merged[-1].get("role") == msg.get("role"):
                prev = merged[-1].setdefault("content", [])
                cur = msg.get("content") or []
                if not isinstance(prev, list):
                    prev = [{"text": str(prev)}]
                    merged[-1]["content"] = prev
                if isinstance(cur, list):
                    prev.extend(cur)
                else:
                    prev.append({"text": str(cur)})
            else:
                merged.append(msg)

        last_popped: dict[str, Any] | None = None
        while merged and merged[-1].get("role") == "assistant":
            last_popped = merged.pop()
        if not merged and last_popped is not None and not BedrockProvider._has_tool_use(last_popped):
            merged.append({"role": "user", "content": last_popped.get("content") or [{"text": "(empty)"}]})
        if merged and merged[0].get("role") == "assistant" and not BedrockProvider._has_tool_use(merged[0]):
            merged.insert(0, {"role": "user", "content": [{"text": "(conversation continued)"}]})
        return merged

    def _convert_messages(
        self,
        messages: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        system: list[dict[str, Any]] = []
        converted: list[dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            if role == "system":
                system.extend(self._system_blocks(content))
                continue
            if role == "tool":
                block = self._tool_result_block(msg)
                if converted and converted[-1].get("role") == "user":
                    converted[-1].setdefault("content", []).append(block)
                else:
                    converted.append({"role": "user", "content": [block]})
                continue
            if role == "assistant":
                converted.append({"role": "assistant", "content": self._assistant_blocks(msg)})
                continue
            if role == "user":
                converted.append({"role": "user", "content": self._content_blocks(content)})

        return system, self._merge_consecutive(converted)

    @staticmethod
    def _convert_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        result: list[dict[str, Any]] = []
        for tool in tools:
            func = tool.get("function") if isinstance(tool.get("function"), dict) else tool
            if not isinstance(func, dict):
                continue
            name = str(func.get("name") or "")
            if not name:
                continue
            spec: dict[str, Any] = {
                "name": name,
                "inputSchema": {
                    "json": func.get("parameters") or {"type": "object", "properties": {}}
                },
            }
            description = func.get("description")
            if description:
                spec["description"] = str(description)
            strict = func.get("strict", tool.get("strict"))
            if isinstance(strict, bool):
                spec["strict"] = strict
            result.append({"toolSpec": spec})
        return result or None

    @staticmethod
    def _contains_tool_blocks(messages: list[dict[str, Any]]) -> bool:
        for msg in messages:
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and ("toolUse" in block or "toolResult" in block):
                    return True
        return False

    @staticmethod
    def _noop_tool() -> dict[str, Any]:
        return {
            "toolSpec": {
                "name": _NOOP_TOOL_NAME,
                "description": "Internal placeholder for Bedrock tool history validation.",
                "inputSchema": {"json": {"type": "object", "properties": {}}},
            }
        }

    @staticmethod
    def _convert_tool_choice(
        tool_choice: str | dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if tool_choice is None or tool_choice == "auto":
            return {"auto": {}}
        if tool_choice == "required":
            return {"any": {}}
        if tool_choice == "none":
            return None
        if isinstance(tool_choice, dict):
            name = tool_choice.get("function", {}).get("name")
            if name:
                return {"tool": {"name": str(name)}}
        return {"auto": {}}

    @staticmethod
    def _adaptive_thinking(reasoning_effort: str | None) -> dict[str, Any] | None:
        if not reasoning_effort:
            return None
        effort = reasoning_effort.lower()
        if effort == "none":
            return None
        thinking: dict[str, Any] = {"type": "adaptive"}
        if effort != "adaptive":
            thinking["effort"] = effort
        return thinking

    def _build_kwargs(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        max_tokens: int,
        temperature: float,
        reasoning_effort: str | None,
        tool_choice: str | dict[str, Any] | None,
    ) -> dict[str, Any]:
        model_id = self._strip_prefix(model or self.default_model)
        system, bedrock_messages = self._convert_messages(self._sanitize_empty_content(messages))
        if not bedrock_messages:
            bedrock_messages = [{"role": "user", "content": [{"text": "(empty)"}]}]

        kwargs: dict[str, Any] = {
            "modelId": model_id,
            "messages": bedrock_messages,
            "inferenceConfig": {"maxTokens": max(1, max_tokens)},
        }
        if system:
            kwargs["system"] = system
        if self._supports_temperature(model_id):
            kwargs["inferenceConfig"]["temperature"] = temperature

        additional: dict[str, Any] = {}
        if self._uses_adaptive_thinking_only(model_id):
            thinking = self._adaptive_thinking(reasoning_effort)
            if thinking:
                additional["thinking"] = thinking
        if self._extra_body:
            additional = _deep_merge(additional, self._extra_body)
        if additional:
            kwargs["additionalModelRequestFields"] = additional

        bedrock_tools = self._convert_tools(tools)
        tool_config: dict[str, Any] | None = None
        if bedrock_tools:
            tool_config = {"tools": bedrock_tools}
            choice = self._convert_tool_choice(tool_choice)
            if choice:
                tool_config["toolChoice"] = choice
        elif self._contains_tool_blocks(bedrock_messages):
            tool_config = {"tools": [self._noop_tool()]}

        if tool_config:
            kwargs["toolConfig"] = tool_config

        return kwargs

    @staticmethod
    def _finish_reason(stop_reason: str | None) -> str:
        return {
            "end_turn": "stop",
            "tool_use": "tool_calls",
            "max_tokens": "length",
        }.get(stop_reason or "", stop_reason or "stop")

    @staticmethod
    def _usage(usage: dict[str, Any] | None) -> dict[str, int]:
        if not usage:
            return {}
        prompt = int(usage.get("inputTokens") or 0)
        completion = int(usage.get("outputTokens") or 0)
        total = int(usage.get("totalTokens") or prompt + completion)
        result = {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": total,
        }
        cache_read = int(usage.get("cacheReadInputTokens") or 0)
        cache_write = int(usage.get("cacheWriteInputTokens") or 0)
        if cache_read:
            result["cached_tokens"] = cache_read
            result["cache_read_input_tokens"] = cache_read
        if cache_write:
            result["cache_creation_input_tokens"] = cache_write
        return result

    @staticmethod
    def _parse_reasoning(block: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
        reasoning = block.get("reasoningContent")
        if not isinstance(reasoning, dict):
            return None, None
        text_obj = reasoning.get("reasoningText")
        if isinstance(text_obj, dict):
            text = text_obj.get("text")
            if isinstance(text, str):
                return text, {
                    "type": "thinking",
                    "thinking": text,
                    "signature": text_obj.get("signature", ""),
                }
        redacted = reasoning.get("redactedContent")
        if redacted is not None:
            if isinstance(redacted, (bytes, bytearray)):
                encoded = base64.b64encode(bytes(redacted)).decode("ascii")
                return None, {"type": "redacted_thinking", "redactedContentBase64": encoded}
            return None, {"type": "redacted_thinking", "redactedContent": redacted}
        return None, None

    @classmethod
    def _parse_response(cls, response: dict[str, Any]) -> LLMResponse:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: list[ToolCallRequest] = []
        thinking_blocks: list[dict[str, Any]] = []
        message = (response.get("output") or {}).get("message") or {}

        for block in message.get("content") or []:
            if not isinstance(block, dict):
                continue
            if isinstance(block.get("text"), str):
                content_parts.append(block["text"])
            tool_use = block.get("toolUse")
            if isinstance(tool_use, dict):
                arguments = tool_use.get("input") if isinstance(tool_use.get("input"), dict) else {}
                tool_calls.append(ToolCallRequest(
                    id=str(tool_use.get("toolUseId") or ""),
                    name=str(tool_use.get("name") or ""),
                    arguments=arguments,
                ))
            reasoning_text, thinking = cls._parse_reasoning(block)
            if reasoning_text:
                reasoning_parts.append(reasoning_text)
            if thinking:
                thinking_blocks.append(thinking)

        return LLMResponse(
            content="".join(content_parts) or None,
            tool_calls=tool_calls,
            finish_reason=cls._finish_reason(response.get("stopReason")),
            usage=cls._usage(response.get("usage")),
            reasoning_content="".join(reasoning_parts) or None,
            thinking_blocks=thinking_blocks or None,
        )

    @classmethod
    def _parse_stream_event(
        cls,
        event: dict[str, Any],
        *,
        content_parts: list[str],
        reasoning_parts: list[str],
        thinking_blocks: list[dict[str, Any]],
        tool_buffers: dict[int, dict[str, Any]],
        state: dict[str, Any],
    ) -> str | None:
        if "contentBlockStart" in event:
            data = event["contentBlockStart"]
            idx = int(data.get("contentBlockIndex") or 0)
            start = data.get("start") or {}
            tool_use = start.get("toolUse")
            if isinstance(tool_use, dict):
                tool_buffers[idx] = {
                    "id": str(tool_use.get("toolUseId") or ""),
                    "name": str(tool_use.get("name") or ""),
                    "input": "",
                }
            return None

        if "contentBlockDelta" in event:
            data = event["contentBlockDelta"]
            idx = int(data.get("contentBlockIndex") or 0)
            delta = data.get("delta") or {}
            text = delta.get("text")
            if isinstance(text, str):
                content_parts.append(text)
                return text
            tool_delta = delta.get("toolUse")
            if isinstance(tool_delta, dict):
                buf = tool_buffers.setdefault(idx, {"id": "", "name": "", "input": ""})
                if isinstance(tool_delta.get("input"), str):
                    buf["input"] += tool_delta["input"]
            reasoning = delta.get("reasoningContent")
            if isinstance(reasoning, dict):
                buf = state.setdefault("reasoning_buffers", {}).setdefault(
                    idx, {"text": "", "signature": "", "redactedContent": None}
                )
                if isinstance(reasoning.get("text"), str):
                    buf["text"] += reasoning["text"]
                    reasoning_parts.append(reasoning["text"])
                if isinstance(reasoning.get("signature"), str):
                    buf["signature"] = reasoning["signature"]
                if reasoning.get("redactedContent") is not None:
                    buf["redactedContent"] = reasoning["redactedContent"]
            return None

        if "contentBlockStop" in event:
            idx = int((event["contentBlockStop"] or {}).get("contentBlockIndex") or 0)
            reasoning_buf = state.setdefault("reasoning_buffers", {}).pop(idx, None)
            if reasoning_buf:
                if reasoning_buf.get("text"):
                    thinking_blocks.append({
                        "type": "thinking",
                        "thinking": reasoning_buf["text"],
                        "signature": reasoning_buf.get("signature", ""),
                    })
                elif reasoning_buf.get("redactedContent") is not None:
                    redacted = reasoning_buf["redactedContent"]
                    if isinstance(redacted, (bytes, bytearray)):
                        redacted_block = {
                            "type": "redacted_thinking",
                            "redactedContentBase64": base64.b64encode(bytes(redacted)).decode("ascii"),
                        }
                    else:
                        redacted_block = {
                            "type": "redacted_thinking",
                            "redactedContent": redacted,
                        }
                    thinking_blocks.append({
                        **redacted_block,
                    })
            return None

        if "messageStop" in event:
            state["stop_reason"] = (event["messageStop"] or {}).get("stopReason")
            return None

        if "metadata" in event:
            metadata = event["metadata"] or {}
            if isinstance(metadata.get("usage"), dict):
                state["usage"] = metadata["usage"]
            return None

        return None

    @classmethod
    def _stream_result(
        cls,
        *,
        content_parts: list[str],
        reasoning_parts: list[str],
        thinking_blocks: list[dict[str, Any]],
        tool_buffers: dict[int, dict[str, Any]],
        state: dict[str, Any],
    ) -> LLMResponse:
        tool_calls: list[ToolCallRequest] = []
        for buf in tool_buffers.values():
            args: Any = {}
            if buf.get("input"):
                try:
                    args = json_repair.loads(buf["input"])
                except Exception:
                    args = {}
            tool_calls.append(ToolCallRequest(
                id=buf.get("id") or "",
                name=buf.get("name") or "",
                arguments=args if isinstance(args, dict) else {},
            ))
        return LLMResponse(
            content="".join(content_parts) or None,
            tool_calls=tool_calls,
            finish_reason=cls._finish_reason(state.get("stop_reason")),
            usage=cls._usage(state.get("usage")),
            reasoning_content="".join(reasoning_parts) or None,
            thinking_blocks=thinking_blocks or None,
        )

    @classmethod
    def _handle_error(cls, e: Exception) -> LLMResponse:
        response = getattr(e, "response", None)
        metadata = response.get("ResponseMetadata", {}) if isinstance(response, dict) else {}
        headers = metadata.get("HTTPHeaders") if isinstance(metadata, dict) else None
        error_obj = response.get("Error", {}) if isinstance(response, dict) else {}
        message = error_obj.get("Message") if isinstance(error_obj, dict) else None
        code = error_obj.get("Code") if isinstance(error_obj, dict) else None
        status_code = metadata.get("HTTPStatusCode") if isinstance(metadata, dict) else None
        body = message or str(e)
        retry_after = cls._extract_retry_after_from_headers(headers)
        if retry_after is None:
            retry_after = cls._extract_retry_after(body)

        error_name = e.__class__.__name__.lower()
        error_kind = None
        if "timeout" in error_name:
            error_kind = "timeout"
        elif "connection" in error_name or "endpoint" in error_name:
            error_kind = "connection"

        code_text = str(code or "").lower()
        should_retry = None
        if status_code is not None:
            should_retry = int(status_code) == 429 or int(status_code) >= 500
        if any(token in code_text for token in ("throttl", "timeout", "unavailable", "modelnotready")):
            should_retry = True

        return LLMResponse(
            content=f"Error: {str(body).strip()[:500]}",
            finish_reason="error",
            retry_after=retry_after,
            error_status_code=int(status_code) if status_code is not None else None,
            error_kind=error_kind,
            error_type=code_text or None,
            error_code=code_text or None,
            error_retry_after_s=retry_after,
            error_should_retry=should_retry,
        )

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
        try:
            kwargs = self._build_kwargs(
                messages, tools, model, max_tokens, temperature, reasoning_effort, tool_choice
            )
            response = await asyncio.to_thread(self._client.converse, **kwargs)
            return self._parse_response(response)
        except Exception as e:
            return self._handle_error(e)

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        idle_timeout_s = int(os.environ.get("NANOBOT_STREAM_IDLE_TIMEOUT_S", "90"))
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        thinking_blocks: list[dict[str, Any]] = []
        tool_buffers: dict[int, dict[str, Any]] = {}
        state: dict[str, Any] = {}

        try:
            kwargs = self._build_kwargs(
                messages, tools, model, max_tokens, temperature, reasoning_effort, tool_choice
            )
            response = await asyncio.to_thread(self._client.converse_stream, **kwargs)
            stream = iter(response.get("stream") or [])
            while True:
                event = await asyncio.wait_for(
                    asyncio.to_thread(_next_or_none, stream),
                    timeout=idle_timeout_s,
                )
                if event is None:
                    break
                delta = self._parse_stream_event(
                    event,
                    content_parts=content_parts,
                    reasoning_parts=reasoning_parts,
                    thinking_blocks=thinking_blocks,
                    tool_buffers=tool_buffers,
                    state=state,
                )
                if delta and on_content_delta:
                    await on_content_delta(delta)
            return self._stream_result(
                content_parts=content_parts,
                reasoning_parts=reasoning_parts,
                thinking_blocks=thinking_blocks,
                tool_buffers=tool_buffers,
                state=state,
            )
        except asyncio.TimeoutError:
            return LLMResponse(
                content=(
                    f"Error calling LLM: stream stalled for more than "
                    f"{idle_timeout_s} seconds"
                ),
                finish_reason="error",
                error_kind="timeout",
            )
        except Exception as e:
            return self._handle_error(e)

    def get_default_model(self) -> str:
        return self.default_model
