"""Read Claude Code CLI's OAuth credentials from system storage.

When a user has logged in via `claude` (Claude Code CLI), this module
extracts the stored OAuth access token so nanobot can reuse it as an
Anthropic API key — no separate API key configuration needed.

Supported platforms:
- macOS: reads from Keychain
- Linux: reads from ~/.claude/.credentials.json
"""

import json
import platform
import subprocess
import getpass
from pathlib import Path
from loguru import logger


def get_claude_code_token() -> str | None:
    """Extract Claude Code CLI's OAuth access token from system storage.

    Returns the access token string, or None if unavailable.
    """
    system = platform.system()

    if system == "Darwin":
        return _get_token_from_keychain()
    elif system in ("Linux", "Windows"):
        return _get_token_from_credentials_file()
    else:
        logger.debug(f"Claude Code auth extraction not supported on {system}")
        return None


def _get_token_from_keychain() -> str | None:
    """Extract token from macOS Keychain."""
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
        return _extract_token(data)

    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
        logger.debug(f"Failed to read Claude Code credentials from keychain: {e}")
        return None


def _get_token_from_credentials_file() -> str | None:
    """Extract token from ~/.claude/.credentials.json (Linux/Windows)."""
    creds_file = Path.home() / ".claude" / ".credentials.json"

    if not creds_file.exists():
        logger.debug(f"Claude Code credentials file not found: {creds_file}")
        return None

    try:
        data = json.loads(creds_file.read_text())
        return _extract_token(data)

    except (json.JSONDecodeError, Exception) as e:
        logger.debug(f"Failed to read Claude Code credentials file: {e}")
        return None


def _extract_token(data: dict) -> str | None:
    """Extract access token from credentials data."""
    oauth = data.get("claudeAiOauth", {})
    token = oauth.get("accessToken")

    if token:
        logger.info("Using Claude Code CLI OAuth token for Anthropic API")
        return token

    logger.debug("No accessToken in Claude Code credentials")
    return None
