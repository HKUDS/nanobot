"""Browser interaction tools."""

from __future__ import annotations

from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.browser.manager import BrowserManager


class BrowserClickTool(Tool):
    """Click on an element."""
    
    name = "browser_click"
    description = "Click on an element identified by CSS selector or text content. Supports single click, double click, and right click."
    parameters = {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": "CSS selector to find the element (e.g., '#button-id', '.class-name', 'button:nth-child(2)', '[data-testid=\"submit\"]'). Preferred method."
            },
            "text": {
                "type": "string",
                "description": "Text content to find and click. Alternative to selector. Finds element containing this text."
            },
            "button": {
                "type": "string",
                "enum": ["left", "right", "middle"],
                "description": "Mouse button to click",
                "default": "left"
            },
            "double_click": {
                "type": "boolean",
                "description": "Perform double click",
                "default": False
            },
            "timeout": {
                "type": "integer",
                "description": "Maximum time to wait for element in milliseconds",
                "default": 10000
            }
        },
        "required": []
    }
    
    async def execute(
        self,
        selector: str | None = None,
        text: str | None = None,
        button: str = "left",
        double_click: bool = False,
        timeout: int = 10000,
        **kwargs: Any
    ) -> str:
        if not selector and not text:
            return "Error: Either 'selector' or 'text' must be provided"
        
        try:
            manager = BrowserManager.get_instance()
            page = await manager.get_page()
            
            click_options = {
                "button": button,
                "timeout": timeout
            }
            
            if double_click:
                click_options["click_count"] = 2
            
            if selector:
                await page.click(selector, **click_options)
                action = "Double-clicked" if double_click else "Clicked"
                return f"{action} element with selector: {selector}"
            
            if text:
                # Use get_by_text for text-based selection
                locator = page.get_by_text(text)
                await locator.click(**click_options)
                action = "Double-clicked" if double_click else "Clicked"
                return f"{action} element with text: {text}"
                
        except Exception as e:
            return f"Error clicking: {str(e)}"


class BrowserTypeTool(Tool):
    """Type text into an input field."""
    
    name = "browser_type"
    description = "Type text into an input field, text area, or contenteditable element. Can clear existing text first and optionally submit the form."
    parameters = {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": "CSS selector for the input field (e.g., 'input[name=\"email\"]', '#search-box', 'textarea')"
            },
            "text": {
                "type": "string",
                "description": "Text to type into the field"
            },
            "clear_first": {
                "type": "boolean",
                "description": "Clear the field before typing (select all and delete)",
                "default": True
            },
            "submit": {
                "type": "boolean",
                "description": "Press Enter after typing (useful for search boxes and forms)",
                "default": False
            },
            "delay": {
                "type": "integer",
                "description": "Delay between keystrokes in milliseconds. 0 for instant typing.",
                "minimum": 0,
                "maximum": 1000,
                "default": 0
            },
            "timeout": {
                "type": "integer",
                "description": "Maximum time to wait for element in milliseconds",
                "default": 10000
            }
        },
        "required": ["selector", "text"]
    }
    
    async def execute(
        self,
        selector: str,
        text: str,
        clear_first: bool = True,
        submit: bool = False,
        delay: int = 0,
        timeout: int = 10000,
        **kwargs: Any
    ) -> str:
        try:
            manager = BrowserManager.get_instance()
            page = await manager.get_page()
            
            locator = page.locator(selector)
            
            # Wait for element to be visible
            await locator.wait_for(state="visible", timeout=timeout)
            
            if clear_first:
                await locator.fill("")  # Clear first
            
            if delay > 0:
                await locator.press_sequentially(text, delay=delay)
            else:
                await locator.fill(text)
            
            result = f"Typed '{text[:50]}{'...' if len(text) > 50 else ''}' into {selector}"
            
            if submit:
                await locator.press("Enter")
                result += " and submitted"
            
            return result
            
        except Exception as e:
            return f"Error typing: {str(e)}"


class BrowserGetTextTool(Tool):
    """Get text content from page or element."""
    
    name = "browser_get_text"
    description = "Extract text content from the entire page or a specific element. Useful for reading page content, article text, or specific sections."
    parameters = {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": "CSS selector to get text from specific element. If not provided, gets all text from the page body."
            },
            "max_length": {
                "type": "integer",
                "description": "Maximum characters to return. Longer content will be truncated.",
                "minimum": 100,
                "maximum": 50000,
                "default": 5000
            },
            "include_hidden": {
                "type": "boolean",
                "description": "Include hidden elements' text (default: false, only visible text)",
                "default": False
            }
        }
    }
    
    async def execute(
        self,
        selector: str | None = None,
        max_length: int = 5000,
        include_hidden: bool = False,
        **kwargs: Any
    ) -> str:
        try:
            manager = BrowserManager.get_instance()
            page = await manager.get_page()
            
            if selector:
                # Get text from specific element
                locator = page.locator(selector)
                count = await locator.count()
                
                if count == 0:
                    return f"Error: No element found with selector '{selector}'"
                
                if include_hidden:
                    text = await locator.inner_text()
                else:
                    text = await locator.inner_text()
            else:
                # Get body text
                body = page.locator("body")
                text = await body.inner_text()
            
            # Clean up whitespace
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            text = "\n".join(lines)
            
            # Truncate if needed
            if len(text) > max_length:
                truncated = text[:max_length]
                return f"{truncated}\n\n... [truncated, total length: {len(text)} characters]"
            
            return text or "(No text found)"
            
        except Exception as e:
            return f"Error getting text: {str(e)}"


