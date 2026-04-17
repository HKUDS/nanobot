"""SkillReviewService: post-task background review that creates/patches skills."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.runner import AgentRunSpec, AgentRunner
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.utils.prompt_templates import render_template

if TYPE_CHECKING:
    from nanobot.agent.skill_evo.skill_store import SkillStore
    from nanobot.agent.skills import SkillsLoader
    from nanobot.config.schema import SkillsConfig
    from nanobot.providers.base import LLMProvider


# Timeout for review to prevent hanging the main conversation
_REVIEW_TIMEOUT_SECONDS = 60


class SkillReviewService:
    """Runs a lightweight review agent after each qualifying turn.

    Follows the Hermes pattern: fork a minimal AgentRunner with only
    skill tools, feed it the conversation snapshot + a review prompt,
    and let it decide whether to create/patch skills.
    """

    def __init__(
        self,
        provider: LLMProvider,
        model: str,
        store: SkillStore,
        catalog: SkillsLoader,
        config: SkillsConfig,
    ) -> None:
        self._provider = provider
        self._model = config.review_model_override or model
        self._store = store
        self._catalog = catalog
        self._config = config
        # Don't create a shared runner; instantiate a fresh one per review

    def _build_tools(
        self,
        *,
        allow_create: bool | None = None,
        allow_patch: bool | None = None,
    ) -> ToolRegistry:
        from nanobot.agent.tools.skills import SkillManageTool, SkillsListTool, SkillViewTool

        tools = ToolRegistry()
        tools.register(SkillsListTool(catalog=self._catalog))
        tools.register(SkillViewTool(catalog=self._catalog))

        from nanobot.config.schema import SkillsConfig
        effective = SkillsConfig(
            allow_create=allow_create if allow_create is not None else self._config.allow_create,
            allow_patch=allow_patch if allow_patch is not None else self._config.allow_patch,
            allow_delete=False,
            guard_enabled=self._config.guard_enabled,
        )
        tools.register(SkillManageTool(
            store=self._store,
            catalog=self._catalog,
            config=effective,
        ))
        return tools

    def _build_metadata_header(
        self,
        tool_call_count: int,
        iteration_count: int,
        tools_used: list[str],
    ) -> str:
        """Build a metadata block so the review agent has quantitative context."""
        has_errors = any(t in tools_used for t in ("exec",)) and iteration_count > 2
        lines = [
            "## Conversation Metadata",
            f"- Tool calls: {tool_call_count}",
            f"- Agent iterations: {iteration_count}",
            f"- Tools used: {', '.join(tools_used) if tools_used else 'none'}",
        ]
        if has_errors:
            lines.append("- Note: Multiple iterations suggest trial-and-error or error recovery occurred")

        usage_stats = self._store.get_usage_summary()
        if usage_stats:
            lines.append("")
            lines.append("## Existing Workspace Skills (usage stats)")
            for s in sorted(usage_stats, key=lambda x: x.get("usage_count", 0), reverse=True):
                uc = s.get("usage_count", 0)
                lines.append(f"- {s['name']}: used {uc} times, by {s.get('created_by', '?')}")
        return "\n".join(lines)

    async def review_turn(
        self,
        messages: list[dict[str, Any]],
        session_key: str,
        *,
        tool_call_count: int = 0,
        iteration_count: int = 0,
        tools_used: list[str] | None = None,
    ) -> list[dict[str, str]]:
        """Run a background review on the conversation snapshot.

        Returns list of skill actions taken (for notification).
        Failures are logged but never propagated.
        Includes timeout protection to prevent hanging.
        """
        try:
            self._store.set_session_key(f"review:{session_key}")
            # Wrap the review in a timeout to prevent hanging indefinitely
            return await asyncio.wait_for(
                self._run_review(
                    messages,
                    tool_call_count=tool_call_count,
                    iteration_count=iteration_count,
                    tools_used=tools_used or [],
                ),
                timeout=_REVIEW_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Skill review timed out after {}s for session {}",
                _REVIEW_TIMEOUT_SECONDS, session_key,
            )
            return []
        except Exception:
            logger.opt(exception=True).warning("Skill review failed (non-fatal)")
            return []

    async def _run_review(
        self,
        messages: list[dict[str, Any]],
        *,
        tool_call_count: int = 0,
        iteration_count: int = 0,
        tools_used: list[str] | None = None,
    ) -> list[dict[str, str]]:
        review_prompt = render_template("agent/skill_review.md", strip=True)

        conversation_text = self._summarize_conversation(messages)
        if not conversation_text.strip():
            logger.debug("Skill review: empty conversation, skipping")
            return []

        metadata_header = self._build_metadata_header(
            tool_call_count, iteration_count, tools_used or [],
        )
        user_content = f"{metadata_header}\n\n{conversation_text}" if metadata_header else conversation_text

        tools = self._build_tools()
        review_mode = self._config.review_mode
        if review_mode == "auto_patch":
            tools = self._build_tools(allow_create=False)
        elif review_mode == "suggest":
            tools = self._build_tools(allow_create=False, allow_patch=False)

        review_messages: list[dict[str, Any]] = [
            {"role": "system", "content": review_prompt},
            {"role": "user", "content": user_content},
        ]

        # Create a fresh, isolated AgentRunner for each review to avoid
        # sharing state with the main conversation agent
        runner = AgentRunner(self._provider)
        
        result = await runner.run(AgentRunSpec(
            initial_messages=review_messages,
            tools=tools,
            model=self._model,
            max_iterations=self._config.review_max_iterations,
            max_tool_result_chars=8_000,
            fail_on_tool_error=False,
        ))

        actions: list[dict[str, str]] = []
        if result.tool_events:
            for ev in result.tool_events:
                logger.info(
                    "Skill review action: name={}, status={}, detail={}",
                    ev.get("name"), ev.get("status"), ev.get("detail", "")[:200],
                )
                if ev.get("name") == "skill_manage" and ev.get("status") == "ok":
                    try:
                        import json as _json
                        detail = _json.loads(ev.get("detail", "{}"))
                        if detail.get("success"):
                            actions.append({
                                "action": detail.get("action", "unknown"),
                                "skill": detail.get("name", "unknown"),
                            })
                    except (ValueError, TypeError):
                        pass
        else:
            logger.debug(
                "Skill review: no actions taken (stop_reason={}, response={})",
                result.stop_reason, (result.final_content or "")[:300],
            )
        return actions

    @staticmethod
    def _summarize_conversation(messages: list[dict[str, Any]]) -> str:
        """Build a text summary of the conversation for the review agent.

        Skips the system prompt to avoid confusing the review agent about
        its own role. Adds clear delimiters between messages.
        """
        parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "unknown")
            if role == "system":
                continue
            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = [
                    b.get("text", "") for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                content = "\n".join(text_parts)
            if not content:
                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    names = [
                        (tc.get("function") or {}).get("name", "?")
                        for tc in tool_calls
                        if isinstance(tc, dict)
                    ]
                    content = f"[tool calls: {', '.join(names)}]"
            if content:
                label = {"user": "USER", "assistant": "ASSISTANT", "tool": "TOOL_RESULT"}.get(role, role.upper())
                parts.append(f"--- {label} ---\n{content[:2000]}")
        return "\n\n".join(parts)
