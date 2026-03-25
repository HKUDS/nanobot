"""Answer verification via LLM self-critique.

``AnswerVerifier`` implements a self-critique gate that can:

- **Always verify** — run a critique pass on every response.
- **Verify on uncertainty** — only verify when the user asks a question
  and memory grounding confidence is below a threshold.
- **Off** — skip verification entirely.

The critique asks the LLM to evaluate its own answer and, if issues are
found, generates a revised response before delivery.

Recovery and fallback explanation logic also lives here so that
``AgentLoop`` can delegate all answer-quality concerns to this class.

Extracted from ``AgentLoop`` per ADR-002 to isolate verification logic.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.streaming import strip_think
from nanobot.context.prompt_loader import prompts
from nanobot.observability.langfuse import score_current_trace
from nanobot.observability.langfuse import span as langfuse_span

if TYPE_CHECKING:
    from nanobot.memory.store import MemoryStore
    from nanobot.providers.base import LLMProvider


class AnswerVerifier:
    """Self-critique verification of LLM answers."""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        model: str,
        temperature: float,
        max_tokens: int,
        verification_mode: str,
        memory_uncertainty_threshold: float,
        memory_store: MemoryStore | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.verification_mode = verification_mode
        self.memory_uncertainty_threshold = memory_uncertainty_threshold
        self._memory = memory_store

    async def verify(
        self,
        user_text: str,
        candidate: str,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float | None = None,
    ) -> tuple[str, list[dict]]:
        """Run a verification pass on the candidate answer.

        Returns ``(possibly_revised_content, updated_messages)``.
        If verification passes or is disabled, returns the candidate as-is.
        """
        if self.verification_mode == "off":
            return candidate, messages

        if self.verification_mode == "on_uncertainty" and not self.should_force_verification(
            user_text
        ):
            return candidate, messages

        effective_model = model if model is not None else self.model
        effective_temperature = temperature if temperature is not None else self.temperature

        logger.debug("Running verification pass (mode={})", self.verification_mode)

        critique_messages = [
            {"role": "system", "content": prompts.get("critique")},
            {
                "role": "user",
                "content": f"User's question: {user_text}\n\nAssistant's answer: {candidate}",
            },
        ]

        async with langfuse_span(
            name="verify",
            metadata={"mode": self.verification_mode, "model": effective_model},
        ):
            try:
                critique_response = await self.provider.chat(
                    messages=critique_messages,
                    tools=None,
                    model=effective_model,
                    temperature=0.0,
                    max_tokens=512,
                )
                raw = (critique_response.content or "").strip()
                parsed = json.loads(raw)
                confidence = int(parsed.get("confidence", 5))
                issues = parsed.get("issues", [])

                # Report verification confidence as a Langfuse score.
                score_current_trace(
                    name="verification_confidence",
                    value=confidence,
                    comment="; ".join(issues) if issues else "passed",
                )

                if confidence >= 3 and not issues:
                    logger.debug("Verification passed (confidence={})", confidence)
                    return candidate, messages

                logger.info(
                    "Verification flagged issues (confidence={}): {}",
                    confidence,
                    issues,
                )
                issue_text = "\n".join(f"- {i}" for i in issues) if issues else "Low confidence"
                messages.append(
                    {
                        "role": "system",
                        "content": prompts.render("revision_request", issue_text=issue_text),
                    }
                )

                revision = await self.provider.chat(
                    messages=messages,
                    tools=None,
                    model=effective_model,
                    temperature=effective_temperature,
                    max_tokens=self.max_tokens,
                )
                revised = strip_think(revision.content) or candidate
                for i in range(len(messages) - 1, -1, -1):
                    if messages[i].get("role") == "assistant":
                        messages[i]["content"] = revised
                        break
                logger.info("Answer revised after verification")
                return revised, messages

            except (json.JSONDecodeError, KeyError, ValueError):
                logger.debug("Verification response not parseable, skipping")
                return candidate, messages
            except Exception:  # crash-barrier: LLM verification call
                logger.debug("Verification call failed, returning original answer")
                return candidate, messages

    def should_force_verification(self, text: str) -> bool:
        """Return True when the text is a question with low memory grounding."""
        if not self._looks_like_question(text):
            return False
        confidence = self._estimate_grounding_confidence(text)
        return confidence < self.memory_uncertainty_threshold

    @staticmethod
    def _looks_like_question(text: str) -> bool:
        content = (text or "").strip().lower()
        if not content:
            return False
        if "?" in content:
            return True
        starters = (
            "what ",
            "which ",
            "who ",
            "when ",
            "where ",
            "why ",
            "how ",
            "is ",
            "are ",
            "do ",
            "does ",
            "did ",
            "can ",
            "could ",
            "should ",
            "would ",
            "will ",
        )
        return content.startswith(starters)

    def _estimate_grounding_confidence(self, query: str) -> float:
        if not self._memory:
            return 0.0
        try:
            items = self._memory.retriever.retrieve(query, top_k=1)
        except Exception:  # crash-barrier: memory subsystem
            return 0.0
        if not items:
            return 0.0
        top = items[0]
        try:
            score = float(top.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        return max(0.0, min(1.0, score))

    # ------------------------------------------------------------------
    # Recovery & fallback explanation (moved from AgentLoop, LAN-215)
    # ------------------------------------------------------------------

    async def attempt_recovery(
        self,
        *,
        channel: str,
        chat_id: str,
        all_msgs: list[dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
    ) -> str | None:
        """Try a single recovery LLM call with minimal context when the main loop produced None.

        Uses only the system prompt and the original user message (no tool history)
        with tools disabled to force a direct text answer.
        """
        system_msg = next((m for m in all_msgs if m.get("role") == "system"), None)
        user_msg = None
        for m in reversed(all_msgs):
            if m.get("role") == "user":
                user_msg = m
                break

        if not system_msg or not user_msg:
            logger.warning("Recovery skipped: missing system or user message")
            return None

        recovery_messages = [
            system_msg,
            user_msg,
            {
                "role": "system",
                "content": prompts.get("recovery"),
            },
        ]

        effective_model = model if model is not None else self.model
        effective_temperature = temperature if temperature is not None else self.temperature

        logger.info("Attempting recovery LLM call for {}:{}", channel, chat_id)
        try:
            response = await self.provider.chat(
                messages=recovery_messages,
                tools=None,
                model=effective_model,
                temperature=effective_temperature,
                max_tokens=self.max_tokens,
            )
        except Exception:  # crash-barrier: recovery LLM call
            logger.exception("Recovery LLM call failed")
            return None

        if response.finish_reason == "error":
            logger.warning("Recovery LLM call returned error: {}", response.content)
            return None

        content = strip_think(response.content)
        if content:
            logger.info("Recovery succeeded, returning answer")
        else:
            logger.warning("Recovery LLM call produced no usable content")
        return content

    @staticmethod
    def build_no_answer_explanation(user_text: str, messages: list[dict[str, Any]]) -> str:
        """Explain why the agent could not produce an answer on this turn."""
        tool_results = [m for m in messages if m.get("role") == "tool"]
        last_tool = tool_results[-1] if tool_results else None
        last_tool_name = str(last_tool.get("name", "")) if last_tool else ""
        last_tool_content = str(last_tool.get("content", "")) if last_tool else ""
        lowered = last_tool_content.lower()

        reasons: list[str] = []
        if not tool_results:
            reasons.append("The model did not produce a response for this message.")
        if "exit code: 1" in lowered or "no such file" in lowered or "not found" in lowered:
            reasons.append(
                f"My last check with `{last_tool_name or 'a tool'}` returned no matching data."
            )
        if "permission denied" in lowered:
            reasons.append("The lookup failed due to a local permission error.")
        if "insufficient_quota" in lowered or "429" in lowered:
            reasons.append("A provider quota/rate limit blocked part of the retrieval.")
        if not reasons:
            reasons.append("The model returned no final answer text after tool execution.")

        question = (user_text or "").strip()
        _question_words = {
            "who",
            "what",
            "when",
            "where",
            "why",
            "how",
            "is",
            "are",
            "can",
            "do",
        }
        looks_like_question = "?" in question or (
            question.split()[0].lower() in _question_words if question else False
        )
        help_line = (
            "Please try rephrasing your question or asking again."
            if looks_like_question
            else "Please share the fact directly and I can save it to memory."
        )

        primary_reason = reasons[0]
        return f"Sorry, I couldn't answer that just now. {primary_reason} {help_line}"
