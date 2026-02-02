"""Screenshot tool for capturing screen images."""

import mimetypes
import platform
import subprocess
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool


class ScreenshotTool(Tool):
    """
    Tool to capture screenshots of the screen or specific windows.

    Supports macOS, Linux (with gnome-screenshot or scrot), and Windows.
    Screenshots are saved to ~/.nanobot/screenshots/ directory.
    """

    # Supported image formats
    SUPPORTED_FORMATS = {"png", "jpg", "jpeg", "gif", "tiff"}

    # Maximum file size (10MB)
    MAX_FILE_SIZE = 10 * 1024 * 1024

    def __init__(self, screenshots_dir: Path | None = None):
        """
        Initialize the screenshot tool.

        Args:
            screenshots_dir: Custom directory for saving screenshots.
                           Defaults to ~/.nanobot/screenshots/
        """
        self._screenshots_dir = screenshots_dir or (Path.home() / ".nanobot" / "screenshots")
        self._screenshots_dir.mkdir(parents=True, exist_ok=True)
        self._platform = platform.system().lower()

    @property
    def name(self) -> str:
        return "screenshot"

    @property
    def description(self) -> str:
        return (
            "Capture a screenshot of the entire screen or a specific display. "
            "Returns the file path of the saved screenshot. "
            "Use the 'message' tool with media_paths to send the screenshot to the user."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "display": {
                    "type": "integer",
                    "description": "Display number to capture (0 for main display). Default: 0"
                },
                "filename": {
                    "type": "string",
                    "description": "Optional custom filename (without extension). Default: timestamp-based name"
                },
                "format": {
                    "type": "string",
                    "enum": ["png", "jpg"],
                    "description": "Image format. Default: png"
                }
            },
            "required": []
        }

    async def execute(
        self,
        display: int = 0,
        filename: str | None = None,
        format: str = "png",
        **kwargs: Any
    ) -> str:
        """
        Capture a screenshot.

        Args:
            display: Display number to capture (0 for main).
            filename: Optional custom filename.
            format: Image format (png or jpg).

        Returns:
            Success message with file path, or error message.
        """
        # Validate format
        format = format.lower()
        if format not in {"png", "jpg", "jpeg"}:
            return f"Error: Unsupported format '{format}'. Use 'png' or 'jpg'."

        # Normalize jpg/jpeg
        if format == "jpeg":
            format = "jpg"

        # Generate filename
        if filename:
            # Sanitize filename
            safe_filename = "".join(c for c in filename if c.isalnum() or c in "-_")
            if not safe_filename:
                safe_filename = "screenshot"
        else:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            safe_filename = f"screenshot-{timestamp}"

        output_path = self._screenshots_dir / f"{safe_filename}.{format}"

        # Avoid overwriting
        counter = 1
        while output_path.exists():
            output_path = self._screenshots_dir / f"{safe_filename}-{counter}.{format}"
            counter += 1

        try:
            # Platform-specific screenshot
            if self._platform == "darwin":
                result = await self._capture_macos(output_path, display)
            elif self._platform == "linux":
                result = await self._capture_linux(output_path, display)
            elif self._platform == "windows":
                result = await self._capture_windows(output_path, display)
            else:
                return f"Error: Unsupported platform '{self._platform}'"

            if result is not None:
                return result  # Error message

            # Verify file was created
            if not output_path.exists():
                return "Error: Screenshot file was not created"

            # Check file size
            file_size = output_path.stat().st_size
            if file_size > self.MAX_FILE_SIZE:
                output_path.unlink()
                return f"Error: Screenshot too large ({file_size / 1024 / 1024:.1f}MB). Max: 10MB"

            if file_size == 0:
                output_path.unlink()
                return "Error: Screenshot file is empty"

            logger.info(f"Screenshot saved: {output_path} ({file_size / 1024:.1f}KB)")

            return (
                f"Screenshot saved successfully.\n"
                f"Path: {output_path}\n"
                f"Size: {file_size / 1024:.1f}KB\n\n"
                f"To send this screenshot to the user, use the message tool with:\n"
                f'message(content="Here is the screenshot", media_paths=["{output_path}"])'
            )

        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return f"Error capturing screenshot: {str(e)}"

    async def _capture_macos(self, output_path: Path, display: int) -> str | None:
        """
        Capture screenshot on macOS using screencapture.

        Returns None on success, error message on failure.
        """
        if not shutil.which("screencapture"):
            return "Error: 'screencapture' command not found"

        cmd = ["screencapture", "-x"]  # -x = no sound

        # Add display selection if not main display
        if display > 0:
            cmd.extend(["-D", str(display + 1)])  # screencapture uses 1-based indexing

        cmd.append(str(output_path))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                error = result.stderr.strip() or "Unknown error"
                return f"Error: screencapture failed - {error}"

            return None  # Success

        except subprocess.TimeoutExpired:
            return "Error: Screenshot timed out after 30 seconds"
        except Exception as e:
            return f"Error running screencapture: {str(e)}"

    async def _capture_linux(self, output_path: Path, display: int) -> str | None:
        """
        Capture screenshot on Linux using gnome-screenshot, scrot, or import.

        Returns None on success, error message on failure.
        """
        # Try different screenshot tools in order of preference
        if shutil.which("gnome-screenshot"):
            cmd = ["gnome-screenshot", "-f", str(output_path)]
        elif shutil.which("scrot"):
            cmd = ["scrot", str(output_path)]
        elif shutil.which("import"):
            # ImageMagick's import
            cmd = ["import", "-window", "root", str(output_path)]
        elif shutil.which("grim"):
            # For Wayland
            cmd = ["grim", str(output_path)]
        else:
            return (
                "Error: No screenshot tool found. "
                "Install one of: gnome-screenshot, scrot, imagemagick, or grim"
            )

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                error = result.stderr.strip() or "Unknown error"
                return f"Error: Screenshot command failed - {error}"

            return None  # Success

        except subprocess.TimeoutExpired:
            return "Error: Screenshot timed out after 30 seconds"
        except Exception as e:
            return f"Error running screenshot command: {str(e)}"

    async def _capture_windows(self, output_path: Path, display: int) -> str | None:
        """
        Capture screenshot on Windows using PowerShell.

        Returns None on success, error message on failure.
        """
        # PowerShell script to capture screen
        ps_script = f'''
Add-Type -AssemblyName System.Windows.Forms
$screen = [System.Windows.Forms.Screen]::AllScreens[{display}]
$bounds = $screen.Bounds
$bitmap = New-Object System.Drawing.Bitmap($bounds.Width, $bounds.Height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
$bitmap.Save("{output_path}")
$graphics.Dispose()
$bitmap.Dispose()
'''

        try:
            result = subprocess.run(
                ["powershell", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                error = result.stderr.strip() or "Unknown error"
                return f"Error: PowerShell screenshot failed - {error}"

            return None  # Success

        except subprocess.TimeoutExpired:
            return "Error: Screenshot timed out after 30 seconds"
        except FileNotFoundError:
            return "Error: PowerShell not found"
        except Exception as e:
            return f"Error running PowerShell: {str(e)}"

    def get_screenshots_dir(self) -> Path:
        """Get the screenshots directory path."""
        return self._screenshots_dir

    def list_screenshots(self, limit: int = 10) -> list[Path]:
        """
        List recent screenshots.

        Args:
            limit: Maximum number of screenshots to return.

        Returns:
            List of screenshot paths, newest first.
        """
        screenshots = []
        for ext in self.SUPPORTED_FORMATS:
            screenshots.extend(self._screenshots_dir.glob(f"*.{ext}"))

        # Sort by modification time, newest first
        screenshots.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        return screenshots[:limit]

    def cleanup_old_screenshots(self, max_age_days: int = 7, max_count: int = 100) -> int:
        """
        Clean up old screenshots to prevent disk space issues.

        Args:
            max_age_days: Delete screenshots older than this.
            max_count: Keep at most this many screenshots.

        Returns:
            Number of files deleted.
        """
        from datetime import timedelta

        deleted = 0
        now = datetime.now()
        cutoff = now - timedelta(days=max_age_days)

        screenshots = self.list_screenshots(limit=1000)

        for i, path in enumerate(screenshots):
            try:
                mtime = datetime.fromtimestamp(path.stat().st_mtime)

                # Delete if too old or beyond max count
                if mtime < cutoff or i >= max_count:
                    path.unlink()
                    deleted += 1
                    logger.debug(f"Deleted old screenshot: {path}")
            except Exception as e:
                logger.warning(f"Failed to delete {path}: {e}")

        if deleted > 0:
            logger.info(f"Cleaned up {deleted} old screenshots")

        return deleted
