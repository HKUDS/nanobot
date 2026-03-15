"""Browser automation tools using Playwright.

This module provides browser automation capabilities through a unified
browser_action tool that supports multiple browser operations including:
- launch: Start a browser instance
- new_session: Create an isolated browser context
- close_session: Close a specific browser session
- navigate: Navigate to a URL
- click: Click on an element
- type: Type text into an element
- check: Check/uncheck a checkbox
- screenshot: Capture a screenshot (returns multimodal result)
- evaluate: Execute JavaScript
- console: Get console logs
- network: Get network requests
- wait: Wait for an element or condition
- close: Close the browser

Example:
    # Launch browser and navigate
    await browser_action(action="launch")
    await browser_action(action="navigate", url="https://example.com")
    
    # Take a screenshot (returns ToolResult with image)
    result = await browser_action(action="screenshot")
    # result is ToolResult with images=[{"type": "image_url", ...}]
    
    # Click an element
    await browser_action(action="click", selector="#submit-button")
"""

from __future__ import annotations

import asyncio
import base64
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool, ToolResult


# Type alias for Playwright objects
try:
    from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    Browser = BrowserContext = Page = Playwright = None


@dataclass
class BrowserSession:
    """Browser session with isolated context.
    
    Each session has its own BrowserContext, providing:
    - Independent cookies and storage
    - Independent session state
    - Isolated browsing data
    """
    id: str
    context: BrowserContext
    page: Page


