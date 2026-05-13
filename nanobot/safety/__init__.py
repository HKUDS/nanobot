"""
Safety module for nanobot.

Provides prompt injection detection and other safety guardrails.
"""

from .prompt_guard import PromptGuard, GuardAction, GuardResult

__all__ = ["PromptGuard", "GuardAction", "GuardResult"]
