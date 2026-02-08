"""Read Claude Code CLI's OAuth credentials from macOS Keychain.

When a user has logged in via `claude` (Claude Code CLI), this module
extracts the stored OAuth access token so nanobot can reuse it as an
Anthropic API key — no separate API key configuration needed.
"""

import json
import platform
import subprocess
import getpass
from loguru import logger


def get_claude_code_token() -> str | None:
    """Extract Claude Code CLI's OAuth access token from the system keychain.

    Returns the access token string, or None if unavailable.
    """
    if platform.system() != "Darwin":
        logger.debug("Claude Code auth extraction only supported on macOS currently")
        return None

    username = getpass.getuser()

    try:
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s", "Claude Code-credentials",
                "-a", username,
                "-w",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            logger.debug("Claude Code credentials not found in keychain")
            return None

        data = json.loads(result.stdout.strip())
        oauth = data.get("claudeAiOauth", {})
        token = oauth.get("accessToken")

        if token:
            logger.info("Using Claude Code CLI OAuth token for Anthropic API")
            return token

        logger.debug("No accessToken in Claude Code credentials")
        return None

    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
        logger.debug(f"Failed to read Claude Code credentials: {e}")
        return None
