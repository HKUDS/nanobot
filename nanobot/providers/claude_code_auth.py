"""Read Claude Code CLI's OAuth credentials.

When a user has logged in via `claude` (Claude Code CLI), this module
extracts the stored OAuth access token so nanobot can reuse it as an
Anthropic API key — no separate API key configuration needed.

Supports macOS (Keychain) and Linux (~/.claude/.credentials.json).
"""

import json
import platform
import subprocess
import getpass
from pathlib import Path
from loguru import logger


def _read_token_darwin() -> str | None:
    """Read OAuth token from macOS Keychain."""
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

        return _extract_token(json.loads(result.stdout.strip()))

    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
        logger.debug(f"Failed to read Claude Code credentials from keychain: {e}")
        return None


def _read_token_linux() -> str | None:
    """Read OAuth token from ~/.claude/.credentials.json."""
    cred_path = Path.home() / ".claude" / ".credentials.json"
    try:
        data = json.loads(cred_path.read_text())
        return _extract_token(data)
    except FileNotFoundError:
        logger.debug(f"Claude Code credentials file not found: {cred_path}")
        return None
    except (json.JSONDecodeError, Exception) as e:
        logger.debug(f"Failed to read Claude Code credentials from {cred_path}: {e}")
        return None


def _extract_token(data: dict) -> str | None:
    """Extract accessToken from parsed credentials JSON."""
    oauth = data.get("claudeAiOauth", {})
    token = oauth.get("accessToken")
    if token:
        logger.info("Using Claude Code CLI OAuth token for Anthropic API")
        return token
    logger.debug("No accessToken in Claude Code credentials")
    return None


def get_claude_code_token() -> str | None:
    """Extract Claude Code CLI's OAuth access token.

    Returns the access token string, or None if unavailable.
    """
    system = platform.system()
    if system == "Darwin":
        return _read_token_darwin()
    elif system == "Linux":
        return _read_token_linux()
    else:
        logger.debug(f"Claude Code auth extraction not supported on {system}")
        return None
