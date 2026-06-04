"""CLI-based diagnostics - bypass VSCode cache, get fresh results."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


async def run_pyright(file_path: str, workspace: str | None = None) -> list[dict]:
    """Run pyright CLI and return diagnostics for a file.

    Args:
        file_path: Path to Python file
        workspace: Workspace root (for context)

    Returns:
        List of diagnostic dicts with keys: message, severity, line, character, code
    """
    file_p = Path(file_path).expanduser().resolve()
    cwd = Path(workspace).expanduser().resolve() if workspace else file_p.parent

    cmd = ["pyright", "--outputjson", str(file_p)]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)

        if not stdout:
            return []

        data = json.loads(stdout.decode())
        diagnostics = data.get("generalDiagnostics", [])

        # Normalize to our format
        return [
            {
                "message": d.get("message", ""),
                "severity": _pyright_severity(d.get("severity", "error")),
                "range": {
                    "start": {
                        "line": d.get("range", {}).get("start", {}).get("line", 0),
                        "character": d.get("range", {}).get("start", {}).get("character", 0),
                    },
                    "end": {
                        "line": d.get("range", {}).get("end", {}).get("line", 0),
                        "character": d.get("range", {}).get("end", {}).get("character", 0),
                    },
                },
                "code": d.get("code"),
                "source": "pyright",
                "file": d.get("file", str(file_p)),
            }
            for d in diagnostics
        ]
    except asyncio.TimeoutError:
        return [{"message": "pyright timeout", "severity": "error", "source": "cli"}]
    except json.JSONDecodeError:
        return []
    except Exception:
        return []


async def run_tsc(file_path: str, workspace: str | None = None) -> list[dict]:
    """Run tsc CLI and return diagnostics for a file.

    tsc doesn't support single-file checking, so we run for the whole project
    and filter results to the requested file.

    Args:
        file_path: Path to TypeScript/JavaScript file
        workspace: Workspace root (required for tsc)

    Returns:
        List of diagnostic dicts
    """
    file_p = Path(file_path).expanduser().resolve()
    cwd = Path(workspace).expanduser().resolve() if workspace else file_p.parent

    # Find tsconfig.json - prefer tsconfig.app.json for app code
    tsconfig = _find_tsconfig(cwd, prefer_app=True)
    if tsconfig:
        cwd = tsconfig.parent

    # Build command with project config
    cmd = ["npx", "tsc", "--noEmit", "--pretty", "false"]
    if tsconfig:
        cmd.extend(["-p", str(tsconfig)])

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)

        # tsc outputs errors to stderr in non-pretty mode
        output = (stderr or stdout or b"").decode()

        # Parse tsc output: path(line,col): error TSxxxx: message
        # Example: src/main.tsx(10,5): error TS2322: Type 'string' is not assignable to type 'number'.
        pattern = r"^(.+?)\((\d+),(\d+)\):\s*(error|warning)\s+(TS\d+):\s*(.+)$"
        diagnostics = []

        for line in output.split("\n"):
            match = re.match(pattern, line.strip())
            if match:
                path, line_num, col, severity, code, message = match.groups()
                diag_path = Path(path)

                # Only include diagnostics for the requested file
                # Match by resolve (absolute) or by name (relative output)
                try:
                    resolved_diag = (cwd / path).resolve()
                    if resolved_diag == file_p or diag_path.name == file_p.name:
                        diagnostics.append({
                            "message": message,
                            "severity": severity,
                            "range": {
                                "start": {"line": int(line_num) - 1, "character": int(col) - 1},
                                "end": {"line": int(line_num) - 1, "character": int(col) + len(message)},
                            },
                            "code": code,
                            "source": "tsc",
                            "file": str(diag_path),
                        })
                except Exception:
                    # If path resolution fails, just match by filename
                    if diag_path.name == file_p.name:
                        diagnostics.append({
                            "message": message,
                            "severity": severity,
                            "range": {
                                "start": {"line": int(line_num) - 1, "character": int(col) - 1},
                                "end": {"line": int(line_num) - 1, "character": int(col) + len(message)},
                            },
                            "code": code,
                            "source": "tsc",
                            "file": str(diag_path),
                        })

        return diagnostics
    except asyncio.TimeoutError:
        return [{"message": "tsc timeout", "severity": "error", "source": "cli"}]
    except Exception:
        return []


async def run_ruff(file_path: str, workspace: str | None = None) -> list[dict]:
    """Run ruff CLI and return diagnostics for a file.

    Args:
        file_path: Path to Python file
        workspace: Workspace root

    Returns:
        List of diagnostic dicts
    """
    file_p = Path(file_path).expanduser().resolve()
    cwd = Path(workspace).expanduser().resolve() if workspace else file_p.parent

    cmd = ["ruff", "check", "--output-format", "json", str(file_p)]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)

        if not stdout:
            return []

        # ruff outputs JSON array
        data = json.loads(stdout.decode())

        return [
            {
                "message": d.get("message", ""),
                "severity": "warning" if d.get("fix") else "error",
                "range": {
                    "start": {
                        "line": d.get("location", {}).get("row", 1) - 1,
                        "character": d.get("location", {}).get("column", 1) - 1,
                    },
                    "end": {
                        "line": d.get("end_location", {}).get("row", 1) - 1,
                        "character": d.get("end_location", {}).get("column", 1) - 1,
                    },
                },
                "code": d.get("code"),
                "source": "ruff",
                "file": d.get("filename", str(file_p)),
            }
            for d in data
        ]
    except asyncio.TimeoutError:
        return [{"message": "ruff timeout", "severity": "error", "source": "cli"}]
    except json.JSONDecodeError:
        return []
    except Exception:
        return []


async def get_diagnostics_cli(
    file_path: str,
    workspace: str | None = None,
    linters: Sequence[str] | None = None,
) -> list[dict]:
    """Get diagnostics using CLI tools (bypasses VSCode cache).

    Automatically detects language from file extension.

    Args:
        file_path: Path to file
        workspace: Workspace root
        linters: Override auto-detection, specify linters to run

    Returns:
        Combined list of diagnostics from all applicable tools
    """
    file_p = Path(file_path)
    ext = file_p.suffix.lower()

    # Auto-detect linters based on file extension
    if linters is None:
        if ext == ".py":
            linters = ["pyright", "ruff"]
        elif ext in (".ts", ".tsx", ".js", ".jsx"):
            linters = ["tsc"]
        else:
            return []

    diagnostics = []

    for linter in linters:
        if linter == "pyright":
            diagnostics.extend(await run_pyright(file_path, workspace))
        elif linter == "tsc":
            diagnostics.extend(await run_tsc(file_path, workspace))
        elif linter == "ruff":
            diagnostics.extend(await run_ruff(file_path, workspace))

    return diagnostics


def _pyright_severity(severity: str) -> str:
    """Convert pyright severity to standard format."""
    mapping = {
        "error": "error",
        "warning": "warning",
        "information": "info",
        "hint": "hint",
    }
    return mapping.get(severity.lower(), "error")


def _find_tsconfig(directory: Path, prefer_app: bool = True) -> Path | None:
    """Find tsconfig.json in directory or parents.

    Args:
        directory: Starting directory
        prefer_app: If True, prefer tsconfig.app.json over tsconfig.json
    """
    current = directory
    while current != current.parent:
        # Check for tsconfig.app.json first if preferred
        if prefer_app:
            app_config = current / "tsconfig.app.json"
            if app_config.exists():
                return app_config

        # Fall back to tsconfig.json
        tsconfig = current / "tsconfig.json"
        if tsconfig.exists():
            return tsconfig

        current = current.parent
    return None
