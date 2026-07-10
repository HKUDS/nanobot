"""Task-based per-turn model routing."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import json_repair
from loguru import logger

from nanobot.agent.model_presets import PresetSnapshotLoader
from nanobot.config.schema import (
    DreamConfig,
    ModelPresetConfig,
    ModelRouteRule,
    ModelRoutingConfig,
    TaskComplexity,
    TaskKind,
    TaskType,
)
from nanobot.providers.factory import ProviderSnapshot
from nanobot.session.goal_state import sustained_goal_turn

_CLASSIFIER_MAX_TOKENS = 128
_USER_TEXT_MAX_CHARS = 2000

_CLASSIFIER_SYSTEM = """You classify user requests for model routing.
Output JSON only with this shape:
{"task_type":"coding|research|admin|chat|other","complexity":"low|medium|high","reason":"brief"}

Guidelines:
- coding: implementation, debugging, refactors, shell automation, multi-file changes
- research: exploration, comparisons, reading docs or URLs, analysis
- admin: scheduling, configuration, reminders, lightweight operational tasks
- chat: simple Q&A, greetings, short explanations
- other: anything that does not fit above
- low: quick, single-step, or conversational
- medium: moderate scope, a few steps or files
- high: large, ambiguous, or multi-step work
"""

BuildInlineSnapshot = Callable[[ModelPresetConfig], ProviderSnapshot]


@dataclass(slots=True)
class RoutingContext:
    """Inputs used to resolve a per-turn model route."""

    user_text: str
    task_kind: TaskKind
    task_type: TaskType | None = None
    complexity: TaskComplexity | None = None
    session_metadata: dict[str, Any] | None = None
    message_metadata: dict[str, Any] | None = None
    session_key: str | None = None


@dataclass(slots=True)
class TurnRoute:
    """Resolved ephemeral model route for one agent run."""

    snapshot: ProviderSnapshot
    preset_name: str
    preset: ModelPresetConfig
    task_kind: TaskKind
    task_type: TaskType | None = None
    complexity: TaskComplexity | None = None

    def to_run_spec_kwargs(self) -> dict[str, Any]:
        return {
            "model": self.snapshot.model,
            "route_provider": self.snapshot.provider,
            "routed_preset": self.preset_name,
            "temperature": self.preset.temperature,
            "max_tokens": self.preset.max_tokens,
            "reasoning_effort": self.preset.reasoning_effort,
            "context_window_tokens": self.snapshot.context_window_tokens,
        }


def infer_task_kind(
    *,
    session_key: str | None,
    session_metadata: dict[str, Any] | None,
    message_metadata: dict[str, Any] | None,
    explicit_task_kind: TaskKind | None = None,
) -> TaskKind:
    if explicit_task_kind is not None:
        return explicit_task_kind
    key = (session_key or "").strip()
    if key.startswith("dream:"):
        return "dream"
    if key == "heartbeat" or key.startswith("cron:"):
        return "cron"
    if sustained_goal_turn(session_metadata, message_metadata=message_metadata):
        return "sustained_goal"
    return "chat"


def extract_user_text(initial_messages: list[dict[str, Any]]) -> str:
    for message in reversed(initial_messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
            if parts:
                return "\n".join(parts)
    return ""


def _truncate_user_text(text: str) -> str:
    text = text.strip()
    if len(text) <= _USER_TEXT_MAX_CHARS:
        return text
    return text[:_USER_TEXT_MAX_CHARS] + "…"


def _parse_classifier_response(content: str | None) -> tuple[TaskType | None, TaskComplexity | None]:
    if not content:
        return None, None
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        try:
            parsed = json_repair.loads(stripped)
        except Exception:
            return None, None
    if not isinstance(parsed, dict):
        return None, None

    task_type = parsed.get("task_type")
    complexity = parsed.get("complexity")
    valid_types = {"coding", "research", "admin", "chat", "other"}
    valid_complexity = {"low", "medium", "high"}
    resolved_type = task_type if task_type in valid_types else None
    resolved_complexity = complexity if complexity in valid_complexity else None
    return resolved_type, resolved_complexity


def _rule_matches(ctx: RoutingContext, rule: ModelRouteRule) -> bool:
    match = rule.match
    if match.task_kind is not None and ctx.task_kind != match.task_kind:
        return False
    if match.task_type is not None and ctx.task_type != match.task_type:
        return False
    if match.complexity is not None and ctx.complexity != match.complexity:
        return False
    return True


class ModelRouter:
    """Resolve per-turn model presets from task context."""

    def __init__(
        self,
        *,
        routing: ModelRoutingConfig,
        dream: DreamConfig,
        load_preset: PresetSnapshotLoader,
        build_inline_snapshot: BuildInlineSnapshot,
        resolve_preset: Callable[[str], ModelPresetConfig],
    ) -> None:
        self._routing = routing
        self._dream = dream
        self._load_preset = load_preset
        self._build_inline_snapshot = build_inline_snapshot
        self._resolve_preset = resolve_preset
        self._classifier_snapshot: ProviderSnapshot | None = None
        self._classifier_signature: tuple[object, ...] | None = None

    @property
    def enabled(self) -> bool:
        return self._routing.enabled

    def _refresh_classifier_snapshot(self) -> ProviderSnapshot:
        signature = ("classifier", self._routing.classifier_preset)
        if (
            self._classifier_snapshot is not None
            and self._classifier_signature == signature
        ):
            return self._classifier_snapshot
        snapshot = self._load_preset(self._routing.classifier_preset)
        self._classifier_snapshot = snapshot
        self._classifier_signature = signature
        return snapshot

    def _snapshot_for_preset(self, preset_name: str) -> tuple[ProviderSnapshot, ModelPresetConfig]:
        preset = self._resolve_preset(preset_name)
        snapshot = self._load_preset(preset_name)
        snapshot.provider.generation = preset.to_generation_settings()
        return snapshot, preset

    def _dream_override_snapshot(self) -> ProviderSnapshot | None:
        override = (self._dream.model_override or "").strip()
        if not override:
            return None
        preset = ModelPresetConfig(model=override, provider="auto")
        return self._build_inline_snapshot(preset)

    def _match_rule(self, ctx: RoutingContext) -> str | None:
        for rule in self._routing.rules:
            if _rule_matches(ctx, rule):
                return rule.preset
        return self._routing.default_preset

    async def _classify(self, user_text: str) -> tuple[TaskType | None, TaskComplexity | None]:
        snapshot = self._refresh_classifier_snapshot()
        provider = snapshot.provider
        preset = self._resolve_preset(self._routing.classifier_preset)
        try:
            response = await provider.chat_with_retry(
                model=snapshot.model,
                messages=[
                    {"role": "system", "content": _CLASSIFIER_SYSTEM},
                    {"role": "user", "content": _truncate_user_text(user_text)},
                ],
                tools=None,
                tool_choice=None,
                max_tokens=_CLASSIFIER_MAX_TOKENS,
                temperature=0.0,
            )
        except Exception:
            logger.warning("Model routing classifier call failed")
            return None, None
        if response.finish_reason == "error":
            logger.warning(
                "Model routing classifier returned error: {}",
                (response.content or "")[:200],
            )
            return None, None
        task_type, complexity = _parse_classifier_response(response.content)
        logger.debug(
            "Model routing classifier: task_type={} complexity={} model={}",
            task_type,
            complexity,
            preset.model,
        )
        return task_type, complexity

    async def resolve_turn_route(
        self,
        ctx: RoutingContext,
        *,
        baseline_model: str,
        baseline_preset: str | None,
    ) -> TurnRoute | None:
        if not self._routing.enabled:
            return None

        if ctx.task_kind == "dream":
            override_snapshot = self._dream_override_snapshot()
            if override_snapshot is not None:
                preset = ModelPresetConfig(model=override_snapshot.model, provider="auto")
                return TurnRoute(
                    snapshot=override_snapshot,
                    preset_name="dream:override",
                    preset=preset,
                    task_kind=ctx.task_kind,
                )

        working = RoutingContext(
            user_text=ctx.user_text,
            task_kind=ctx.task_kind,
            task_type=ctx.task_type,
            complexity=ctx.complexity,
            session_metadata=ctx.session_metadata,
            message_metadata=ctx.message_metadata,
            session_key=ctx.session_key,
        )

        if working.task_kind == "chat":
            task_type, complexity = await self._classify(working.user_text)
            working.task_type = task_type
            working.complexity = complexity

        preset_name = self._match_rule(working)
        if preset_name is None:
            return None

        snapshot, preset = self._snapshot_for_preset(preset_name)
        if snapshot.model == baseline_model and preset_name == (baseline_preset or "default"):
            return None

        return TurnRoute(
            snapshot=snapshot,
            preset_name=preset_name,
            preset=preset,
            task_kind=working.task_kind,
            task_type=working.task_type,
            complexity=working.complexity,
        )
