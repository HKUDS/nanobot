"""Answer verification via LLM self-critique.

``AnswerVerifier`` implements a self-critique gate that can:

- **Always verify** — run a critique pass on every response.
- **Verify on uncertainty** — only verify when the user asks a question
  and memory grounding confidence is below a threshold.
- **Off** — skip verification entirely.

The critique asks the LLM to evaluate its own answer and, if issues are
found, generates a revised response before delivery.

Extracted from ``AgentLoop`` per ADR-002 to isolate verification logic.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from loguru import logger

from nanobot.agent.observability import score_current_trace
from nanobot.agent.observability import span as langfuse_span
from nanobot.agent.prompt_loader import prompts
from nanobot.agent.streaming import strip_think

if TYPE_CHECKING:
    from nanobot.agent.memory.store import MemoryStore
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
            metadata={"mode": self.verification_mode, "model": self.model},
        ):
            try:
                critique_response = await self.provider.chat(
                    messages=critique_messages,
                    tools=None,
                    model=self.model,
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
                        "content": (
                            f"Self-check found potential issues with your answer:\n"
                            f"{issue_text}\n\n"
                            "Please revise your answer addressing these concerns. "
                            "If you're uncertain about a claim, say so explicitly."
                        ),
                    }
                )

                revision = await self.provider.chat(
                    messages=messages,
                    tools=None,
                    model=self.model,
                    temperature=self.temperature,
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
            items = self._memory.retrieve(query, top_k=1)
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