class BrowserWaitTool(Tool):
    """Wait for element, text, or time."""
    
    name = "browser_wait"
    description = "Wait for an element to appear, specific text to be visible, or just wait for a specified time. Useful for AJAX content, loading states, or animations."
    parameters = {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": "CSS selector to wait for. Element must become visible."
            },
            "text": {
                "type": "string",
                "description": "Text content to wait for on the page."
            },
            "state": {
                "type": "string",
                "enum": ["visible", "hidden", "attached", "detached"],
                "description": "Element state to wait for (only used with selector)",
                "default": "visible"
            },
            "timeout": {
                "type": "integer",
                "description": "Maximum time to wait in milliseconds",
                "minimum": 100,
                "maximum": 300000,
                "default": 10000
            },
            "delay": {
                "type": "integer",
                "description": "Fixed delay to wait in milliseconds (alternative to selector/text). Simple sleep."
            }
        }
    }
    
    async def execute(
        self,
        selector: str | None = None,
        text: str | None = None,
        state: str = "visible",
        timeout: int = 10000,
        delay: int | None = None,
        **kwargs: Any
    ) -> str:
        try:
            import asyncio
            
            manager = BrowserManager.get_instance()
            page = await manager.get_page()
            
            # Fixed delay mode
            if delay is not None:
                await asyncio.sleep(delay / 1000)
                return f"Waited for {delay}ms"
            
            # Selector wait mode
            if selector:
                locator = page.locator(selector)
                await locator.wait_for(state=state, timeout=timeout)  # type: ignore
                return f"Element '{selector}' became {state}"
            
            # Text wait mode
            if text:
                # Wait for text to appear
                await page.wait_for_selector(f"text={text}", timeout=timeout)
                return f"Text '{text}' appeared on page"
            
            return "Error: No wait condition specified (provide selector, text, or delay)"
            
        except Exception as e:
            if "Timeout" in str(e):
                return f"Timeout waiting for condition: {str(e)}"
            return f"Error waiting: {str(e)}"


class BrowserScrollTool(Tool):
    """Scroll the page."""
    
    name = "browser_scroll"
    description = "Scroll the page or a specific element. Can scroll by amount, to element, or to position."
    parameters = {
        "type": "object",
        "properties": {
            "direction": {
                "type": "string",
                "enum": ["down", "up", "left", "right", "to", "to_bottom", "to_top"],
                "description": "Scroll direction or mode"
            },
            "amount": {
                "type": "integer",
                "description": "Pixels to scroll (for down/up/left/right)",
                "default": 500
            },
            "selector": {
                "type": "string",
                "description": "CSS selector to scroll into view (for 'to' direction)"
            },
            "smooth": {
                "type": "boolean",
                "description": "Use smooth scrolling",
                "default": True
            }
        },
        "required": ["direction"]
    }
    
    async def execute(
        self,
        direction: str,
        amount: int = 500,
        selector: str | None = None,
        smooth: bool = True,
        **kwargs: Any
    ) -> str:
        try:
            manager = BrowserManager.get_instance()
            page = await manager.get_page()
            
            behavior = "smooth" if smooth else "auto"
            
            if direction == "to" and selector:
                # Scroll element into view
                element = page.locator(selector)
                await element.scroll_into_view_if_needed()
                return f"Scrolled to element: {selector}"
            
            elif direction == "to_bottom":
                await page.evaluate(f"window.scrollTo({{ top: document.body.scrollHeight, behavior: '{behavior}' }})")
                return "Scrolled to bottom of page"
            
            elif direction == "to_top":
                await page.evaluate(f"window.scrollTo({{ top: 0, behavior: '{behavior}' }})")
                return "Scrolled to top of page"
            
            elif direction in ("down", "up", "left", "right"):
                # Map directions to scroll values
                scroll_map = {
                    "down": (0, amount),
                    "up": (0, -amount),
                    "right": (amount, 0),
                    "left": (-amount, 0)
                }
                x, y = scroll_map[direction]
                await page.evaluate(f"window.scrollBy({{ left: {x}, top: {y}, behavior: '{behavior}' }})")
                return f"Scrolled {direction} by {amount}px"
            
            else:
                return f"Error: Invalid direction '{direction}'"
                
        except Exception as e:
            return f"Error scrolling: {str(e)}"
