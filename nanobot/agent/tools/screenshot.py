"""Screenshot capture tool for cross-platform screen capture."""

import asyncio
import base64
import os
import platform
import tempfile
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool


class ScreenshotTool(Tool):
    """Tool to capture screenshots across platforms."""

    def __init__(self):
        self.system = platform.system().lower()

    @property
    def name(self) -> str:
        return "screenshot"

    @property
    def description(self) -> str:
        return "Capture a screenshot and return as base64 or save to file. Supports region capture."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "output_path": {
                    "type": "string",
                    "description": "Optional path to save screenshot. If not provided, returns base64."
                },
                "region": {
                    "type": "object",
                    "description": "Optional region to capture (x, y, width, height)",
                    "properties": {
                        "x": {"type": "integer", "description": "X coordinate"},
                        "y": {"type": "integer", "description": "Y coordinate"},
                        "width": {"type": "integer", "description": "Width"},
                        "height": {"type": "integer", "description": "Height"}
                    },
                    "required": ["x", "y", "width", "height"]
                },
                "delay": {
                    "type": "number",
                    "description": "Delay before capture in seconds",
                    "default": 0
                }
            }
        }

    async def execute(
        self,
        output_path: str | None = None,
        region: dict[str, int] | None = None,
        delay: float = 0,
        **kwargs: Any
    ) -> str:
        """Capture screenshot and return base64 or save to file."""
        # Input validation
        if output_path and len(output_path) > 500:
            return "Error: Output path too long"

        if delay < 0 or delay > 10:
            return "Error: Delay must be between 0 and 10 seconds"

        if region:
            if not all(k in region for k in ["x", "y", "width", "height"]):
                return "Error: Region must include x, y, width, height"
            if any(region[k] < 0 for k in region):
                return "Error: Region coordinates must be non-negative"

        # Delay if requested
        if delay > 0:
            await asyncio.sleep(delay)

        # Create temp file if no output path
        use_temp = output_path is None
        if use_temp:
            temp_fd, output_path = tempfile.mkstemp(suffix=".png")
            os.close(temp_fd)

        try:
            # Capture screenshot
            success, error = await self._capture_screenshot(output_path, region)
            if not success:
                return f"Error capturing screenshot: {error}"

            # Return base64 if temp file
            if use_temp:
                with open(output_path, "rb") as f:
                    image_data = f.read()
                os.unlink(output_path)
                b64_data = base64.b64encode(image_data).decode("utf-8")
                return f"data:image/png;base64,{b64_data}"
            else:
                return f"Screenshot saved to {output_path}"

        except Exception as e:
            if use_temp and os.path.exists(output_path):
                os.unlink(output_path)
            return f"Error: {str(e)}"

    async def _capture_screenshot(self, output_path: str, region: dict[str, int] | None) -> tuple[bool, str]:
        """Capture screenshot using platform-specific tools."""
        try:
            if self.system == "darwin":  # macOS
                return await self._capture_macos(output_path, region)
            elif self.system == "linux":
                return await self._capture_linux(output_path, region)
            elif self.system == "windows":
                return await self._capture_windows(output_path, region)
            else:
                return False, f"Unsupported platform: {self.system}"
        except Exception as e:
            return False, f"Capture failed: {str(e)}"

    async def _capture_macos(self, output_path: str, region: dict[str, int] | None) -> tuple[bool, str]:
        """Capture screenshot on macOS using screencapture."""
        cmd = ["screencapture", "-x"]  # -x = no sound

        if region:
            # macOS screencapture uses -R x,y,width,height
            x, y, w, h = region["x"], region["y"], region["width"], region["height"]
            cmd.extend(["-R", f"{x},{y},{w},{h}"])

        cmd.append(output_path)

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            return True, ""
        else:
            error = stderr.decode("utf-8", errors="replace").strip()
            return False, error or "screencapture failed"

    async def _capture_linux(self, output_path: str, region: dict[str, int] | None) -> tuple[bool, str]:
        """Capture screenshot on Linux using available tools."""
        # Try gnome-screenshot first, then scrot
        tools = [
            self._gnome_screenshot_cmd,
            self._scrot_cmd
        ]

        for tool_func in tools:
            cmd = tool_func(output_path, region)
            if cmd:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

                stdout, stderr = await process.communicate()

                if process.returncode == 0:
                    return True, ""

        return False, "No screenshot tool available (tried gnome-screenshot, scrot)"

    def _gnome_screenshot_cmd(self, output_path: str, region: dict[str, int] | None) -> list[str] | None:
        """Generate gnome-screenshot command."""
        cmd = ["gnome-screenshot", "--file", output_path]
        if region:
            x, y, w, h = region["x"], region["y"], region["width"], region["height"]
            cmd.extend(["--area", "--x", str(x), "--y", str(y), "--width", str(w), "--height", str(h)])
        return cmd

    def _scrot_cmd(self, output_path: str, region: dict[str, int] | None) -> list[str] | None:
        """Generate scrot command."""
        cmd = ["scrot", output_path]
        if region:
            x, y, w, h = region["x"], region["y"], region["width"], region["height"]
            geometry = f"{w}x{h}+{x}+{y}"
            cmd.extend(["-a", geometry])
        return cmd

    async def _capture_windows(self, output_path: str, region: dict[str, int] | None) -> tuple[bool, str]:
        """Capture screenshot on Windows using PowerShell."""
        # Use PowerShell to capture screenshot
        # Note: This is a basic implementation, may need refinement

        ps_script = f"""
        Add-Type -AssemblyName System.Windows.Forms
        Add-Type -AssemblyName System.Drawing

        $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
        $bitmap = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        $graphics.CopyFromScreen($bounds.X, $bounds.Y, 0, 0, $bounds.Size)
        $bitmap.Save("{output_path}", [System.Drawing.Imaging.ImageFormat]::Png)
        $graphics.Dispose()
        $bitmap.Dispose()
        """

        # Write temp script and execute
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ps1", delete=False) as f:
            f.write(ps_script)
            script_path = f.name

        try:
            process = await asyncio.create_subprocess_exec(
                "powershell.exe", "-ExecutionPolicy", "Bypass", "-File", script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                return True, ""
            else:
                error = stderr.decode("utf-8", errors="replace").strip()
                return False, error or "PowerShell screenshot failed"

        finally:
            os.unlink(script_path)