class BrowserManager:
    """Manages browser instances and sessions.
    
    Uses a single Browser instance with multiple BrowserContext objects
    for efficient resource usage while maintaining session isolation.
    
    Attributes:
        max_contexts: Maximum number of concurrent contexts (default: 5)
        session_timeout: Session timeout in seconds (default: 1800 = 30 minutes)
    """
    
    def __init__(self, max_contexts: int = 5, session_timeout: int = 1800):
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._sessions: dict[str, BrowserSession] = {}
        self._max_contexts = max_contexts
        self._lock = asyncio.Lock()
        self._browser_installed: bool | None = None
        self._session_timeout = session_timeout  # 30 minutes default
        self._session_last_used: dict[str, float] = {}  # Track session activity
    
    def _check_browser_installed(self) -> bool:
        """Check if Chromium browser is installed for Playwright.
        
        Returns:
            True if browser is installed, False otherwise.
        """
        try:
            # Try to get browser path - this will fail if not installed
            from playwright._impl._driver import get_driver
            driver = get_driver()
            # Check if chromium is available
            return True
        except Exception:
            return False
    
    async def _install_browser(self) -> None:
        """Install Chromium browser for Playwright.
        
        This runs the playwright install command to download Chromium.
        Note: This is a synchronous operation that may take some time.
        """
        import loguru
        
        loguru.logger.info("Installing Chromium for Playwright (this may take a minute)...")
        
        # Run in thread pool to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._install_browser_sync)
        
        loguru.logger.info("Chromium installed successfully")
    
    def _install_browser_sync(self) -> None:
        """Synchronous browser installation."""
        try:
            # Use subprocess to run playwright install
            result = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True,
                text=True,
                timeout=300  # 5 minutes timeout
            )
            if result.returncode != 0:
                raise RuntimeError(f"Failed to install Chromium: {result.stderr}")
        except subprocess.TimeoutExpired:
            raise RuntimeError("Chromium installation timed out")
        except FileNotFoundError:
            raise RuntimeError("Playwright not found. Please install: pip install playwright")
    
    async def launch(self) -> None:
        """Launch the browser if not already running.
        
        If browser is not installed, automatically installs it first.
        """
        async with self._lock:
            if not self._playwright:
                self._playwright = await async_playwright().start()
            
            if not self._browser:
                try:
                    self._browser = await self._playwright.chromium.launch()
                except Exception as e:
                    error_msg = str(e).lower()
                    # Check if it's a browser not installed error
                    if any(keyword in error_msg for keyword in [
                        "browser", "executable", "chromium", "not found"
                    ]):
                        # Try to install browser and retry
                        await self._install_browser()
                        self._browser = await self._playwright.chromium.launch()
                    else:
                        raise
    
    async def create_session(self, session_id: str | None = None) -> BrowserSession:
        """Create a new isolated browser session.
        
        Args:
            session_id: Optional session ID. If not provided, a UUID will be generated.
            
        Returns:
            BrowserSession with isolated context and page.
            
        Raises:
            RuntimeError: If max contexts reached or browser not launched.
        """
        await self.launch()
        
        async with self._lock:
            # Clean up expired sessions before creating new one
            await self._cleanup_expired_sessions()
            
            if len(self._sessions) >= self._max_contexts:
                raise RuntimeError(f"Max browser contexts ({self._max_contexts}) reached. Please close some sessions.")
            
            session_id = session_id or str(uuid.uuid4())[:8]
            context = await self._browser.new_context()
            page = await context.new_page()
            
            session = BrowserSession(id=session_id, context=context, page=page)
            self._sessions[session_id] = session
            self._session_last_used[session_id] = time.time()
            return session
    
    async def _cleanup_expired_sessions(self) -> None:
        """Clean up expired sessions based on timeout.
        
        This method should be called with the lock held.
        """
        now = time.time()
        expired = [
            sid for sid, last_used in self._session_last_used.items()
            if now - last_used > self._session_timeout
        ]
        
        for session_id in expired:
            logger.info(f"Closing expired browser session: {session_id}")
            if session := self._sessions.pop(session_id, None):
                await session.context.close()
            self._session_last_used.pop(session_id, None)
    
    def update_session_activity(self, session_id: str) -> None:
        """Update the last used time for a session.
        
        Args:
            session_id: The session ID to update.
        """
        if session_id in self._sessions:
            self._session_last_used[session_id] = time.time()
    
    def get_session(self, session_id: str) -> BrowserSession | None:
        """Get an existing session by ID."""
        return self._sessions.get(session_id)
    
    async def close_session(self, session_id: str) -> bool:
        """Close a specific session.
        
        Args:
            session_id: The session ID to close.
            
        Returns:
            True if session was found and closed, False otherwise.
        """
        async with self._lock:
            if session := self._sessions.pop(session_id, None):
                await session.context.close()
                self._session_last_used.pop(session_id, None)
                return True
            return False
    
    async def close(self) -> None:
        """Close all sessions and the browser."""
        async with self._lock:
            for session in list(self._sessions.values()):
                await session.context.close()
            self._sessions.clear()
            self._session_last_used.clear()
            
            if self._browser:
                await self._browser.close()
                self._browser = None
            
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None
    
    @property
    def session_count(self) -> int:
        """Get the number of active sessions."""
        return len(self._sessions)
    
    def get_sessions(self) -> dict[str, BrowserSession]:
        """Get all active sessions.
        
        Returns:
            A copy of the sessions dictionary to prevent external modification.
        """
        return self._sessions.copy()
    
    def get_session_last_used(self, session_id: str) -> float | None:
        """Get the last used timestamp for a session.
        
        Args:
            session_id: The session ID to query.
            
        Returns:
            The timestamp of last use, or None if session not found.
        """
        return self._session_last_used.get(session_id)
    
    def get_sessions(self) -> dict[str, BrowserSession]:
        """Get all active sessions.
        
        Returns:
            A copy of the sessions dictionary to prevent external modification.
        """
        return self._sessions.copy()
    
    def get_session_last_used(self, session_id: str) -> float | None:
        """Get the last used timestamp for a session.
        
        Args:
            session_id: The session ID to query.
            
        Returns:
            The timestamp of last use, or None if session not found.
        """
        return self._session_last_used.get(session_id)


