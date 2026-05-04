"""Detect hallucinated tool calls in agent responses.

A hallucinated tool call is when the model's natural-language response
*claims* it performed a side-effecting action (e.g. "I've added the meeting
to your calendar", "Done. I'll remind you Monday at 9 AM") but no tool
call backing that claim was actually issued in the turn.

This guard is opt-in. By default it observes and logs only. Operators can
enable a soft warning appended to the user-visible response, or strict
mode that injects a follow-up system message asking the model to either
make the missing tool call or correct its claim.

Detection is intentionally conservative — false positives break trust
faster than missed detections do. The matcher is:

    1. The final response text contains an action-claim phrase
       (configurable list, English-language defaults).
    2. The final iteration had zero tool calls AND no tool call earlier in
       the same turn would plausibly back the claim (heuristic only —
       see below).

This is not perfect. It will miss multilingual claims, claims phrased in
unusual ways, and claims backed by tool calls whose effect doesn't match
the claim. It is a smoke detector, not a fire alarm.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from loguru import logger

from nanobot.agent.hook import AgentHook, AgentHookContext

# Default English-language phrases that signal a side-effecting claim. The
# list is intentionally narrow — we want high precision over high recall.
# Each entry must imply the model believes external state has been changed
# or scheduled, not just that information has been retrieved.
DEFAULT_ACTION_CLAIM_PATTERNS: tuple[str, ...] = (
    # Reminders / scheduling
    r"\bI(?:'ve| have| will| 'll)?\s+(?:set|added|scheduled|created)\b[^.]{0,80}\b(?:reminder|alert|alarm|cron|schedule)\b",
    r"\bI(?:'ve| have| will| 'll)?\s+remind\s+you\b",
    r"\breminder\s+(?:is\s+)?set\b",
    # Calendar
    r"\bI(?:'ve| have| will| 'll)?\s+(?:added|created|scheduled)\b[^.]{0,80}\b(?:calendar|event|meeting)\b",
    r"\b(?:added|saved)\s+(?:the|that|this|your)?\s*(?:meeting|event)\s+to\s+(?:your\s+)?calendar\b",
    # Email / messages
    r"\bI(?:'ve| have)\s+(?:sent|emailed|messaged|replied|forwarded)\b",
    # Files / writes
    r"\bI(?:'ve| have)\s+(?:saved|written|created|updated)\s+(?:the\s+)?(?:file|note|document)\b",
    # Generic confirmation when paired with future tense action
    r"\b(?:Done|Got it|Fixed)\b\.?\s+I(?:'ll| will)\s+(?:remind|alert|notify|email|message|send|schedule)\b",
)

# Tool name fragments that, when present in the turn, count as plausible
# backing for an action claim. Match is case-insensitive substring.
DEFAULT_BACKING_TOOL_FRAGMENTS: tuple[str, ...] = (
    "cron",
    "reminder",
    "calendar",
    "email",
    "gmail",
    "send",
    "write_file",
    "drive_create",
    "drive_update",
    "create_event",
    "schedule",
)


@dataclass(slots=True)
class HallucinatedToolCallGuardConfig:
    """Configuration for the hallucinated tool call guard.

    Attributes:
        enabled: Master switch. When False, the guard is a no-op.
        annotate_response: When True, append a short visible note to the
            user-facing response when a hallucination is detected. Default
            False (log-only).
        warning_text: Override the default appended note.
        action_claim_patterns: Regex patterns that detect action claims.
            Defaults to a curated English-language list.
        backing_tool_fragments: Substrings of tool names that count as
            plausible backing for an action claim.
    """

    enabled: bool = False
    annotate_response: bool = False
    warning_text: str = (
        "\n\n_(I noticed I described an action above but I am not certain the "
        "underlying tool actually ran — please verify before relying on it.)_"
    )
    action_claim_patterns: tuple[str, ...] = DEFAULT_ACTION_CLAIM_PATTERNS
    backing_tool_fragments: tuple[str, ...] = DEFAULT_BACKING_TOOL_FRAGMENTS


class HallucinatedToolCallGuard(AgentHook):
    """Hook that flags responses claiming actions without backing tool calls.

    The guard records all tool calls observed across the turn (collected
    via `before_execute_tools`) and, on `finalize_content`, scans the final
    response for action-claim phrases. If a claim is found and no plausible
    backing tool was called, it logs a WARNING and (optionally) annotates
    the response.

    The guard never raises and never blocks a turn — its only effect when
    `annotate_response` is False is a log line. This keeps it safe to
    enable in production as a diagnostic before promoting to user-visible.
    """

    __slots__ = ("_config", "_compiled_patterns", "_tool_names_seen")

    def __init__(self, config: HallucinatedToolCallGuardConfig | None = None) -> None:
        super().__init__()
        self._config = config or HallucinatedToolCallGuardConfig()
        self._compiled_patterns = [
            re.compile(p, re.IGNORECASE) for p in self._config.action_claim_patterns
        ]
        # Reset per turn via reset(). The runner shares one hook instance
        # for the whole turn, so we accumulate then clear.
        self._tool_names_seen: list[str] = []

    def reset(self) -> None:
        """Clear per-turn state. Call before a new turn."""
        self._tool_names_seen.clear()

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        if not self._config.enabled:
            return
        for tc in context.tool_calls:
            self._tool_names_seen.append(tc.name)

    def finalize_content(self, context: AgentHookContext, content: str | None) -> str | None:
        if not self._config.enabled or not content:
            return content

        claim = self._find_action_claim(content)
        if claim is None:
            return content

        if self._has_plausible_backing_tool():
            return content

        # Hallucination signal.
        logger.warning(
            "Hallucinated tool call guard tripped: model claimed an action "
            "('{}') but no backing tool was called this turn. "
            "Tools observed this turn: {}",
            claim[:120],
            self._tool_names_seen or "<none>",
        )

        if self._config.annotate_response:
            return content + self._config.warning_text

        return content

    # ---- internals --------------------------------------------------------

    def _find_action_claim(self, content: str) -> str | None:
        for pattern in self._compiled_patterns:
            match = pattern.search(content)
            if match:
                return match.group(0)
        return None

    def _has_plausible_backing_tool(self) -> bool:
        if not self._tool_names_seen:
            return False
        fragments = [f.lower() for f in self._config.backing_tool_fragments]
        for tool_name in self._tool_names_seen:
            tn = tool_name.lower()
            for frag in fragments:
                if frag in tn:
                    return True
        return False
