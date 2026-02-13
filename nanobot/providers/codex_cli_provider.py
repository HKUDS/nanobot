"""Codex CLI-backed provider for OpenAI Codex OAuth flows."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from nanobot.providers.base import LLMProvider, LLMResponse


class CodexCLIProvider(LLMProvider):
    """LLM provider that delegates inference to `codex exec --json`."""

    def __init__(self, default_model: str = "openai-codex/gpt-5.3-codex"):
        super().__init__(api_key=None, api_base=None)
        self.default_model = default_model

    @staticmethod
    def _normalize_model(model: str) -> str:
        model = model.strip()
        if model.startswith("openai-codex/"):
            return model.split("/", 1)[1]
        if model.startswith("openai/"):
            return model.split("/", 1)[1]
        return model

    @staticmethod
    def _fallback_model(model: str) -> str | None:
        fallbacks = {
            "gpt-5.3-codex": "gpt-5.2-codex",
            "gpt-5.2-codex": "gpt-5.1-codex",
        }
        return fallbacks.get(model.strip().lower())

    @staticmethod
    def _message_to_text(message: dict[str, Any]) -> str:
        role = str(message.get("role", "user"))
        content = message.get("content", "")
        text = ""
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    maybe = item.get("text")
                    if isinstance(maybe, str):
                        parts.append(maybe)
            text = "\n".join([p for p in parts if p])
        else:
            text = str(content)
        return f"{role.upper()}: {text}".strip()

    def _build_prompt(self, messages: list[dict[str, Any]]) -> str:
        if not messages:
            return ""
        return "\n\n".join(self._message_to_text(m) for m in messages if isinstance(m, dict))

    @staticmethod
    def _parse_jsonl_output(stdout: str) -> str:
        texts: list[str] = []
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(parsed, dict):
                continue
            item = parsed.get("item")
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            item_type = str(item.get("type", "")).lower()
            if not item_type or "message" in item_type:
                texts.append(text.strip())
        return "\n".join(t for t in texts if t).strip()

    async def _run_codex(self, model: str, prompt: str) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            "codex",
            "exec",
            "--json",
            "--color",
            "never",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--model",
            model,
            prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode, stdout.decode("utf-8", errors="replace"), stderr.decode(
            "utf-8", errors="replace"
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        del tools, max_tokens, temperature
        normalized_model = self._normalize_model(model or self.default_model)
        prompt = self._build_prompt(messages)

        attempt_model = normalized_model
        tried: set[str] = set()
        last_error = ""
        while True:
            tried.add(attempt_model)
            try:
                code, stdout, stderr = await self._run_codex(attempt_model, prompt)
            except FileNotFoundError:
                return LLMResponse(
                    content=(
                        "Error calling LLM: codex CLI is not installed or not on PATH. "
                        "Install Codex CLI and run `codex login`."
                    ),
                    finish_reason="error",
                )

            if code == 0:
                text = self._parse_jsonl_output(stdout)
                if text:
                    return LLMResponse(content=text, finish_reason="stop")
                return LLMResponse(content=stdout.strip() or "No response from Codex CLI.", finish_reason="stop")

            err = (stderr or stdout or "").strip()
            last_error = err or f"codex exited with code {code}"
            err_lower = last_error.lower()
            can_retry = "does not exist" in err_lower or "do not have access" in err_lower
            fallback = self._fallback_model(attempt_model)
            if not can_retry or not fallback or fallback in tried:
                break
            attempt_model = fallback

        return LLMResponse(content=f"Error calling LLM: {last_error}", finish_reason="error")

    def get_default_model(self) -> str:
        return self.default_model
