"""Browser screenshot and PDF tools."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.browser.manager import BrowserManager
from nanobot.config.paths import get_workspace_path


class BrowserScreenshotTool(Tool):
    """Take a screenshot of the page or element."""
    
    name = "browser_screenshot"
    description = "Capture a screenshot of the current page, full page, or a specific element. Saves to workspace/screenshots directory."
    parameters = {
        "type": "object",
        "properties": {
            "full_page": {
                "type": "boolean",
                "description": "Capture the full scrollable page (not just viewport). Recommended for complete page captures.",
                "default": False
            },
            "selector": {
                "type": "string",
                "description": "CSS selector to screenshot a specific element only (e.g., '#chart', '.modal-content'). Overrides full_page."
            },
            "filename": {
                "type": "string",
                "description": "Custom filename (without extension). If not provided, uses timestamp."
            },
            "format": {
                "type": "string",
                "enum": ["png", "jpeg"],
                "description": "Image format",
                "default": "png"
            },
            "quality": {
                "type": "integer",
                "description": "JPEG quality (0-100). Only used for jpeg format.",
                "minimum": 0,
                "maximum": 100,
                "default": 90
            },
            "path": {
                "type": "string",
                "description": "Custom path to save screenshot (relative to workspace). Overrides default location."
            }
        }
    }
    
    async def execute(
        self,
        full_page: bool = False,
        selector: str | None = None,
        filename: str | None = None,
        format: str = "png",
        quality: int = 90,
        path: str | None = None,
        **kwargs: Any
    ) -> str:
        try:
            manager = BrowserManager.get_instance()
            page = await manager.get_page()
            
            # Determine save path
            if path:
                save_path = Path(path)
                if not save_path.is_absolute():
                    save_path = get_workspace_path() / save_path
            else:
                # Use screenshots directory
                if manager.config and manager.config.screenshots_dir:
                    screenshots_dir = manager.config.screenshots_dir
                else:
                    screenshots_dir = get_workspace_path() / "screenshots"
                
                screenshots_dir.mkdir(parents=True, exist_ok=True)
                
                # Generate filename
                timestamp = int(time.time())
                name = filename or f"screenshot_{timestamp}"
                save_path = screenshots_dir / f"{name}.{format}"
            
            save_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Screenshot options
            screenshot_options: dict[str, Any] = {
                "path": str(save_path),
                "type": format
            }
            
            if format == "jpeg":
                screenshot_options["quality"] = quality
            
            # Take screenshot
            if selector:
                # Screenshot specific element
                element = page.locator(selector)
                await element.screenshot(**screenshot_options)
                target_desc = f"element '{selector}'"
            else:
                # Screenshot page
                screenshot_options["full_page"] = full_page
                await page.screenshot(**screenshot_options)
                target_desc = "full page" if full_page else "viewport"
            
            # Get file size
            file_size = save_path.stat().st_size
            size_kb = file_size / 1024
            
            return f"Screenshot saved: {save_path} ({size_kb:.1f} KB, {target_desc})"
            
        except Exception as e:
            return f"Error taking screenshot: {str(e)}"


class BrowserPdfTool(Tool):
    """Generate PDF from the page."""
    
    name = "browser_pdf"
    description = "Generate a PDF from the current page. Supports full page or specific element, with customizable format and margins."
    parameters = {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Custom filename (without .pdf extension). If not provided, uses timestamp."
            },
            "path": {
                "type": "string",
                "description": "Custom path to save PDF (relative to workspace). Defaults to workspace/downloads."
            },
            "format": {
                "type": "string",
                "enum": ["A4", "Letter", "Legal", "Tabloid", "A3", "A5"],
                "description": "Paper format",
                "default": "A4"
            },
            "landscape": {
                "type": "boolean",
                "description": "Landscape orientation",
                "default": False
            },
            "margin": {
                "type": "object",
                "description": "Page margins in inches (or cm with 'cm' suffix)",
                "properties": {
                    "top": {"type": "string", "default": "0.4in"},
                    "bottom": {"type": "string", "default": "0.4in"},
                    "left": {"type": "string", "default": "0.4in"},
                    "right": {"type": "string", "default": "0.4in"}
                }
            },
            "print_background": {
                "type": "boolean",
                "description": "Include background graphics",
                "default": True
            },
            "header_template": {
                "type": "string",
                "description": "HTML template for header. Use <span class='title'></span> for title, <span class='url'></span> for URL, <span class='date'></span> for date."
            },
            "footer_template": {
                "type": "string",
                "description": "HTML template for footer. Use <span class='pageNumber'></span> and <span class='totalPages'></span>."
            },
            "selector": {
                "type": "string",
                "description": "CSS selector to print only specific element (prints whole page if not specified)"
            }
        }
    }
    
    async def execute(
        self,
        filename: str | None = None,
        path: str | None = None,
        format: str = "A4",
        landscape: bool = False,
        margin: dict[str, str] | None = None,
        print_background: bool = True,
        header_template: str | None = None,
        footer_template: str | None = None,
        selector: str | None = None,
        **kwargs: Any
    ) -> str:
        try:
            manager = BrowserManager.get_instance()
            page = await manager.get_page()
            
            # Determine save path
            if path:
                save_path = Path(path)
                if not save_path.is_absolute():
                    save_path = get_workspace_path() / save_path
            else:
                # Use downloads directory
                if manager.config and manager.config.downloads_dir:
                    downloads_dir = manager.config.downloads_dir
                else:
                    downloads_dir = get_workspace_path() / "downloads"
                
                downloads_dir.mkdir(parents=True, exist_ok=True)
                
                # Generate filename
                timestamp = int(time.time())
                name = filename or f"page_{timestamp}"
                save_path = downloads_dir / f"{name}.pdf"
            
            save_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Build PDF options
            pdf_options: dict[str, Any] = {
                "path": str(save_path),
                "format": format,
                "landscape": landscape,
                "print_background": print_background,
            }
            
            # Set margins
            default_margin = {"top": "0.4in", "bottom": "0.4in", "left": "0.4in", "right": "0.4in"}
            margins = {**default_margin, **(margin or {})}
            pdf_options["margin"] = margins
            
            # Add templates if provided
            if header_template:
                pdf_options["display_header_footer"] = True
                pdf_options["header_template"] = header_template
            if footer_template:
                pdf_options["display_header_footer"] = True
                pdf_options["footer_template"] = footer_template
            
            # If selector specified, we need to handle element-only printing
            if selector:
                # Create a temporary page with just that element
                element = page.locator(selector)
                html_content = await element.inner_html()
                
                temp_page = await manager.new_page()
                await temp_page.set_content(f"<html><body>{html_content}</body></html>")
                await temp_page.pdf(**pdf_options)
                await manager.close_page(temp_page)
                
                target_desc = f"element '{selector}'"
            else:
                # Print full page
                await page.pdf(**pdf_options)
                target_desc = "full page"
            
            # Get file size
            file_size = save_path.stat().st_size
            size_kb = file_size / 1024
            
            orientation = "landscape" if landscape else "portrait"
            return f"PDF saved: {save_path} ({size_kb:.1f} KB, {format} {orientation}, {target_desc})"
            
        except Exception as e:
            return f"Error generating PDF: {str(e)}"
