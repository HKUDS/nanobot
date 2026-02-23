"""Claude Code CLI OAuth token from environment.

Token is set via: claude setup-token
Env var: CLAUDE_CODE_OAUTH_TOKEN
"""

import os

from loguru import logger


def get_claude_code_token() -> str | None:
    """Get Claude Code OAuth token from CLAUDE_CODE_OAUTH_TOKEN env var.

    Users obtain this token by running: claude setup-token
    """
    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    if token:
        logger.debug("Using Claude Code OAuth token from CLAUDE_CODE_OAUTH_TOKEN")
        return token
    return None


def is_oauth_token(token: str) -> bool:
    """Check if a token is a Claude Code OAuth token (vs regular API key)."""
    return token.startswith("sk-ant-oat")
