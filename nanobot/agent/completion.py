"""Bounded, independent completion review for explicitly verified tasks."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from nanobot.providers.base import LLMResponse, LLMUsage, ProviderCallContext, ToolCallRequest
from nanobot.utils.helpers import (
    build_assistant_message,
    estimate_message_tokens,
    estimate_prompt_tokens_chain,
)
from nanobot.utils.llm_runtime import LLMRuntime
from nanobot.utils.prompt_templates import render_template

CompletionStatus = Literal["verified", "needs_revision", "blocked", "exhausted"]

_REVIEW_TIMEOUT_SECONDS = 30
_MAX_REVIEW_TOKENS = 1024
_MAX_EVIDENCE_CHARS = 64_000
_TOOL_STATUS_KEY = "_completion_tool_status"


@dataclass(frozen=True, slots=True)
class CompletionVerdict:
    """A judgment bound to the exact evidence supplied to the reviewer."""

    status: CompletionStatus
    reason: str
    evidence_ids: tuple[str, ...] = ()
    evidence_digest: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "reason": self.reason,
            "evidence_ids": list(self.evidence_ids),
            "evidence_digest": self.evidence_digest,
        }


@dataclass(slots=True)
class CompletionRunEvidence:
    """A turn-local view over messages appended after the runner starts."""

    _messages: list[dict[str, Any]] = field(repr=False)
    _start: int
    usage: LLMUsage | None = None
    round_usages: list[LLMUsage] = field(default_factory=list)
    verified_goal: tuple[str, CompletionVerdict] | None = None
    _tool_statuses: dict[str, str] = field(default_factory=dict, repr=False)

    def snapshot(self) -> list[dict[str, Any]]:
        """Detach current-run observations; prior conversation is not evidence."""
        messages = deepcopy(self._messages[self._start:])
        for message in messages:
            if message.get("role") == "tool":
                call_id = message.get("tool_call_id")
                if isinstance(call_id, str) and call_id in self._tool_statuses:
                    message[_TOOL_STATUS_KEY] = self._tool_statuses[call_id]
        return messages

    def record_tool_results(
        self, tool_calls: list[ToolCallRequest], events: list[dict[str, str]],
    ) -> None:
        """Keep execution status outside provider transcripts and attach it to snapshots."""
        for call, event in zip(tool_calls, events, strict=True):
            self._tool_statuses[call.id] = event["status"]

    def record_usage(self, usage: LLMUsage | None) -> None:
        """Include auxiliary reviews in the run total without recording them twice."""
        if usage is not None:
            self.usage = usage if self.usage is None else self.usage + usage
            self.round_usages.append(usage)


_CURRENT_EVIDENCE: ContextVar[CompletionRunEvidence | None] = ContextVar(
    "nanobot_completion_run_evidence", default=None,
)


def current_completion_evidence() -> CompletionRunEvidence | None:
    return _CURRENT_EVIDENCE.get()


@contextmanager
def completion_evidence_scope(
    messages: list[dict[str, Any]],
) -> Generator[CompletionRunEvidence]:
    """Expose this run's live transcript while keeping nested runs isolated."""
    evidence = CompletionRunEvidence(messages, len(messages))
    token = _CURRENT_EVIDENCE.set(evidence)
    try:
        yield evidence
    finally:
        _CURRENT_EVIDENCE.reset(token)


