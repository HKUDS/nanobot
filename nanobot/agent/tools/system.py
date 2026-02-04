"""System control tools for the agent."""

import os
import platform
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool

def _get_os() -> str:
    return platform.system().lower()


def _safe_run(cmd: list[str]) -> tuple[bool, str]:
    """
    Safely run a predefined system command.
    No shell=True allowed.
    """
    try:
        subprocess.run(cmd, check=True)
        return True, "Command executed successfully"
    except subprocess.CalledProcessError as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)


class OpenApplicationTool(Tool):
    """Open an application by name."""

    @property
    def name(self) -> str:
        return "open_application"

    @property
    def description(self) -> str:
        return "Open an application on the system."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "app": {
                    "type": "string",
                    "description": "Application name (e.g. Chrome, VS Code)",
                }
            },
            "required": ["app"],
        }

    async def execute(self, app: str, **kwargs: Any) -> str:
        os_name = _get_os()

        if os_name == "darwin":  # macOS
            success, msg = _safe_run(["open", "-a", app])
        elif os_name == "windows":
            success, msg = _safe_run(["cmd", "/c", "start", "", app])
        elif os_name == "linux":
            success, msg = _safe_run([app])
        else:
            return f"Unsupported OS: {os_name}"

        return f"Opened application: {app}" if success else f"Error opening {app}: {msg}"


class CloseApplicationTool(Tool):
    """Close an application by name."""

    @property
    def name(self) -> str:
        return "close_application"

    @property
    def description(self) -> str:
        return "Close a running application by name."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "app": {
                    "type": "string",
                    "description": "Application name to close",
                }
            },
            "required": ["app"],
        }

    async def execute(self, app: str, **kwargs: Any) -> str:
        os_name = _get_os()

        if os_name == "darwin":
            cmd = ["pkill", "-f", app]
        elif os_name == "windows":
            cmd = ["taskkill", "/IM", f"{app}.exe", "/F"]
        elif os_name == "linux":
            cmd = ["pkill", app]
        else:
            return f"Unsupported OS: {os_name}"

        success, msg = _safe_run(cmd)
        return f"Closed application: {app}" if success else f"Error closing {app}: {msg}"


class SystemInfoTool(Tool):
    """Get system information."""

    @property
    def name(self) -> str:
        return "system_info"

    @property
    def description(self) -> str:
        return "Get basic system information."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> str:
        info = {
            "os": platform.system(),
            "os_version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python_version": platform.python_version(),
            "time": datetime.now().isoformat(),
        }
        return "\n".join(f"{k}: {v}" for k, v in info.items())


class ScreenshotTool(Tool):
    """Take a screenshot and save it."""

    @property
    def name(self) -> str:
        return "take_screenshot"

    @property
    def description(self) -> str:
        return "Take a screenshot and save it to a file."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to save screenshot",
                }
            },
            "required": ["path"],
        }

    async def execute(self, path: str, **kwargs: Any) -> str:
        os_name = _get_os()
        file_path = Path(path).expanduser()

        file_path.parent.mkdir(parents=True, exist_ok=True)

        if os_name == "darwin":
            cmd = ["screencapture", str(file_path)]
        elif os_name == "linux":
            cmd = ["gnome-screenshot", "-f", str(file_path)]
        elif os_name == "windows":
            return "Screenshot tool not implemented for Windows yet"
        else:
            return f"Unsupported OS: {os_name}"

        success, msg = _safe_run(cmd)
        return (
            f"Screenshot saved to {file_path}"
            if success
            else f"Error taking screenshot: {msg}"
        )