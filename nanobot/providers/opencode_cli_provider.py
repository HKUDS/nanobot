"""OpenCode CLI provider backed by `opencode run --format json`."""

from __future__ import annotations

import asyncio
import json
import os
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from nanobot.providers.base import LLMProvider, LLMResponse

_MAX_ERROR_SNIPPET = 400


class OpenCodeCLIProvider(LLMProvider):
    """Use the OpenCode CLI as a local agent runtime.

    This adapter is intentionally text-first: it sends a combined prompt to
    `opencode run --format json` and parses the streamed JSON events into a
    final assistant response.
    """

    def __init__(
        self,
        default_model: str = "opencode/grok-code",
        attach_url: str | None = None,
        command: str | None = None,
        cwd: str | Path | None = None,
    ):
        super().__init__(api_key=None, api_base=attach_url)
        self.default_model = default_model
        self.attach_url = attach_url
        self.command = command or os.environ.get("OPENCODE_COMMAND", "opencode")
        self.cwd = Path(cwd) if cwd is not None else None

    def _build_prompt(self, messages: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        for msg in messages:
            role = str(msg.get("role") or "user")
            text = self._extract_text(msg.get("content"))
            if not text and role != "system":
                continue
            if role == "system":
                parts.append(f"System: {text}")
            elif role == "assistant":
                parts.append(f"Assistant: {text}")
            elif role == "tool":
                tool_name = msg.get("name") or msg.get("tool_name") or "tool"
                parts.append(f"Tool[{tool_name}]: {text}")
            else:
                parts.append(f"User: {text}")
        return "\n\n".join(parts).strip()

    @staticmethod
    def _extract_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            chunks: list[str] = []
            for item in value:
                if isinstance(item, str):
                    chunks.append(item)
                    continue
                if isinstance(item, dict):
                    if isinstance(item.get("text"), str):
                        chunks.append(item["text"])
                        continue
                    if isinstance(item.get("content"), str):
                        chunks.append(item["content"])
                        continue
            return "".join(chunks)
        if isinstance(value, dict):
            for key in ("text", "content", "message", "output"):
                nested = value.get(key)
                if isinstance(nested, str):
                    return nested
                if nested is not None:
                    extracted = OpenCodeCLIProvider._extract_text(nested)
                    if extracted:
                        return extracted
        return str(value)

    @staticmethod
    def _iter_json_objects(raw: str) -> list[dict[str, Any]]:
        decoder = json.JSONDecoder()
        idx = 0
        events: list[dict[str, Any]] = []
        while idx < len(raw):
            while idx < len(raw) and raw[idx].isspace():
                idx += 1
            if idx >= len(raw):
                break
            try:
                obj, end = decoder.raw_decode(raw, idx)
            except JSONDecodeError:
                next_brace = raw.find("{", idx + 1)
                if next_brace == -1:
                    break
                idx = next_brace
                continue
            if isinstance(obj, dict):
                events.append(obj)
            idx = end
        return events

    @staticmethod
    def _extract_reason(event: dict[str, Any]) -> str | None:
        part = event.get("part")
        if isinstance(part, dict):
            reason = part.get("reason")
            if isinstance(reason, str):
                return reason
        reason = event.get("reason")
        if isinstance(reason, str):
            return reason
        return None

    @classmethod
    def _parse_output(cls, raw_stdout: str) -> LLMResponse:
        events = cls._iter_json_objects(raw_stdout)
        if not events:
            text = raw_stdout.strip()
            if not text:
                return LLMResponse(content=None, finish_reason="stop")
            return LLMResponse(content=text, finish_reason="stop")

        content_parts: list[str] = []
        finish_reason = "stop"

        for event in events:
            event_type = str(event.get("type") or "")
            part = event.get("part") if isinstance(event.get("part"), dict) else {}
            text = ""
            if event_type == "text":
                text = cls._extract_text(part or event.get("text") or event.get("content"))
            elif event_type in {"assistant", "message.updated", "message"}:
                text = cls._extract_text(event.get("content") or event.get("text") or part or event)
            elif isinstance(part, dict) and part.get("type") in {"text", "output_text"}:
                text = cls._extract_text(part)
            if text:
                content_parts.append(text)
            reason = cls._extract_reason(event)
            if reason:
                finish_reason = reason

        return LLMResponse(
            content="".join(content_parts) or None,
            finish_reason=finish_reason,
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
        del tools, max_tokens, temperature, reasoning_effort, tool_choice

        model_name = model or self.default_model
        prompt = self._build_prompt(messages)
        payload = {"message": prompt}
        stdin_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        args = [self.command, "run", "--format", "json", "--model", model_name]
        if self.attach_url:
            args.extend(["--attach", self.attach_url])

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                cwd=str(self.cwd) if self.cwd else None,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            return LLMResponse(content=f"Error calling OpenCode: {exc}", finish_reason="error")

        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(stdin_data), timeout=1800)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return LLMResponse(content="Error calling OpenCode: command timed out", finish_reason="error")

        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            message = stderr.strip() or stdout.strip() or f"OpenCode exited with code {proc.returncode}"
            return LLMResponse(
                content=f"Error calling OpenCode: {message[:_MAX_ERROR_SNIPPET]}",
                finish_reason="error",
            )

        response = self._parse_output(stdout)
        if response.content is None and stderr.strip():
            return LLMResponse(
                content=f"Error calling OpenCode: {stderr.strip()[:_MAX_ERROR_SNIPPET]}",
                finish_reason="error",
            )
        return response

    def get_default_model(self) -> str:
        return self.default_model