def _text_content(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return None
    parts: list[str] = []
    for item in cast(list[object], value):
        if not isinstance(item, dict):
            continue
        block = cast(dict[str, object], item)
        text = block.get("text")
        if block.get("type") == "text" and isinstance(text, str):
            parts.append(text)
    return "\n".join(parts) or None


def _project_evidence(messages: list[dict[str, Any]]) -> list[dict[str, object]]:
    """Pair runtime tool results with calls, excluding the builder's narrative."""
    calls: dict[str, dict[str, object]] = {}
    used_ids = {"candidate"}
    evidence: list[dict[str, object]] = []
    injection = 0
    for message in messages:
        role = message.get("role")
        if role == "assistant":
            raw_calls: object = message.get("tool_calls", [])
            if not isinstance(raw_calls, list):
                continue
            for raw_call in cast(list[object], raw_calls):
                if not isinstance(raw_call, dict):
                    continue
                call = cast(dict[str, object], raw_call)
                call_id, function = call.get("id"), call.get("function")
                if not isinstance(call_id, str) or not isinstance(function, dict):
                    continue
                function = cast(dict[str, object], function)
                name, arguments = function.get("name"), function.get("arguments")
                if not call_id or not isinstance(name, str) or not name:
                    continue
                if call_id in calls or call_id in used_ids or call_id.startswith("injection:"):
                    raise ValueError("Ambiguous tool evidence IDs.")
                calls[call_id] = {"name": name, "arguments": arguments}
        elif role == "tool":
            call_id = message.get("tool_call_id")
            if not isinstance(call_id, str) or call_id not in calls:
                continue
            call = calls.pop(call_id)
            content = _text_content(message.get("content"))
            if content is None or message.get("name", call["name"]) != call["name"]:
                continue
            used_ids.add(call_id)
            evidence.append({
                "id": call_id,
                "kind": "tool_result",
                **call,
                "status": message.get(_TOOL_STATUS_KEY, "unknown"),
                "result": content,
            })
        elif role == "user":
            content = _text_content(message.get("content"))
            if content:
                injection += 1
                evidence.append({
                    "id": f"injection:{injection}",
                    "kind": "user_message",
                    "content": content,
                })
    return evidence


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate review fields.")
        result[key] = value
    return result


def _parse_verdict(
    content: str | None, allowed_ids: set[str], digest: str,
) -> CompletionVerdict:
    """Parse one exact response schema; malformed output never grants completion."""
    value: object = json.loads(content or "", object_pairs_hook=_unique_json_object)
    if not isinstance(value, dict):
        raise ValueError("Review must be a JSON object.")
    payload = cast(dict[str, object], value)
    if set(payload) != {"status", "reason", "evidence_ids"}:
        raise ValueError("Review fields do not match the required schema.")
    status, reason, ids = payload["status"], payload["reason"], payload["evidence_ids"]
    if status == "verified":
        normalized_status: CompletionStatus = "verified"
    elif status == "needs_revision":
        normalized_status = "needs_revision"
    elif status == "blocked":
        normalized_status = "blocked"
    else:
        raise ValueError("Invalid review status.")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
        raise ValueError("Review requires a bounded, non-empty reason.")
    if not isinstance(ids, list):
        raise ValueError("Review evidence IDs must be a list.")
    evidence_ids: list[str] = []
    for evidence_id in cast(list[object], ids):
        if not isinstance(evidence_id, str) or evidence_id not in allowed_ids:
            raise ValueError("Review cited evidence that was not supplied.")
        if evidence_id in evidence_ids:
            raise ValueError("Review cited duplicate evidence IDs.")
        evidence_ids.append(evidence_id)
    if normalized_status == "verified" and not evidence_ids:
        raise ValueError("A verified judgment must cite its supporting evidence.")
    return CompletionVerdict(normalized_status, reason.strip(), tuple(evidence_ids), digest)


class CompletionVerifier:
    """Review a frozen objective with a separate context and a bounded budget."""

    def __init__(
        self, runtime: LLMRuntime, objective: str, max_attempts: int = 2,
    ) -> None:
        if not objective.strip():
            raise ValueError("Completion review requires an objective.")
        if max_attempts < 0 or max_attempts > 2:
            raise ValueError("Completion review permits at most two attempts.")
        self._runtime = runtime
        self._objective = objective
        self._max_attempts = max_attempts
        self._attempts = 0
        self.usage: LLMUsage | None = None
        self.round_usages: list[LLMUsage] = []

    @property
    def objective(self) -> str:
        return self._objective

    @property
    def attempts(self) -> int:
        return self._attempts

    @property
    def max_attempts(self) -> int:
        return self._max_attempts

    async def verify(
        self, candidate: str, messages: list[dict[str, Any]],
    ) -> CompletionVerdict:
        """Judge only observed results; this method cannot read files or call tools."""
        try:
            evidence = _project_evidence(messages)
            payload = json.dumps({
                "objective": self._objective,
                "candidate": {"id": "candidate", "content": candidate},
                "evidence": evidence,
            }, sort_keys=True, separators=(",", ":"))
            digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        except (TypeError, ValueError):
            # Failed evidence is never sent to the model, but its rejection still
            # needs an identity for the task's audit record.
            digest = hashlib.sha256(
                repr((self._objective, candidate, messages)).encode("utf-8", errors="backslashreplace")
            ).hexdigest()
            if self._attempts >= self._max_attempts:
                return CompletionVerdict("exhausted", "Completion review budget exhausted.", evidence_digest=digest)
            self._attempts += 1
            return CompletionVerdict(
                "blocked", "Completion evidence could not be validated.", evidence_digest=digest,
            )
        if self._attempts >= self._max_attempts:
            return CompletionVerdict("exhausted", "Completion review budget exhausted.", evidence_digest=digest)
        self._attempts += 1
        if not candidate.strip():
            return CompletionVerdict("blocked", "No candidate result was supplied.", evidence_digest=digest)
        if len(payload) > _MAX_EVIDENCE_CHARS:
            return CompletionVerdict(
                "blocked", "Completion evidence exceeds the review budget; provide a smaller verified result.",
                evidence_digest=digest,
            )
        allowed_ids = {"candidate"}
        allowed_ids.update(str(item["id"]) for item in evidence)
        review_messages: list[dict[str, Any]] = [
            {"role": "system", "content": render_template("agent/completion_review.md", strip=True)},
            {"role": "user", "content": payload},
        ]
        try:
            async with asyncio.timeout(_REVIEW_TIMEOUT_SECONDS) as deadline:
                # The provider's observer records physical calls, including retries.
                # Keep this request independent of the builder's conversation state.
                response = await self._runtime.provider.chat_with_retry(
                    messages=review_messages,
                    tools=None,
                    model=self._runtime.model,
                    max_tokens=min(self._runtime.generation.max_tokens, _MAX_REVIEW_TOKENS),
                    temperature=0,
                    reasoning_effort=self._runtime.generation.reasoning_effort,
                    provider_context=ProviderCallContext(
                        context_window_tokens=self._runtime.context_window_tokens,
                    ),
                )
        except Exception as exc:
            self._record_usage(LLMUsage.empty_request())
            return CompletionVerdict(
                "blocked", f"Completion review unavailable ({type(exc).__name__}).", evidence_digest=digest,
            )
        usage = self._response_usage(review_messages, response)
        self._record_usage(usage)
        if deadline.expired():
            return CompletionVerdict(
                "blocked", "Completion review timed out.", evidence_digest=digest,
            )
        if response.finish_reason != "stop" or response.has_tool_calls:
            return CompletionVerdict(
                "blocked", "Completion reviewer did not return a complete judgment.", evidence_digest=digest,
            )
        try:
            return _parse_verdict(response.content, allowed_ids, digest)
        except (TypeError, ValueError):
            return CompletionVerdict(
                "blocked", "Completion reviewer returned an invalid judgment.", evidence_digest=digest,
            )

    def _record_usage(self, usage: LLMUsage) -> None:
        self.usage = usage if self.usage is None else self.usage + usage
        self.round_usages.append(usage)

    def _response_usage(
        self, messages: list[dict[str, Any]], response: LLMResponse,
    ) -> LLMUsage:
        usage = response.usage
        if usage is None or usage.total_tokens == 0:
            if response.finish_reason == "error":
                usage = LLMUsage.empty_request()
            else:
                input_tokens, _ = estimate_prompt_tokens_chain(
                    self._runtime.provider, self._runtime.model, messages,
                )
                usage = LLMUsage.estimated(
                    input_tokens=max(0, input_tokens),
                    output_tokens=estimate_message_tokens(build_assistant_message(
                        response.content or "",
                        tool_calls=[call.to_openai_tool_call() for call in response.tool_calls],
                        reasoning_content=response.reasoning_content,
                        thinking_blocks=response.thinking_blocks,
                    )),
                )
        return usage.with_timing(generation_ms=response.generation_ms, ttft_ms=response.ttft_ms)
