"""Lightweight model router — picks main vs light model per request.

When ``routing_strategy`` is ``"auto"`` and a ``light_model`` is configured,
simple conversational turns are routed to the cheaper model while complex
tasks (code generation, debugging, multi-tool workflows) stay on the main
model.  When routing is ``"none"`` (the default) or ``light_model`` is
unset, the main model is always returned — zero behaviour change.
"""

from __future__ import annotations

from typing import Any


# ── Complex-task keywords (any match → use main model) ──────────────
_COMPLEX_KEYWORDS: tuple[str, ...] = (
    # Chinese
    "重构", "调试", "分析", "设计", "实现", "写代码", "修复", "部署", "审查",
    "优化", "迁移", "架构", "测试", "编写",
    # English
    "refactor", "debug", "analyze", "analyse", "design", "implement",
    "write code", "fix", "deploy", "review", "optimize", "migrate",
    "architect", "test", "develop",
)


# ── Helpers ──────────────────────────────────────────────────────────

def _last_user_text(messages: list[dict[str, Any]]) -> str:
    """Extract the text of the most recent user message (lowercased)."""
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            return content.lower()
        # Multi-part content (text + images)
        return " ".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ).lower()
    return ""


def _last_user_length(messages: list[dict[str, Any]]) -> int:
    """Character count of the most recent user message."""
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            return len(content)
        return sum(
            len(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return 0


def _user_turn_count(messages: list[dict[str, Any]]) -> int:
    """Count user turns in the conversation."""
    return sum(1 for m in messages if m.get("role") == "user")


def _has_tool_history(messages: list[dict[str, Any]]) -> bool:
    """Whether the conversation already contains tool-call results."""
    return any(m.get("role") == "tool" for m in messages)


# ── Simple-task signals (ALL must be True to route to light model) ──

_SIMPLE_SIGNALS = (
    # Few user turns (early / short conversation)
    lambda msgs: _user_turn_count(msgs) <= 2,
    # Short latest message (< 200 chars — likely a quick question)
    lambda msgs: _last_user_length(msgs) < 200,
    # No prior tool usage (pure chat, no code/file operations yet)
    lambda msgs: not _has_tool_history(msgs),
)


# ── Public API ───────────────────────────────────────────────────────

def pick_model(
    messages: list[dict[str, Any]],
    main_model: str,
    light_model: str | None,
    strategy: str = "none",
) -> str:
    """Choose which model to use for this request.

    Parameters
    ----------
    messages:
        The full message list about to be sent to the LLM.
    main_model:
        The user-configured primary (expensive) model.
    light_model:
        The user-configured cheaper model.  ``None`` disables routing.
    strategy:
        ``"none"`` — always return *main_model* (default, backward-compat).
        ``"auto"`` — return *light_model* when all simple signals match and
        no complex keyword is detected.

    Returns
    -------
    str
        The model identifier to use for this request.
    """
    # Fast path: routing disabled, no light model, or empty conversation
    if strategy == "none" or not light_model or not messages:
        return main_model

    # Complex keyword detected → main model
    user_text = _last_user_text(messages)
    if any(kw in user_text for kw in _COMPLEX_KEYWORDS):
        return main_model

    # All simple signals satisfied → light model
    if all(signal(messages) for signal in _SIMPLE_SIGNALS):
        return light_model

    # Default: main model
    return main_model
