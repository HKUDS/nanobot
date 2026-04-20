"""Tirith pre-exec security scanning wrapper.

Tirith (https://github.com/sheeki03/tirith) is a terminal security tool
that scans commands for content-level threats: homograph/punycode URLs,
pipe-to-interpreter patterns, terminal injection (ANSI escapes, bidi
Unicode, zero-width chars), typosquatted packages, and insecure transport.

Exit code is the verdict source of truth:
  0 = allow, 1 = block, 2 = warn

The tirith binary must be installed separately — nanobot does not download
or install it. Options: `brew install sheeki03/tap/tirith`,
`cargo install tirith`, or a prebuilt release from
https://github.com/sheeki03/tirith/releases. If tirith is absent, scanning
fails through the configured fail_open branch (default: allow).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from typing import Any

logger = logging.getLogger(__name__)

_MAX_FINDINGS = 50
_MAX_SUMMARY_LEN = 500


def _resolve_tirith_path(configured: str) -> str | None:
    """Resolve a user-configured tirith path.

    Rules:
      - expand ~
      - if the value has a path component (any separator), treat as explicit
        path — return it only if it is a real, executable file; otherwise None
      - otherwise, PATH lookup via shutil.which
    """
    expanded = os.path.expanduser(configured)
    has_path_component = os.sep in expanded or (
        os.altsep is not None and os.altsep in expanded
    )
    if has_path_component:
        if os.path.isfile(expanded) and os.access(expanded, os.X_OK):
            return expanded
        return None
    return shutil.which(expanded)


def check_security(
    text: str,
    context: str = "exec",
    *,
    enabled: bool = False,
    tirith_bin: str = "tirith",
    timeout: int = 5,
    fail_open: bool = True,
) -> dict[str, Any]:
    """Run tirith scan. Returns {action, findings, summary}.

    Exit code is source of truth: 0=allow, 1=block, 2=warn.
    Disabled by default — callers opt in via `enabled=True`.
    """
    if not enabled:
        return {"action": "allow", "findings": [], "summary": ""}

    tirith_path = _resolve_tirith_path(tirith_bin)
    if tirith_path is None:
        msg = f"tirith not found (looked for {tirith_bin!r})"
        if fail_open:
            return {"action": "allow", "findings": [], "summary": f"{msg} (fail-open)"}
        return {"action": "block", "findings": [], "summary": f"{msg} (fail-closed)"}

    shell_mode = "posix" if sys.platform != "win32" else "cmd"

    try:
        if context == "exec":
            cmd = [
                tirith_path, "check", "--json", "--non-interactive",
                "--shell", shell_mode, "--", text,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        else:
            cmd = [tirith_path, "paste", "--json", "--non-interactive"]
            result = subprocess.run(
                cmd, input=text, capture_output=True, text=True, timeout=timeout,
            )
    except OSError as exc:
        logger.warning("tirith spawn failed: %s", exc, exc_info=True)
        if fail_open:
            return {"action": "allow", "findings": [], "summary": f"tirith unavailable: {exc}"}
        return {"action": "block", "findings": [], "summary": f"tirith failed (fail-closed): {exc}"}
    except subprocess.TimeoutExpired:
        logger.warning("tirith timed out after %ds", timeout)
        if fail_open:
            return {"action": "allow", "findings": [], "summary": f"tirith timed out ({timeout}s)"}
        return {"action": "block", "findings": [], "summary": "tirith timed out (fail-closed)"}

    exit_code = result.returncode
    if exit_code == 0:
        action = "allow"
    elif exit_code == 1:
        action = "block"
    elif exit_code == 2:
        action = "warn"
    else:
        logger.warning("tirith unexpected exit code %d", exit_code)
        if fail_open:
            return {"action": "allow", "findings": [], "summary": f"tirith exit code {exit_code} (fail-open)"}
        return {"action": "block", "findings": [], "summary": f"tirith exit code {exit_code} (fail-closed)"}

    findings: list[dict[str, Any]] = []
    summary = ""
    try:
        data = json.loads(result.stdout) if result.stdout.strip() else {}
        findings = data.get("findings", [])[:_MAX_FINDINGS]
        summary = (data.get("summary", "") or "")[:_MAX_SUMMARY_LEN]
    except (json.JSONDecodeError, AttributeError):
        logger.debug("tirith JSON parse failed, using exit code only")
        if action == "block":
            summary = "security issue detected (details unavailable)"
        elif action == "warn":
            summary = "security warning detected (details unavailable)"

    return {"action": action, "findings": findings, "summary": summary}
