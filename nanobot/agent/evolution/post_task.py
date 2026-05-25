"""PostTask skill creation: trigger gates and LLM-driven create decisions."""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from loguru import logger

from nanobot.agent.evolution.models import ToolCallRecord, TurnTrace
from nanobot.agent.evolution.proposals import (
    PostTaskCreateResult,
    ProposalStore,
    SKIP_ACTIVE_SKILL_EXISTS,
    normalize_skill_md_content,
    validate_skill_md,
)
from nanobot.config.schema import EvolutionConfig
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.utils.prompt_templates import render_template

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_UPDATE_ACTIONS = frozenset({"update_skill", "update", "modify_skill", "modify"})

POST_TASK_LLM_TIMEOUT_S = 120.0
POST_TASK_LLM_MAX_TOKENS = 2048  # small JSON; 512 can truncate on reasoning models (finish_reason=length)
POST_TASK_SKILL_LLM_MAX_TOKENS = 4096
_TRUNCATED_FINISH_REASONS = frozenset({"length", "max_tokens"})

PostTaskAction = Literal["none", "create_skill"]

# Human-readable skip reasons returned by ``should_trigger`` (None = proceed).
SKIP_EVOLUTION_DISABLED = "evolution disabled"
SKIP_TOOL_CALLS_LOW = "tool_call_count below min_tool_calls"
SKIP_OUTCOME = "outcome not success"
SKIP_STOP_REASON = "stop_reason not completed"
SKIP_NO_TOOL_CALLS = "no tool calls recorded"
SKIP_SUBAGENT = "subagent turn"
SKIP_COOLDOWN = "session cooldown active"


@dataclass(frozen=True, slots=True)
class PostTaskDecision:
    """LLM verdict on whether to create a new skill from a turn trace."""

    action: PostTaskAction = "none"
    skill_name: str = ""
    rationale: str = ""
    confidence: float = 0.0
    parsed: bool = False  # True when model output was valid JSON (even if action is none)

    @classmethod
    def none(
        cls,
        *,
        rationale: str = "",
        confidence: float = 0.0,
        parsed: bool = False,
    ) -> PostTaskDecision:
        return cls(
            action="none",
            rationale=rationale,
            confidence=confidence,
            parsed=parsed,
        )


@dataclass(frozen=True, slots=True)
class PostTaskGateResult:
    """Outcome of PostTask trigger gate evaluation."""

    should_run: bool
    skip_reason: str = ""

    @classmethod
    def allow(cls) -> PostTaskGateResult:
        return cls(should_run=True)

    @classmethod
    def skip(cls, reason: str) -> PostTaskGateResult:
        return cls(should_run=False, skip_reason=reason)


