"""JavaScript execution tools for browser."""

from __future__ import annotations

import json
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.browser.manager import BrowserManager


class BrowserEvaluateTool(Tool):
    """Execute JavaScript in the browser page context."""
    
    name = "browser_evaluate"
    description = """Execute JavaScript code in the context of the current page. 

Can access DOM, global variables, and return values. Useful for:
- Extracting data not visible in HTML
- Manipulating page state
- Triggering events
- Getting computed styles
- Custom data extraction

The script runs in the page context (not isolated), so it has full access to window, document, etc.
"""
    parameters = {
        "type": "object",
        "properties": {
            "script": {
                "type": "string",
                "description": "JavaScript code to execute. Use 'return' to return a value. Can be an arrow function or plain script."
            },
            "args": {
                "type": "array",
                "description": "Arguments to pass to the script. Accessible via 'arguments' array or destructuring in arrow function.",
                "items": {"type": ["string", "number", "boolean", "object", "array"]},
                "default": []
            },
            "selector": {
                "type": "string",
                "description": "Optional: CSS selector to execute script on a specific element (passed as first argument)"
            },
            "timeout": {
                "type": "integer",
                "description": "Maximum execution time in milliseconds",
                "default": 30000
            }
        },
        "required": ["script"]
    }
    
    async def execute(
        self,
        script: str,
        args: list[Any] | None = None,
        selector: str | None = None,
        timeout: int = 30000,
        **kwargs: Any
    ) -> str:
        try:
            manager = BrowserManager.get_instance()
            page = await manager.get_page()
            
            execution_args = args or []
            
            # If selector provided, add the element as first argument
            if selector:
                element = await page.query_selector(selector)
                if not element:
                    return f"Error: Element not found with selector '{selector}'"
                execution_args = [element] + execution_args
            
            # Set timeout for this evaluation
            page.set_default_timeout(timeout)
            
            try:
                result = await page.evaluate(script, execution_args)
            finally:
                # Reset to default timeout
                if manager.config:
                    page.set_default_timeout(manager.config.default_timeout)
            
            # Format result
            if result is None:
                return "Script executed successfully (returned null/undefined)"
            
            if isinstance(result, (dict, list)):
                # Pretty print complex objects
                return json.dumps(result, indent=2, ensure_ascii=False, default=str)
            
            return str(result)
            
        except Exception as e:
            return f"Error executing script: {str(e)}"


class BrowserEvaluateHandleTool(Tool):
    """Execute JavaScript and return a handle to the result."""
    
    name = "browser_evaluate_handle"
    description = """Execute JavaScript and get a persistent handle to the result.

Useful when you need to work with complex objects across multiple operations.
Returns a handle ID that can be used with other tools (future feature).
For now, use browser_evaluate for most cases.
"""
    parameters = {
        "type": "object",
        "properties": {
            "script": {
                "type": "string",
                "description": "JavaScript code to execute"
            },
            "args": {
                "type": "array",
                "description": "Arguments to pass to script",
                "default": []
            }
        },
        "required": ["script"]
    }
    
    async def execute(
        self,
        script: str,
        args: list[Any] | None = None,
        **kwargs: Any
    ) -> str:
        try:
            manager = BrowserManager.get_instance()
            page = await manager.get_page()
            
            handle = await page.evaluate_handle(script, args or [])
            
            # Get properties of the handle
            properties = await handle.get_properties()
            result = {}
            for key, value in properties.items():
                try:
                    result[key] = await value.json_value()
                except Exception:
                    result[key] = "[Object]"
            
            await handle.dispose()
            
            return json.dumps(result, indent=2, ensure_ascii=False, default=str)
            
        except Exception as e:
            return f"Error executing script: {str(e)}"


class BrowserAddScriptTool(Tool):
    """Add a script tag to the page."""
    
    name = "browser_add_script"
    description = "Inject a JavaScript file or inline script into the page. Useful for adding libraries or polyfills."
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL of script to load (e.g., https://cdn.example.com/lib.js)"
            },
            "content": {
                "type": "string",
                "description": "Inline JavaScript code to inject"
            },
            "type": {
                "type": "string",
                "enum": ["text/javascript", "module"],
                "description": "Script type",
                "default": "text/javascript"
            }
        },
        "required": []
    }
    
    async def execute(
        self,
        url: str | None = None,
        content: str | None = None,
        type: str = "text/javascript",
        **kwargs: Any
    ) -> str:
        if not url and not content:
            return "Error: Either 'url' or 'content' must be provided"
        
        try:
            manager = BrowserManager.get_instance()
            page = await manager.get_page()
            
            if url:
                # Add external script
                await page.add_script_tag(url=url, type=type)
                return f"Script added from URL: {url}"
            else:
                # Add inline script
                await page.add_script_tag(content=content, type=type)
                return "Inline script added successfully"
                
        except Exception as e:
            return f"Error adding script: {str(e)}"
