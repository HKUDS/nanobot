"""Browser manager for managing Playwright instances."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nanobot.config.paths import get_workspace_path

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright

    from nanobot.agent.tools.browser.config import BrowserConfig


def is_running_in_docker() -> bool:
    """Detect if running inside a Docker container."""
    # Check for .dockerenv file
    if Path("/.dockerenv").exists():
        return True
    
    # Check cgroup
    try:
        cgroup = Path("/proc/1/cgroup").read_text()
        return "docker" in cgroup or "containerd" in cgroup
    except Exception:
        pass
    
    return False


class BrowserManager:
    """
    Singleton browser manager for managing Playwright browser instances.
    
    Features:
    - Lazy initialization
    - Multi-page support
    - Automatic resource cleanup
    - Docker-compatible launch args
    - Session isolation
    """
    
    _instance: BrowserManager | None = None
    _lock: asyncio.Lock | None = None
    
    def __new__(cls) -> BrowserManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._pages: dict[str, Page] = {}  # session_id -> Page
        self._default_page_id: str = "default"
        self._config: BrowserConfig | None = None
    
    @classmethod
    def get_instance(cls) -> BrowserManager:
        """Get the singleton instance."""
        return cls()
    
    @classmethod
    def get_lock(cls) -> asyncio.Lock:
        """Get the async lock for thread-safe operations."""
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        return cls._lock
    
    def _get_launch_args(self) -> dict[str, Any]:
        """Get browser launch arguments based on configuration."""
        args = []
        
        # Docker required args
        if self._config and self._config.no_sandbox:
            args.append("--no-sandbox")
        if self._config and self._config.disable_dev_shm:
            args.append("--disable-dev-shm-usage")
        
        # Additional stability args
        args.extend([
            "--disable-gpu",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-setuid-sandbox",
            "--disable-accelerated-2d-canvas",
            "--disable-accelerated-jpeg-decoding",
            "--disable-accelerated-mjpeg-decode",
            "--disable-accelerated-video-decode",
            "--disable-breakpad",
            "--disable-client-side-phishing-detection",
            "--disable-component-extensions-with-background-pages",
            "--disable-default-apps",
            "--disable-extensions",
            "--disable-features=Translate",
            "--disable-hang-monitor",
            "--disable-ipc-flooding-protection",
            "--disable-popup-blocking",
            "--disable-prompt-on-repost",
            "--disable-renderer-backgrounding",
            "--force-color-profile=srgb",
            "--metrics-recording-only",
            "--safebrowsing-disable-auto-update",
        ])
        
        return {
            "headless": self._config.headless if self._config else True,
            "args": args,
            "slow_mo": self._config.slow_mo if self._config else 0,
        }
    
    def _get_context_options(self) -> dict[str, Any]:
        """Get browser context options."""
        options: dict[str, Any] = {
            "viewport": self._config.viewport if self._config else {"width": 1280, "height": 720},
            "locale": self._config.locale if self._config else "en-US",
            "timezone_id": self._config.timezone if self._config else "America/New_York",
            "accept_downloads": self._config.accept_downloads if self._config else True,
            "bypass_csp": self._config.bypass_csp if self._config else False,
            "ignore_https_errors": self._config.ignore_https_errors if self._config else False,
        }
        
        if self._config and self._config.user_agent:
            options["user_agent"] = self._config.user_agent
        
        # Set download path
        if self._config:
            downloads_dir = self._config.downloads_dir
            downloads_dir.mkdir(parents=True, exist_ok=True)
            options["downloads_path"] = str(downloads_dir)
        
        return options
    
    async def initialize(self, config: BrowserConfig | None = None) -> None:
        """Initialize the browser with optional configuration."""
        async with self.get_lock():
            if self._browser is not None:
                return
            
            # Auto-detect Docker if not explicitly set
            if config and not config.docker_mode:
                config.docker_mode = is_running_in_docker()
                if config.docker_mode:
                    config.no_sandbox = True
                    config.disable_dev_shm = True
            
            self._config = config
            
            try:
                from playwright.async_api import async_playwright
                
                self._playwright = await async_playwright().start()
                
                # Launch browser based on type
                browser_type = self._config.browser_type if self._config else "chromium"
                launch_args = self._get_launch_args()
                
                if browser_type == "firefox":
                    self._browser = await self._playwright.firefox.launch(**launch_args)
                elif browser_type == "webkit":
                    self._browser = await self._playwright.webkit.launch(**launch_args)
                else:  # chromium (default)
                    self._browser = await self._playwright.chromium.launch(**launch_args)
                
                # Create context
                context_options = self._get_context_options()
                self._context = await self._browser.new_context(**context_options)
                
                # Create default page
                default_page = await self._context.new_page()
                default_page.set_default_timeout(
                    self._config.default_timeout if self._config else 30000
                )
                self._pages[self._default_page_id] = default_page
                
            except Exception as e:
                await self.close()
                raise RuntimeError(f"Failed to initialize browser: {e}") from e
    
    async def get_page(self, page_id: str | None = None) -> Page:
        """
        Get a page by ID, or the default page if no ID specified.
        
        Args:
            page_id: Optional page identifier for multi-page support
            
        Returns:
            Playwright Page object
        """
        await self.ensure_initialized()
        
        page_id = page_id or self._default_page_id
        
        async with self.get_lock():
            if page_id not in self._pages or self._pages[page_id].is_closed():
                # Create new page
                if self._context is None:
                    raise RuntimeError("Browser context not initialized")
                new_page = await self._context.new_page()
                new_page.set_default_timeout(
                    self._config.default_timeout if self._config else 30000
                )
                self._pages[page_id] = new_page
            
            return self._pages[page_id]
    
    async def new_page(self, page_id: str | None = None) -> Page:
        """Create a new page with optional ID."""
        await self.ensure_initialized()
        
        async with self.get_lock():
            if self._context is None:
                raise RuntimeError("Browser context not initialized")
            
            new_page = await self._context.new_page()
            new_page.set_default_timeout(
                self._config.default_timeout if self._config else 30000
            )
            
            # Generate ID if not provided
            if page_id is None:
                page_id = f"page_{len(self._pages)}"
            
            self._pages[page_id] = new_page
            return new_page
    
    async def close_page(self, page_id: str | None = None) -> bool:
        """Close a specific page."""
        page_id = page_id or self._default_page_id
        
        async with self.get_lock():
            if page_id in self._pages:
                page = self._pages[page_id]
                if not page.is_closed():
                    await page.close()
                del self._pages[page_id]
                return True
            return False
    
    async def list_pages(self) -> list[dict[str, Any]]:
        """List all open pages with their info."""
        await self.ensure_initialized()
        
        pages_info = []
        for page_id, page in self._pages.items():
            if not page.is_closed():
                try:
                    url = page.url
                    title = await page.title()
                    pages_info.append({
                        "id": page_id,
                        "url": url,
                        "title": title,
                    })
                except Exception:
                    # Page might be closing
                    pass
        
        return pages_info
    
    async def ensure_initialized(self) -> None:
        """Ensure browser is initialized."""
        if self._browser is None:
            await self.initialize()
    
    async def close(self) -> None:
        """Close browser and cleanup all resources."""
        async with self.get_lock():
            # Close all pages
            for page in self._pages.values():
                try:
                    if not page.is_closed():
                        await page.close()
                except Exception:
                    pass
            self._pages.clear()
            
            # Close context
            if self._context:
                try:
                    await self._context.close()
                except Exception:
                    pass
                self._context = None
            
            # Close browser
            if self._browser:
                try:
                    await self._browser.close()
                except Exception:
                    pass
                self._browser = None
            
            # Stop playwright
            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None
    
    @property
    def is_initialized(self) -> bool:
        """Check if browser is initialized."""
        return self._browser is not None and self._context is not None
    
    @property
    def config(self) -> BrowserConfig | None:
        """Get current configuration."""
        return self._config