class PostTaskCooldownStore:
    """Persist last PostTask run time per session under ``{workspace}/.nanobot/``."""

    def __init__(self, workspace: Path) -> None:
        self._path = workspace.expanduser().resolve() / ".nanobot" / "post_task_cooldown.json"
        self._memory: dict[str, float] = {}
        self._loaded = False

    # 检查 session_key 是否还在冷却窗口内 (cooldown_minutes)
    def is_active(self, session_key: str, cooldown_minutes: int) -> bool:
        """Return True when *session_key* is still inside the cooldown window."""
        if cooldown_minutes <= 0:
            return False
        last = self._read().get(session_key)
        if last is None:
            return False
        return (time.time() - last) < cooldown_minutes * 60

    def mark(self, session_key: str) -> None:
        """Record that PostTask ran for *session_key* now."""
        data = self._read()
        data[session_key] = time.time()
        self._write(data)

    def _read(self) -> dict[str, float]:
        if self._loaded:
            return dict(self._memory)
        if not self._path.exists():
            self._loaded = True
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("PostTask cooldown file unreadable ({}): {}", self._path, exc)
            self._loaded = True
            return {}
        if not isinstance(raw, dict):
            self._loaded = True
            return {}
        memory: dict[str, float] = {}
        for key, value in raw.items():
            try:
                memory[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
        self._memory = memory
        self._loaded = True
        return dict(self._memory)

    def _write(self, data: dict[str, float]) -> None:
        self._memory = dict(data)
        self._loaded = True
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def format_tool_calls_for_prompt(tool_calls: tuple[ToolCallRecord, ...]) -> str:
    """Render tool call records for the PostTask LLM prompt."""
    if not tool_calls:
        return "(none)"
    lines: list[str] = []
    for index, call in enumerate(tool_calls, start=1):
        status = "ok" if call.ok else "error"
        summary = call.args_summary or "(no args)"
        lines.append(f"{index}. {call.name} [{status}] {summary}")
    return "\n".join(lines)


def format_skills_injected(skills: tuple[str, ...]) -> str:
    if not skills:
        return "(none)"
    return ", ".join(skills)


def _parse_confidence(raw: object) -> float | None:
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value < 0.0 or value > 1.0:
        return None
    return value


def _normalize_action(raw: object) -> str:
    if not isinstance(raw, str):
        return ""
    return raw.strip().lower().replace("-", "_")


def _normalize_skill_name(raw: object) -> str:
    if not isinstance(raw, str):
        return ""
    name = raw.strip().lower().replace("_", "-")
    while "--" in name:
        name = name.replace("--", "-")
    return name.strip("-")


def parse_post_task_response(
    content: str | None,
    *,
    min_confidence: float,
) -> PostTaskDecision:
    """Parse PostTask JSON from model output and apply hard post-rules."""
    if not content:
        return PostTaskDecision.none()

    text = _JSON_FENCE_RE.sub("", content.strip()).strip()
    data: object
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_OBJECT_RE.search(text)
        if not match:
            return PostTaskDecision.none()
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            return PostTaskDecision.none()

    if not isinstance(data, dict):
        return PostTaskDecision.none()

    action = _normalize_action(data.get("action"))
    rationale = str(data.get("rationale") or "").strip()
    confidence = _parse_confidence(data.get("confidence"))
    if confidence is None:
        confidence = 0.0

    if action in _UPDATE_ACTIONS:
        logger.info("PostTask LLM requested update; deferred to GEPA")
        return PostTaskDecision.none(
            rationale="update deferred to GEPA",
            confidence=confidence,
            parsed=True,
        )

    if action != "create_skill":
        return PostTaskDecision.none(rationale=rationale, confidence=confidence, parsed=True)

    skill_name = _normalize_skill_name(data.get("skill_name"))
    if not skill_name or not _SKILL_NAME_RE.fullmatch(skill_name):
        return PostTaskDecision.none(rationale=rationale, confidence=confidence, parsed=True)

    if confidence < min_confidence:
        logger.info(
            "PostTask confidence {:.2f} below min {:.2f}; skipping create",
            confidence,
            min_confidence,
        )
        return PostTaskDecision.none(rationale=rationale, confidence=confidence, parsed=True)

    return PostTaskDecision(
        action="create_skill",
        skill_name=skill_name,
        rationale=rationale,
        confidence=confidence,
        parsed=True,
    )


def resolve_post_task_provider(
    config: Any,
    evolution: EvolutionConfig,
    fallback_provider: LLMProvider,
) -> LLMProvider:
    """Return the LLM provider used for PostTask decisions."""
    model = evolution.post_task.model
    if model:
        from nanobot.providers.factory import make_provider

        try:
            return make_provider(config, model=model)
        except Exception as exc:
            logger.warning(
                "Failed to create PostTask model {!r}: {}; using fallback provider",
                model,
                exc,
            )
    return fallback_provider


class PostTaskEvolver:
    """Turn-boundary skill creation (E1): gates + LLM create decision."""

    def __init__(
        self,
        workspace: Path,
        config: EvolutionConfig,
        provider: LLMProvider | None = None,
        *,
        cooldown_store: PostTaskCooldownStore | None = None,
        proposal_store: ProposalStore | None = None,
        llm_timeout_s: float | None = None,
        llm_max_tokens: int = POST_TASK_LLM_MAX_TOKENS,
        skill_llm_max_tokens: int = POST_TASK_SKILL_LLM_MAX_TOKENS,
    ) -> None:
        self._workspace = workspace.expanduser().resolve()
        self._config = config
        self._provider = provider
        self._cooldown = cooldown_store or PostTaskCooldownStore(self._workspace)
        self._proposals = proposal_store or ProposalStore(self._workspace)
        self._llm_timeout_s = (
            llm_timeout_s if llm_timeout_s is not None else config.post_task.llm_timeout_s
        )
        self._llm_max_tokens = llm_max_tokens
        self._skill_llm_max_tokens = skill_llm_max_tokens

    @property
    def cooldown_store(self) -> PostTaskCooldownStore:
        return self._cooldown

    @property
    def proposal_store(self) -> ProposalStore:
        return self._proposals

    def evaluate_gate(self, trace: TurnTrace, *, is_subagent: bool) -> PostTaskGateResult:
        """Return whether PostTask should run for *trace*."""
        reason = self.should_trigger(trace, is_subagent=is_subagent)
        if reason is None:
            return PostTaskGateResult.allow()
        return PostTaskGateResult.skip(reason)

    def should_trigger(self, trace: TurnTrace, *, is_subagent: bool) -> str | None:
        """Return a skip reason string, or ``None`` when all gates pass."""
        if not self._config.post_task_enabled():
            return SKIP_EVOLUTION_DISABLED

        if is_subagent:
            return SKIP_SUBAGENT

        post_task = self._config.post_task

        if trace.tool_call_count < post_task.min_tool_calls:
            return SKIP_TOOL_CALLS_LOW

        if not trace.tool_calls:
            return SKIP_NO_TOOL_CALLS

        if trace.outcome != "success":
            return SKIP_OUTCOME

        if trace.stop_reason != "completed":
            return SKIP_STOP_REASON

        if self._cooldown.is_active(trace.session_key, post_task.cooldown_minutes):
            return SKIP_COOLDOWN

        return None

    async def decide(self, trace: TurnTrace) -> PostTaskDecision:
        """Ask the LLM whether to create a skill from *trace* (Step 2)."""
        if self._provider is None:
            logger.warning("PostTask decide skipped: no LLM provider configured")
            return PostTaskDecision.none()

        post_task = self._config.post_task
        user_prompt = render_template(
            "agent/evolution_post_task.md",
            query=trace.query.strip() or "(empty)",
            skills_injected=format_skills_injected(trace.skills_injected),
            tool_call_count=trace.tool_call_count,
            iterations=trace.iterations,
            tool_calls=format_tool_calls_for_prompt(trace.tool_calls),
        )
        messages = [
            {
                "role": "system",
                "content": "You are a skill evolution router. Output valid JSON only.",
            },
            {"role": "user", "content": user_prompt},
        ]
        model = post_task.model

        logger.info(
            "PostTask decide [start]: trace_id={} session={} model={} tool_calls={} timeout={}s",
            trace.trace_id,
            trace.session_key,
            model or "(provider default)",
            trace.tool_call_count,
            self._llm_timeout_s,
        )

        max_tokens = self._llm_max_tokens
        response = await self._chat_post_task_decide(
            messages=messages,
            model=model,
            max_tokens=max_tokens,
        )
        if response is None:
            return PostTaskDecision.none()

        if response.finish_reason == "error":
            logger.warning("PostTask LLM provider error: {}", response.content)
            return PostTaskDecision.none()

        raw_content = response.content or ""
        if (
            response.finish_reason in _TRUNCATED_FINISH_REASONS
            and not raw_content.strip()
        ):
            logger.warning(
                "PostTask decide truncated with empty body (max_tokens={}); retrying",
                max_tokens,
            )
            response = await self._chat_post_task_decide(
                messages=messages,
                model=model,
                max_tokens=min(max_tokens * 4, 4096),
            )
            if response is None:
                return PostTaskDecision.none()
            raw_content = response.content or ""

        logger.info(
            "PostTask decide [response]: finish_reason={} has_content={} content={!r}",
            response.finish_reason,
            bool(raw_content.strip()),
            raw_content[:500],
        )

        if response.finish_reason in _TRUNCATED_FINISH_REASONS and not parse_post_task_response(
            raw_content,
            min_confidence=0.0,
        ).parsed:
            logger.warning(
                "PostTask decide still truncated/unparseable after retry (finish_reason={})",
                response.finish_reason,
            )

        decision = parse_post_task_response(
            raw_content,
            min_confidence=post_task.min_confidence,
        )
        logger.info(
            "PostTask decide [done]: action={} skill_name={!r} confidence={:.2f} "
            "parsed={} rationale={!r}",
            decision.action,
            decision.skill_name,
            decision.confidence,
            decision.parsed,
            (decision.rationale or "")[:200],
        )
        return decision

    async def _chat_post_task_decide(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None,
        max_tokens: int,
    ) -> LLMResponse | None:
        """Call the decide LLM; return ``None`` on timeout/error."""
        if self._provider is None:
            return None
        try:
            async with asyncio.timeout(self._llm_timeout_s):
                return await self._provider.chat_with_retry(
                    messages=messages,
                    model=model,
                    max_tokens=max_tokens,
                    temperature=0,
                    retry_mode="standard",
                )
        except TimeoutError:
            logger.warning("PostTask LLM decision timed out after {}s", self._llm_timeout_s)
            return None
        except Exception as exc:
            logger.warning("PostTask LLM decision failed: {}", exc)
            return None

    async def generate_skill_content(
        self,
        trace: TurnTrace,
        decision: PostTaskDecision,
    ) -> str | None:
        """Ask the LLM to draft SKILL.md body for *decision.skill_name*."""
        if self._provider is None:
            logger.warning("PostTask skill generation skipped: no LLM provider")
            return None

        post_task = self._config.post_task
        model = post_task.model
        logger.info(
            "PostTask skill-gen [start]: skill={!r} model={}",
            decision.skill_name,
            model or "(provider default)",
        )

        existing = self._proposals.list_workspace_skill_summaries()
        existing_text = "\n".join(f"- {line}" for line in existing) if existing else "(none)"

        user_prompt = render_template(
            "agent/evolution_post_task_skill.md",
            skill_name=decision.skill_name,
            rationale=decision.rationale or "(none)",
            query=trace.query.strip() or "(empty)",
            skills_injected=format_skills_injected(trace.skills_injected),
            tool_calls=format_tool_calls_for_prompt(trace.tool_calls),
            existing_skills=existing_text,
        )
        messages = [
            {
                "role": "system",
                "content": "You write agent SKILL.md files. Output markdown only.",
            },
            {"role": "user", "content": user_prompt},
        ]

        max_tokens = self._skill_llm_max_tokens
        response = await self._chat_post_task_decide(
            messages=messages,
            model=model,
            max_tokens=max_tokens,
        )
        if response is None:
            return None

        if response.finish_reason == "error":
            logger.warning("PostTask skill generation provider error: {}", response.content)
            return None

        raw_content = response.content or ""
        if (
            response.finish_reason in _TRUNCATED_FINISH_REASONS
            and not raw_content.strip()
        ):
            logger.warning(
                "PostTask skill-gen truncated with empty body (max_tokens={}); retrying",
                max_tokens,
            )
            response = await self._chat_post_task_decide(
                messages=messages,
                model=model,
                max_tokens=min(max_tokens * 2, 8192),
            )
            if response is None:
                return None
            raw_content = response.content or ""

        logger.info(
            "PostTask skill-gen [response]: finish_reason={} has_content={} chars={}",
            response.finish_reason,
            bool(raw_content.strip()),
            len(raw_content),
        )

        skill_md = normalize_skill_md_content(raw_content)
        if not skill_md:
            logger.warning("PostTask skill-gen produced empty content after normalize")
            return None
        return skill_md

    async def create_proposal(
        self,
        trace: TurnTrace,
        decision: PostTaskDecision,
    ) -> PostTaskCreateResult:
        """Generate SKILL.md and write proposal or auto-applied workspace skill."""
        if decision.action != "create_skill" or not decision.skill_name:
            return PostTaskCreateResult.skipped("not a create_skill decision")

        skill_name = decision.skill_name
        logger.info("PostTask create [start]: skill={!r}", skill_name)

        dedup_reason = self._proposals.check_dedup(skill_name)
        if dedup_reason:
            logger.info("PostTask create skipped (dedup): {} for {!r}", dedup_reason, skill_name)
            return PostTaskCreateResult.skipped(dedup_reason, skill_name=skill_name)

        skill_md = await self.generate_skill_content(trace, decision)
        if not skill_md:
            logger.warning("PostTask create skipped for {!r}: skill generation failed", skill_name)
            return PostTaskCreateResult.skipped("skill generation failed", skill_name=skill_name)

        validation_error = validate_skill_md(skill_md, skill_name=skill_name)
        if validation_error:
            logger.warning(
                "PostTask skill validation failed for {!r}: {} (preview={!r})",
                skill_name,
                validation_error,
                skill_md[:300],
            )
            return PostTaskCreateResult.skipped(validation_error, skill_name=skill_name)

        post_task = self._config.post_task
        if post_task.auto_apply:
            try:
                skill_path = self._proposals.write_active_skill(skill_name, skill_md)
            except FileExistsError:
                return PostTaskCreateResult.skipped(
                    SKIP_ACTIVE_SKILL_EXISTS,
                    skill_name=skill_name,
                )
            except OSError as exc:
                logger.warning("PostTask auto_apply write failed: {}", exc)
                return PostTaskCreateResult.skipped("write failed", skill_name=skill_name)
            from nanobot.agent.evolution.git_store import EvolutionGitStore

            EvolutionGitStore(self._workspace).commit_create(skill_name)
            rel = skill_path.relative_to(self._workspace).as_posix()
            return PostTaskCreateResult.ok(
                skill_name=skill_name,
                skill_path=rel,
                auto_applied=True,
            )

        try:
            proposal_id = self._proposals.write_proposal(
                skill_name=skill_name,
                skill_md=skill_md,
                trace_id=trace.trace_id,
                rationale=decision.rationale,
                confidence=decision.confidence,
            )
        except FileExistsError:
            return PostTaskCreateResult.skipped("proposal id collision", skill_name=skill_name)
        except OSError as exc:
            logger.warning("PostTask proposal write failed: {}", exc)
            return PostTaskCreateResult.skipped("write failed", skill_name=skill_name)

        rel = f"skills/.proposals/{proposal_id}/SKILL.md"
        return PostTaskCreateResult.ok(
            skill_name=skill_name,
            skill_path=rel,
            proposal_id=proposal_id,
            auto_applied=False,
        )
