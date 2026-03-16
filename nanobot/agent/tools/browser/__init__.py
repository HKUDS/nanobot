"""Browser automation tools using Playwright."""

from nanobot.agent.tools.browser.config import BrowserConfig
from nanobot.agent.tools.browser.manager import BrowserManager
from nanobot.agent.tools.browser.navigation import (
    BrowserCloseTool,
    BrowserGoBackTool,
    BrowserGoForwardTool,
    BrowserNavigateTool,
    BrowserRefreshTool,
)
from nanobot.agent.tools.browser.interaction import (
    BrowserClickTool,
    BrowserGetTextTool,
    BrowserScrollTool,
    BrowserTypeTool,
    BrowserWaitTool,
)
from nanobot.agent.tools.browser.javascript import (
    BrowserAddScriptTool,
    BrowserEvaluateHandleTool,
    BrowserEvaluateTool,
)
from nanobot.agent.tools.browser.screenshot import (
    BrowserPdfTool,
    BrowserScreenshotTool,
)

__all__ = [
    # Config & Manager
    "BrowserConfig",
    "BrowserManager",
    # Navigation
    "BrowserNavigateTool",
    "BrowserGoBackTool",
    "BrowserGoForwardTool",
    "BrowserRefreshTool",
    "BrowserCloseTool",
    # Interaction
    "BrowserClickTool",
    "BrowserTypeTool",
    "BrowserGetTextTool",
    "BrowserWaitTool",
    "BrowserScrollTool",
    # Screenshot
    "BrowserScreenshotTool",
    "BrowserPdfTool",
    # JavaScript
    "BrowserEvaluateTool",
    "BrowserEvaluateHandleTool",
    "BrowserAddScriptTool",
]
