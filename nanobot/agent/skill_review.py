"""SkillReviewService: post-task background review that creates/patches skills."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.runner import AgentRunSpec, AgentRunner
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.utils.prompt_templates import render_template

if TYPE_CHECKING:
    from nanobot.agent.skill_store import SkillStore
    from nanobot.agent.skills import SkillsLoader
    from nanobot.config.schema import SkillsConfig
    from nanobot.providers.base import LLMProvider


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
        self._runner = AgentRunner(provider)

    def _build_tools(self) -> ToolRegistry:
        from nanobot.agent.tools.skills import SkillManageTool, SkillsListTool, SkillViewTool

        tools = ToolRegistry()
        tools.register(SkillsListTool(catalog=self._catalog))
        tools.register(SkillViewTool(catalog=self._catalog))
        tools.register(SkillManageTool(
            store=self._store,
            catalog=self._catalog,
            config=self._config,
        ))
        return tools

    async def review_turn(
        self,
        messages: list[dict[str, Any]],
        session_key: str,
    ) -> None:
        """Run a background review on the conversation snapshot.

        Failures are logged but never propagated.
        """
        try:
            self._store.set_session_key(f"review:{session_key}")
            await self._run_review(messages)
        except Exception:
            logger.opt(exception=True).warning("Skill review failed (non-fatal)")

    async def _run_review(self, messages: list[dict[str, Any]]) -> None:
        review_prompt = render_template("agent/skill_review.md", strip=True)

        conversation_text = self._summarize_conversation(messages)
        if not conversation_text.strip():
            logger.debug("Skill review: empty conversation, skipping")
            return

        tools = self._build_tools()
        review_messages: list[dict[str, Any]] = [
            {"role": "system", "content": review_prompt},
            {"role": "user", "content": conversation_text},
        ]

        result = await self._runner.run(AgentRunSpec(
            initial_messages=review_messages,
            tools=tools,
            model=self._model,
            max_iterations=self._config.review_max_iterations,
            max_tool_result_chars=8_000,
            fail_on_tool_error=False,
        ))

        if result.tool_events:
            for ev in result.tool_events:
                logger.info(
                    "Skill review action: name={}, status={}, detail={}",
                    ev.get("name"), ev.get("status"), ev.get("detail", "")[:200],
                )
        else:
            logger.debug("Skill review: no actions taken (stop_reason={})", result.stop_reason)

    @staticmethod
    def _summarize_conversation(messages: list[dict[str, Any]]) -> str:
        """Build a text summary of the conversation for the review agent."""
        parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "unknown")
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
                parts.append(f"[{role}] {content[:2000]}")
        return "\n\n".join(parts)
