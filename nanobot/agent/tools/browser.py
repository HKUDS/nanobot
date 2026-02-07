"""Browser tool: Playwright-based web automation with screenshot support."""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool


class BrowserTool(Tool):
    """
    Browser automation using Playwright.
    
    Browser is lazily initialized on first use and reused across calls.
    """
    
    name = "browser"
    description = """Control a browser for web automation. Actions:
- navigate: Go to URL (params: url)
- click: Click element (params: selector)
- type: Type into field (params: selector, text)
- screenshot: Capture page (params: path optional)
- get_text: Get visible text (params: selector optional)
- close: Close browser session"""
    
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["navigate", "click", "type", "screenshot", "get_text", "close"],
                "description": "Action to perform"
            },
            "url": {"type": "string", "description": "URL for navigate"},
            "selector": {"type": "string", "description": "CSS selector"},
            "text": {"type": "string", "description": "Text for type action"},
            "path": {"type": "string", "description": "Screenshot path (optional)"}
        },
        "required": ["action"]
    }
    
    MAX_TEXT_LENGTH = 3000
    
    def __init__(self, workspace: Path | None = None):
        self._playwright = None
        self._browser = None
        self._page = None
        self.workspace = workspace or Path.cwd()
        self.screenshots_dir = self.workspace / "screenshots"
    
    async def _ensure_browser(self) -> None:
        """Lazily initialize browser on first use."""
        if self._page is not None:
            return
        
        from playwright.async_api import async_playwright
        
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._page = await self._browser.new_page()
        logger.debug("Browser initialized")
    
    async def _close_browser(self) -> None:
        """Close browser and cleanup resources."""
        if self._page:
            await self._page.close()
            self._page = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.debug("Browser closed")
    
    async def execute(self, action: str, **kwargs: Any) -> str:
        """Execute browser action."""
        handlers = {
            "navigate": lambda: self._navigate(kwargs.get("url", "")),
            "click": lambda: self._click(kwargs.get("selector", "")),
            "type": lambda: self._type(kwargs.get("selector", ""), kwargs.get("text", "")),
            "screenshot": lambda: self._screenshot(kwargs.get("path")),
            "get_text": lambda: self._get_text(kwargs.get("selector")),
        }
        
        try:
            if action == "close":
                await self._close_browser()
                return json.dumps({"status": "ok", "message": "Browser closed"})
            
            if action not in handlers:
                return json.dumps({"error": f"Unknown action: {action}"})
            
            await self._ensure_browser()
            return await handlers[action]()
        except Exception as e:
            logger.warning(f"Browser error: {e}")
            return json.dumps({"error": str(e)})
    
    async def _navigate(self, url: str) -> str:
        if not url:
            return json.dumps({"error": "url required"})
        
        await self._page.goto(url, wait_until="domcontentloaded")
        return json.dumps({
            "status": "ok",
            "url": self._page.url,
            "title": await self._page.title()
        })
    
    async def _click(self, selector: str) -> str:
        if not selector:
            return json.dumps({"error": "selector required"})
        
        await self._page.click(selector, timeout=5000)
        return json.dumps({"status": "ok", "clicked": selector})
    
    async def _type(self, selector: str, text: str) -> str:
        if not selector or not text:
            return json.dumps({"error": "selector and text required"})
        
        await self._page.fill(selector, text)
        return json.dumps({"status": "ok", "typed": len(text)})
    
    async def _screenshot(self, path: str | None) -> str:
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        
        filepath = Path(path) if path else (
            self.screenshots_dir / f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        )
        
        await self._page.screenshot(path=str(filepath), full_page=True)
        return json.dumps({"status": "ok", "path": str(filepath)})
    
    async def _get_text(self, selector: str | None) -> str:
        if selector:
            element = await self._page.query_selector(selector)
            if not element:
                return json.dumps({"error": f"Element not found: {selector}"})
            text = await element.inner_text()
        else:
            text = await self._page.inner_text("body")
        
        text = re.sub(r'\s+', ' ', text).strip()
        truncated = len(text) > self.MAX_TEXT_LENGTH
        
        return json.dumps({
            "status": "ok",
            "text": text[:self.MAX_TEXT_LENGTH] + "..." if truncated else text,
            "truncated": truncated
        })