class BrowserActionTool(Tool):
    """Unified browser automation tool.
    
    Provides a single tool interface for all browser operations,
    reducing tool registration complexity.
    
    Actions:
        - launch: Start the browser (no parameters)
        - new_session: Create isolated context (optional: session parameter)
        - close_session: Close a session (required: session parameter)
        - list_sessions: List all active sessions (no parameters)
        - navigate: Navigate to URL (required: url, optional: session)
        - click: Click element (required: selector, optional: session)
        - type: Type text (required: selector, text, optional: session)
        - check: Toggle checkbox (required: selector, checked, optional: session)
        - screenshot: Capture screenshot (optional: session)
        - evaluate: Execute JS (required: script, optional: session)
        - console: Get console logs (optional: session)
        - network: Get network requests (optional: session)
        - wait: Wait for element (required: selector, optional: session, timeout)
        - close: Close browser (no parameters)
    
    Session Management:
        - Default session 'default' is auto-created on first use
        - All results include the active session ID
        - Sessions auto-expire after 30 minutes of inactivity
    """
    
    # Default session ID for convenience
    DEFAULT_SESSION_ID = "default"
    
    def __init__(self, manager: BrowserManager | None = None, enable_vision: bool = True, session_timeout: int = 1800):
        """Initialize the browser action tool.
        
        Args:
            manager: Optional BrowserManager instance. If not provided, creates a new one.
            enable_vision: Whether to enable vision capabilities (screenshot returns images).
                          If False, screenshots return text descriptions only.
                          This should be set based on whether the LLM provider supports vision.
            session_timeout: Session timeout in seconds (default: 1800 = 30 minutes).
        """
        self._manager = manager or BrowserManager(session_timeout=session_timeout)
        self._console_logs: dict[str, list[dict]] = {}
        self._network_logs: dict[str, list[dict]] = {}
        self._enable_vision = enable_vision
        self._current_session_id: str | None = None
    
    @property
    def name(self) -> str:
        return "browser_action"
    
    @property
    def description(self) -> str:
        """Get the tool description for the LLM.
        
        The description varies based on whether vision is enabled, to inform
        the LLM about the screenshot behavior.
        """
        vision_note = (
            "Screenshot returns image for multimodal models."
            if self._enable_vision
            else "Screenshot returns text description only (vision disabled)."
        )
        
        return f"""Control browser for automation testing.

Session Management:
- Default session '{self.DEFAULT_SESSION_ID}' is auto-created on first use
- Use 'new_session' to create isolated sessions
- Use 'close_session' to close specific sessions
- Use 'list_sessions' to see all active sessions
- All results include the active session ID
- Sessions auto-expire after 30 minutes of inactivity

Actions:
- launch: Start the browser
- new_session: Create isolated context (optional: session parameter)
- close_session: Close a session (required: session parameter)
- list_sessions: List all active sessions
- navigate: Navigate to URL (required: url, optional: session)
- click: Click element (required: selector, optional: session)
- type: Type text (required: selector, text, optional: session)
- check: Toggle checkbox (required: selector, checked, optional: session)
- screenshot: Capture screenshot (optional: session)
- evaluate: Execute JS (required: script, optional: session)
- console: Get console logs (optional: session)
- network: Get network requests (optional: session)
- wait: Wait for element (required: selector, optional: session, timeout)
- close: Close browser

{vision_note}"""
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "launch", "new_session", "close_session", "list_sessions",
                        "navigate", "click", "type", "check", "screenshot",
                        "evaluate", "console", "network", "wait", "close"
                    ],
                    "description": "The browser action to perform"
                },
                "session": {
                    "type": "string",
                    "description": "Session ID for multi-browser support"
                },
                "url": {
                    "type": "string",
                    "description": "URL to navigate to (for navigate action)"
                },
                "selector": {
                    "type": "string",
                    "description": "CSS selector for element interaction"
                },
                "text": {
                    "type": "string",
                    "description": "Text to type (for type action)"
                },
                "checked": {
                    "type": "boolean",
                    "description": "Check state (for check action)"
                },
                "script": {
                    "type": "string",
                    "description": "JavaScript to execute (for evaluate action)"
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in milliseconds (for wait action)",
                    "default": 30000
                },
            },
            "required": ["action"]
        }
    
    async def execute(self, action: str, **kwargs: Any) -> ToolResult | str:
        """Execute the browser action.
        
        Args:
            action: The browser action to perform.
            **kwargs: Action-specific parameters.
            
        Returns:
            ToolResult with the action result. All results include the session ID.
        """
        if not PLAYWRIGHT_AVAILABLE:
            return ToolResult(
                content="Error: Playwright is not installed. Install with: pip install nanobot[browser]",
                images=None
            )
        
        session_id = kwargs.get("session")
        
        # Get or create session for actions that need it
        session: BrowserSession | None = None
        if action in ("launch", "close"):
            # These operations don't need a session
            pass
        elif action == "new_session":
            # Explicitly create a new session
            return await self._handle_new_session(session_id)
        elif action == "close_session":
            # Explicitly close a session
            return await self._handle_close_session(session_id)
        elif action == "list_sessions":
            # List all active sessions
            return await self._handle_list_sessions()
        else:
            # Other actions need a session
            if session_id:
                # Use the specified session
                session = self._manager.get_session(session_id)
                if not session:
                    return ToolResult(
                        content=f"Error: Session '{session_id}' not found. Use 'new_session' to create one.",
                        images=None
                    )
            else:
                # Use default session
                session = self._manager.get_session(self.DEFAULT_SESSION_ID)
                if not session:
                    # Auto-create default session
                    try:
                        session = await self._manager.create_session(self.DEFAULT_SESSION_ID)
                        self._setup_console_logging(session)
                        logger.info(f"Auto-created default browser session: {self.DEFAULT_SESSION_ID}")
                    except Exception as e:
                        return ToolResult(content=f"Error creating default session: {str(e)}", images=None)
                
                session_id = self.DEFAULT_SESSION_ID
                self._current_session_id = session_id
        
        # Update session activity timestamp
        if session_id:
            self._manager.update_session_activity(session_id)
        
        # Execute the action
        try:
            # Remove session from kwargs to avoid duplicate parameter error
            action_kwargs = {k: v for k, v in kwargs.items() if k != "session"}
            
            match action:
                case "launch":
                    result = await self._handle_launch()
                case "navigate":
                    result = await self._handle_navigate(session, **action_kwargs)
                case "click":
                    result = await self._handle_click(session, **action_kwargs)
                case "type":
                    result = await self._handle_type(session, **action_kwargs)
                case "check":
                    result = await self._handle_check(session, **action_kwargs)
                case "screenshot":
                    result = await self._handle_screenshot(session)
                case "evaluate":
                    result = await self._handle_evaluate(session, **action_kwargs)
                case "console":
                    result = await self._handle_console(session_id)
                case "network":
                    result = await self._handle_network(session_id)
                case "wait":
                    result = await self._handle_wait(session, **action_kwargs)
                case "close":
                    result = await self._handle_close()
                case _:
                    return ToolResult(content=f"Unknown action: {action}", images=None)
            
            # Include session ID in result for actions that use a session
            if session_id and isinstance(result, ToolResult):
                result.content = f"[Session: {session_id}] {result.content}"
            
            return result
        except Exception as e:
            return ToolResult(content=f"Error: {str(e)}", images=None)
    
    async def _handle_launch(self) -> ToolResult:
        """Launch the browser."""
        await self._manager.launch()
        return ToolResult(content="Browser launched successfully", images=None)
    
    async def _handle_new_session(self, session_id: str | None) -> ToolResult:
        """Create a new browser session."""
        session = await self._manager.create_session(session_id)
        # Set up console logging for this session
        self._setup_console_logging(session)
        return ToolResult(
            content=f"Created new session: {session.id}",
            images=None
        )
    
    async def _handle_close_session(self, session_id: str | None) -> ToolResult:
        """Close a browser session."""
        if not session_id:
            return ToolResult(content="Error: session_id required", images=None)
        
        success = await self._manager.close_session(session_id)
        if success:
            self._console_logs.pop(session_id, None)
            self._network_logs.pop(session_id, None)
            return ToolResult(content=f"Closed session: {session_id}", images=None)
        return ToolResult(content=f"Session not found: {session_id}", images=None)
    
    async def _handle_navigate(self, session: BrowserSession, **kwargs) -> ToolResult:
        """Navigate to a URL."""
        url = kwargs.get("url")
        if not url:
            return ToolResult(content="Error: url required", images=None)
        
        await session.page.goto(url)
        title = await session.page.title()
        return ToolResult(
            content=f"Navigated to {url}. Page title: {title}",
            images=None
        )
    
    async def _handle_click(self, session: BrowserSession, **kwargs) -> ToolResult:
        """Click an element."""
        selector = kwargs.get("selector")
        if not selector:
            return ToolResult(content="Error: selector required", images=None)
        
        await session.page.click(selector)
        return ToolResult(content=f"Clicked element: {selector}", images=None)
    
    async def _handle_type(self, session: BrowserSession, **kwargs) -> ToolResult:
        """Type text into an element."""
        selector = kwargs.get("selector")
        text = kwargs.get("text")
        
        if not selector:
            return ToolResult(content="Error: selector required", images=None)
        if text is None:
            return ToolResult(content="Error: text required", images=None)
        
        await session.page.fill(selector, text)
        return ToolResult(content=f"Typed text into: {selector}", images=None)
    
    async def _handle_check(self, session: BrowserSession, **kwargs) -> ToolResult:
        """Check or uncheck a checkbox."""
        selector = kwargs.get("selector")
        checked = kwargs.get("checked", True)
        
        if not selector:
            return ToolResult(content="Error: selector required", images=None)
        
        await session.page.set_checked(selector, checked)
        state = "checked" if checked else "unchecked"
        return ToolResult(content=f"Set {selector} to {state}", images=None)
    
    async def _handle_screenshot(self, session: BrowserSession) -> ToolResult:
        """Capture a screenshot.
        
        Returns:
            ToolResult with image data if vision is enabled, otherwise text description.
        """
        if not session:
            return ToolResult(content="Error: No active session", images=None)
        
        screenshot_bytes = await session.page.screenshot()
        
        if self._enable_vision:
            # Return image data for multimodal models
            b64 = base64.b64encode(screenshot_bytes).decode()
            return ToolResult(
                content="Screenshot captured",
                images=[{
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"}
                }]
            )
        else:
            # Return text description when vision is disabled
            return ToolResult(
                content="Screenshot captured (vision disabled - image not sent to model)",
                images=None
            )
    
    async def _handle_evaluate(self, session: BrowserSession, **kwargs) -> ToolResult:
        """Execute JavaScript."""
        script = kwargs.get("script")
        if not script:
            return ToolResult(content="Error: script required", images=None)
        
        result = await session.page.evaluate(script)
        return ToolResult(content=f"Script result: {result}", images=None)
    
    async def _handle_console(self, session_id: str | None) -> ToolResult:
        """Get console logs for a session."""
        if not session_id:
            return ToolResult(content="Error: session_id required", images=None)
        
        logs = self._console_logs.get(session_id, [])
        if not logs:
            return ToolResult(content="No console logs captured", images=None)
        
        formatted = "\n".join([
            f"[{log.get('type', 'log')}] {log.get('text', '')}"
            for log in logs
        ])
        return ToolResult(content=formatted, images=None)
    
    async def _handle_network(self, session_id: str | None) -> ToolResult:
        """Get network requests for a session."""
        if not session_id:
            return ToolResult(content="Error: session_id required", images=None)
        
        logs = self._network_logs.get(session_id, [])
        if not logs:
            return ToolResult(content="No network requests captured", images=None)
        
        formatted = "\n".join([
            f"{log.get('method', 'GET')} {log.get('url', '')} - {log.get('status', '')}"
            for log in logs
        ])
        return ToolResult(content=formatted, images=None)
    
    async def _handle_wait(self, session: BrowserSession, **kwargs) -> ToolResult:
        """Wait for an element."""
        selector = kwargs.get("selector")
        timeout = kwargs.get("timeout", 30000)
        
        if not selector:
            return ToolResult(content="Error: selector required", images=None)
        
        await session.page.wait_for_selector(selector, timeout=timeout)
        return ToolResult(content=f"Element found: {selector}", images=None)
    
    async def _handle_close(self) -> ToolResult:
        """Close the browser and all sessions."""
        await self._manager.close()
        self._console_logs.clear()
        self._network_logs.clear()
        self._current_session_id = None
        return ToolResult(content="Browser closed", images=None)
    
    async def _handle_list_sessions(self) -> ToolResult:
        """List all active browser sessions.
        
        Returns:
            ToolResult with a list of active session IDs.
        """
        sessions = self._manager.get_sessions()
        if not sessions:
            return ToolResult(content="No active sessions", images=None)
        
        lines = ["Active sessions:"]
        for session_id, session in sessions.items():
            last_used = self._manager.get_session_last_used(session_id)
            if last_used:
                import datetime
                last_used_str = datetime.datetime.fromtimestamp(last_used).strftime("%H:%M:%S")
                lines.append(f"  - {session_id} (last used: {last_used_str})")
            else:
                lines.append(f"  - {session_id}")
        
        return ToolResult(content="\n".join(lines), images=None)
    
    def _setup_console_logging(self, session: BrowserSession) -> None:
        """Set up console and network logging for a session."""
        session_id = session.id
        
        async def handle_console(msg):
            self._console_logs.setdefault(session_id, []).append({
                "type": msg.type,
                "text": msg.text
            })
        
        async def handle_request(request):
            self._network_logs.setdefault(session_id, []).append({
                "method": request.method,
                "url": request.url,
                "resource_type": request.resource_type
            })
        
        async def handle_response(response):
            if session_id in self._network_logs:
                for log in self._network_logs[session_id]:
                    if log.get("url") == response.url:
                        log["status"] = response.status
                        break
        
        session.page.on("console", handle_console)
        session.page.on("request", handle_request)
        session.page.on("response", handle_response)