"""Browser configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class BrowserConfig(BaseModel):
    """Browser automation configuration."""

    enabled: bool = False
    headless: bool = True
    browser_type: Literal["chromium", "firefox", "webkit"] = "chromium"
    viewport_width: int = 1280
    viewport_height: int = 720
    default_timeout: int = 30000
    slow_mo: int = 0  # Slow down operations by specified milliseconds (useful for debugging)
    
    # Paths
    screenshots_path: str = "~/workspace/screenshots"
    downloads_path: str = "~/workspace/downloads"
    
    # Docker/Container settings
    docker_mode: bool = False  # Auto-detected if not set
    no_sandbox: bool = True  # Required for Docker
    disable_dev_shm: bool = True  # Disable /dev/shm usage (for Docker)
    
    # Behavior
    user_agent: str | None = None  # Custom User-Agent
    locale: str = "en-US"
    timezone: str = "America/New_York"
    
    # Security
    accept_downloads: bool = True
    bypass_csp: bool = False  # Bypass Content-Security-Policy
    ignore_https_errors: bool = False
    
    @property
    def viewport(self) -> dict[str, int]:
        """Get viewport size as dict."""
        return {"width": self.viewport_width, "height": self.viewport_height}
    
    @property
    def screenshots_dir(self) -> Path:
        """Get screenshots directory path."""
        return Path(self.screenshots_path).expanduser()
    
    @property
    def downloads_dir(self) -> Path:
        """Get downloads directory path."""
        return Path(self.downloads_path).expanduser()
