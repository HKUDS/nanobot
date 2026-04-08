"""Cross-cutting agent hooks.

Hooks in this package intercept the runner lifecycle without coupling to
any specific tool implementation. See ``CLAUDE.md`` for architecture notes.
"""

from nanobot.agent.hooks.rewrite import CommandRewriteHook

__all__ = ["CommandRewriteHook"]
