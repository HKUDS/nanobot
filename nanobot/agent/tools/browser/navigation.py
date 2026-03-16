"""Browser navigation tools."""

from __future__ import annotations

from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.browser.manager import BrowserManager


class BrowserNavigateTool(Tool):
    """Navigate to a URL."""
    
    name = "browser_navigate"
    description = "Navigate the browser to a specific URL. Waits for page to load."
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to navigate to. Must include protocol (http:// or https://)"
            },
            "wait_until": {
                "type": "string",
                "enum": ["load", "domcontentloaded", "networkidle", "commit"],
                "description": "When to consider navigation complete. 'networkidle' waits for no network connections for 500ms (good for SPAs). 'load' waits for load event. 'domcontentloaded' is faster but may miss lazy content.",
                "default": "networkidle"
            },
            "timeout": {
                "type": "integer",
                "description": "Navigation timeout in milliseconds. Default is 30000 (30 seconds).",
                "minimum": 1000,
                "maximum": 300000,
                "default": 30000
            }
        },
        "required": ["url"]
    }
    
    async def execute(
        self,
        url: str,
        wait_until: str = "networkidle",
        timeout: int = 30000,
        **kwargs: Any
    ) -> str:
        try:
            manager = BrowserManager.get_instance()
            page = await manager.get_page()
            
            # Ensure URL has protocol
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            
            response = await page.goto(
                url,
                wait_until=wait_until,  # type: ignore
                timeout=timeout
            )
            
            title = await page.title()
            final_url = page.url
            
            status_info = ""
            if response:
                status_info = f" (Status: {response.status})"
            
            return f"Navigated to: {final_url}{status_info}\nPage title: {title}"
            
        except Exception as e:
            return f"Error navigating to {url}: {str(e)}"


class BrowserGoBackTool(Tool):
    """Go back to previous page."""
    
    name = "browser_go_back"
    description = "Navigate back to the previous page in browser history."
    parameters = {
        "type": "object",
        "properties": {
            "wait_until": {
                "type": "string",
                "enum": ["load", "domcontentloaded", "networkidle"],
                "description": "When to consider navigation complete",
                "default": "networkidle"
            }
        }
    }
    
    async def execute(self, wait_until: str = "networkidle", **kwargs: Any) -> str:
        try:
            manager = BrowserManager.get_instance()
            page = await manager.get_page()
            
            await page.go_back(wait_until=wait_until)  # type: ignore
            
            title = await page.title()
            url = page.url
            
            return f"Went back to: {url}\nPage title: {title}"
            
        except Exception as e:
            return f"Error going back: {str(e)}"


class BrowserGoForwardTool(Tool):
    """Go forward to next page."""
    
    name = "browser_go_forward"
    description = "Navigate forward to the next page in browser history (if you previously went back)."
    parameters = {
        "type": "object",
        "properties": {
            "wait_until": {
                "type": "string",
                "enum": ["load", "domcontentloaded", "networkidle"],
                "description": "When to consider navigation complete",
                "default": "networkidle"
            }
        }
    }
    
    async def execute(self, wait_until: str = "networkidle", **kwargs: Any) -> str:
        try:
            manager = BrowserManager.get_instance()
            page = await manager.get_page()
            
            await page.go_forward(wait_until=wait_until)  # type: ignore
            
            title = await page.title()
            url = page.url
            
            return f"Went forward to: {url}\nPage title: {title}"
            
        except Exception as e:
            return f"Error going forward: {str(e)}"


class BrowserRefreshTool(Tool):
    """Refresh/reload current page."""
    
    name = "browser_refresh"
    description = "Refresh/reload the current page."
    parameters = {
        "type": "object",
        "properties": {
            "wait_until": {
                "type": "string",
                "enum": ["load", "domcontentloaded", "networkidle"],
                "description": "When to consider reload complete",
                "default": "networkidle"
            }
        }
    }
    
    async def execute(self, wait_until: str = "networkidle", **kwargs: Any) -> str:
        try:
            manager = BrowserManager.get_instance()
            page = await manager.get_page()
            
            await page.reload(wait_until=wait_until)  # type: ignore
            
            title = await page.title()
            url = page.url
            
            return f"Refreshed: {url}\nPage title: {title}"
            
        except Exception as e:
            return f"Error refreshing page: {str(e)}"


class BrowserCloseTool(Tool):
    """Close browser and cleanup."""
    
    name = "browser_close"
    description = "Close the browser, all its pages, and release all resources. Call this when you're done with browser automation."
    parameters = {
        "type": "object",
        "properties": {}
    }
    
    async def execute(self, **kwargs: Any) -> str:
        try:
            manager = BrowserManager.get_instance()
            await manager.close()
            return "Browser closed successfully. All resources released."
        except Exception as e:
            return f"Error closing browser: {str(e)}"
