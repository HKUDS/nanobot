"""Extract tool-use strategies from successful guardrail recoveries.

When a guardrail fires (with a strategy_tag) and subsequent tool calls
succeed, the recovery pattern is saved as a reusable strategy for future
sessions.  Strategy extraction is best-effort --- failures never block
the main processing pipeline.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.memory.strategy import Strategy, StrategyStore

if TYPE_CHECKING:
    from nanobot.agent.turn_types import ToolAttempt
    from nanobot.providers.base import LLMProvider


class StrategyExtractor:
    """Extracts and saves tool-use strategies from guardrail recoveries.

    When a guardrail fires (with a strategy_tag) and subsequent tool calls
    succeed, the recovery pattern is saved as a reusable strategy.
    """

    def __init__(
        self,
        store: StrategyStore,
        provider: LLMProvider | None = None,
        model: str = "",
    ) -> None:
        self._store = store
        self._provider = provider
        self._model = model

    async def extract_from_turn(
        self,
        tool_results_log: list[ToolAttempt],
        guardrail_activations: list[dict[str, Any]],
        user_text: str,
    ) -> list[Strategy]:
        """Extract strategies from a completed turn.

        Looks for guardrail activations with strategy_tags where subsequent
        tool calls succeeded.  For each, creates a Strategy and saves it.
        """
        strategies: list[Strategy] = []
        for activation in guardrail_activations:
            tag = activation.get("strategy_tag")
            if not tag:
                continue

            fired_at_iteration: int = activation.get("iteration", 0)

            # Check if any subsequent tool call succeeded with data
            subsequent_successes = [
                r
                for r in tool_results_log
                if r.iteration > fired_at_iteration and r.success and not r.output_empty
            ]
            if not subsequent_successes:
                continue  # Recovery didn't produce useful results

            # Build strategy from the recovery pattern
            strategy = await self._build_strategy(
                activation=activation,
                successful_attempt=subsequent_successes[0],
                user_text=user_text,
            )
            if strategy:
                self._store.save(strategy)
                strategies.append(strategy)
                logger.info(
                    "strategy_extracted | domain={} | task_type={} | tag={}",
                    strategy.domain,
                    strategy.task_type,
                    tag,
                )

        return strategies

    async def _build_strategy(
        self,
        activation: dict[str, Any],
        successful_attempt: ToolAttempt,
        user_text: str,
    ) -> Strategy | None:
        """Build a Strategy from a guardrail recovery."""
        failed_tool = activation.get("failed_tool", "unknown")
        failed_args = activation.get("failed_args", "")

        if self._provider:
            strategy_text = await self._llm_summarize(
                user_text,
                failed_tool,
                str(failed_args),
                successful_attempt.tool_name,
                str(successful_attempt.arguments),
            )
        else:
            strategy_text = (
                f"{failed_tool} did not return results for this type of query. "
                f"Use {successful_attempt.tool_name} instead."
            )

        domain = self._infer_domain(failed_tool, successful_attempt.tool_name)
        task_type = activation.get("strategy_tag", "general")

        strategy_id = hashlib.sha1(
            f"{domain}:{task_type}:{strategy_text[:100]}".encode()
        ).hexdigest()[:12]

        now = datetime.now(timezone.utc)
        return Strategy(
            id=strategy_id,
            domain=domain,
            task_type=task_type,
            strategy=strategy_text,
            context=f"Learned from guardrail recovery: {activation.get('source', 'unknown')}",
            source="guardrail_recovery",
            confidence=0.5,
            created_at=now,
            last_used=now,
            use_count=0,
            success_count=0,
        )

    async def _llm_summarize(
        self,
        user_text: str,
        failed_tool: str,
        failed_args: str,
        success_tool: str,
        success_args: str,
    ) -> str:
        """Use LLM to generate a concise strategy description."""
        assert self._provider is not None
        prompt = (
            "A tool-use strategy was discovered. Summarize it in 1-2 sentences.\n\n"
            f"User task: {user_text[:200]}\n"
            f"Failed: {failed_tool}({failed_args[:100]})\n"
            f"Succeeded: {success_tool}({success_args[:100]})\n\n"
            "Write what doesn't work and what to do instead."
        )
        try:
            response = await self._provider.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self._model or None,
                max_tokens=150,
                temperature=0.3,
            )
            return response.content or f"Use {success_tool} instead of {failed_tool}."
        except Exception:  # crash-barrier: strategy extraction is best-effort
            logger.warning("LLM strategy summarization failed; using fallback")
            return f"Use {success_tool} instead of {failed_tool}."

    @staticmethod
    def _infer_domain(failed_tool: str, success_tool: str) -> str:
        """Infer the domain from tool names."""
        tools = f"{failed_tool} {success_tool}".lower()
        if "obsidian" in tools:
            return "obsidian"
        if "git" in tools or "github" in tools:
            return "github"
        if "web" in tools:
            return "web"
        return "filesystem"

    def update_confidence(
        self,
        strategies_in_context: list[Strategy],
        *,
        had_guardrail_activations: bool,
    ) -> None:
        """Update confidence for strategies that were in context this turn."""
        for s in strategies_in_context:
            if had_guardrail_activations:
                new_conf = max(0.0, s.confidence - 0.05)
            else:
                new_conf = min(1.0, s.confidence + 0.1)
            self._store.update_confidence(s.id, new_conf)
            self._store.record_usage(s.id, success=not had_guardrail_activations)
