"""Web scraping tools using Scrapling library."""

import json
import os
import re
from typing import Any
from urllib.parse import urlparse

from loguru import logger

from nanobot.agent.tools.base import Tool

# Try to import Scrapling
try:
    from scrapling.fetchers import Fetcher, FetcherSession, StealthyFetcher, DynamicFetcher
    from scrapling.parser import Selector
    SCRAPLING_AVAILABLE = True
except ImportError:
    SCRAPLING_AVAILABLE = False
    logger.warning("Scrapling not installed. Install with: pip install 'scrapling[fetchers]' && scrapling install")


def _validate_url(url: str) -> tuple[bool, str]:
    """Validate URL: must be http(s) with valid domain."""
    try:
        p = urlparse(url)
        if p.scheme not in ('http', 'https'):
            return False, f"Only http/https allowed, got '{p.scheme or 'none'}'"
        if not p.netloc:
            return False, "Missing domain"
        return True, ""
    except Exception as e:
        return False, str(e)


def _parse_selector(selector: str) -> tuple[str, str]:
    """
    Parse selector and determine type (CSS or XPath).

    Returns:
        Tuple of (selector_type, cleaned_selector)
        - selector_type: "css" or "xpath"
        - cleaned_selector: Selector without prefix
    """
    if selector.startswith("xpath:"):
        return "xpath", selector[6:]
    elif selector.startswith("//") or selector.startswith("("):
        return "xpath", selector
    else:
        return "css", selector


def _extract_attribute(selector: str) -> tuple[str, str | None]:
    """
    Check if selector includes attribute extraction (::attr(name)).

    Returns:
        Tuple of (base_selector, attribute_name or None)
    """
    # Match CSS pseudo-element for attribute: ::attr(name)
    match = re.search(r'::attr\(([^)]+)\)$', selector)
    if match:
        base_selector = selector[:match.start()]
        attribute = match.group(1)
        return base_selector, attribute

    # Match CSS pseudo-element for text: ::text
    if "::text" in selector:
        base_selector = selector.split("::text")[0]
        return base_selector, "text"

    return selector, None


def _format_results(results: list[Any] | str, url: str, method: str, extract_type: str) -> str:
    """Format scraping results as JSON."""
    if isinstance(results, str):
        results = [results]

    return json.dumps({
        "url": url,
        "status": "success",
        "method": method,
        "extract_type": extract_type,
        "count": len(results),
        "results": results[:100],  # Limit to 100 results
        "truncated": len(results) > 100
    }, ensure_ascii=False, indent=2)


class ScrapePageTool(Tool):
    """Fast HTTP-based scraping with TLS impersonation."""

    name = "scrape_page"
    description = "Fast web scraping using HTTP requests with TLS impersonation. Best for static pages and APIs. Supports CSS and XPath selectors."
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL to scrape"
            },
            "selector": {
                "type": "string",
                "description": "CSS or XPath selector (prefix with 'xpath:' for XPath). Examples: '.product', '#content', 'xpath://div[@class=\"item\"]', 'a::attr(href)' for attributes"
            },
            "extract": {
                "type": "string",
                "enum": ["text", "html", "attr", "all"],
                "description": "What to extract: 'text' (default), 'html', 'attr' (for attributes), 'all' (full element objects)",
                "default": "text"
            },
            "attribute": {
                "type": "string",
                "description": "Attribute name to extract (used with extract='attr')"
            },
            "impersonate": {
                "type": "string",
                "enum": ["chrome", "firefox", "safari", "edge", "random"],
                "description": "Browser to impersonate for TLS fingerprinting (default: chrome)",
                "default": "chrome"
            },
            "timeout": {
                "type": "integer",
                "description": "Request timeout in seconds (default: 30)",
                "default": 30,
                "minimum": 5,
                "maximum": 300
            }
        },
        "required": ["url"]
    }

    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    async def execute(
        self,
        url: str,
        selector: str | None = None,
        extract: str = "text",
        attribute: str | None = None,
        impersonate: str = "chrome",
        timeout: int | None = None,
        **kwargs: Any
    ) -> str:
        if not SCRAPLING_AVAILABLE:
            return json.dumps({
                "error": "Scrapling is not installed. Install with: pip install 'scrapling[fetchers]' && scrapling install",
                "url": url
            }, ensure_ascii=False)

        # Validate URL
        is_valid, error_msg = _validate_url(url)
        if not is_valid:
            return json.dumps({"error": f"URL validation failed: {error_msg}", "url": url}, ensure_ascii=False)

        timeout = timeout or self.timeout

        try:
            # Fetch the page
            page = Fetcher.get(
                url,
                impersonate=impersonate,
                timeout=timeout
            )

            # If no selector, return full page content
            if not selector:
                content = page.html if extract == "html" else page.text
                return _format_results(content, url, "fetcher", extract)

            # Parse selector and extract
            base_selector, attr_in_selector = _extract_attribute(selector)
            selector_type, cleaned_selector = _parse_selector(base_selector)

            # Determine what to extract
            extract_attr = attribute or attr_in_selector
            if extract == "attr" and extract_attr:
                # Extract specific attribute
                if selector_type == "css":
                    results = page.css(cleaned_selector + f"::attr({extract_attr})")
                else:
                    results = page.xpath(cleaned_selector + f"/@{extract_attr}")
                results = results.getall() if hasattr(results, 'getall') else [results]
                return _format_results(results, url, "fetcher", f"attr:{extract_attr}")

            elif extract == "html":
                # Extract HTML content
                if selector_type == "css":
                    elements = page.css(cleaned_selector)
                else:
                    elements = page.xpath(cleaned_selector)
                results = elements.getall() if hasattr(elements, 'getall') else [elements.html if hasattr(elements, 'html') else str(elements)]
                return _format_results(results, url, "fetcher", "html")

            elif extract == "text":
                # Extract text content
                if selector_type == "css":
                    results = page.css(cleaned_selector + "::text")
                else:
                    results = page.xpath(cleaned_selector + "/text()")
                results = results.getall() if hasattr(results, 'getall') else [results]
                # Clean and filter empty results
                results = [r.strip() for r in results if r and r.strip()]
                return _format_results(results, url, "fetcher", "text")

            else:  # extract == "all"
                # Return full element data
                if selector_type == "css":
                    elements = page.css(cleaned_selector)
                else:
                    elements = page.xpath(cleaned_selector)

                if hasattr(elements, '__iter__'):
                    results = [
                        {
                            "text": el.get(),
                            "html": el.html if hasattr(el, 'html') else None,
                            "attributes": el.attrib if hasattr(el, 'attrib') else {}
                        }
                        for el in elements
                    ]
                else:
                    results = [{
                        "text": elements.get(),
                        "html": elements.html if hasattr(elements, 'html') else None,
                        "attributes": elements.attrib if hasattr(elements, 'attrib') else {}
                    }]
                return _format_results(results, url, "fetcher", "all")

        except Exception as e:
            logger.error(f"Scraping error for {url}: {e}")
            return json.dumps({
                "error": str(e),
                "url": url,
                "method": "fetcher"
            }, ensure_ascii=False)


class ScrapeStealthyTool(Tool):
    """Advanced scraping with anti-bot bypass (Cloudflare, etc.)."""

    name = "scrape_stealthy"
    description = "Advanced web scraping with anti-bot bypass. Handles Cloudflare Turnstile, Interstitial, and other bot protection. Slower but more powerful."
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL to scrape"
            },
            "selector": {
                "type": "string",
                "description": "CSS or XPath selector"
            },
            "extract": {
                "type": "string",
                "enum": ["text", "html", "attr", "all"],
                "description": "What to extract (default: text)",
                "default": "text"
            },
            "attribute": {
                "type": "string",
                "description": "Attribute name to extract"
            },
            "solve_cloudflare": {
                "type": "boolean",
                "description": "Auto-solve Cloudflare challenges (default: true)",
                "default": True
            },
            "headless": {
                "type": "boolean",
                "description": "Run headless browser (default: true)",
                "default": True
            },
            "timeout": {
                "type": "integer",
                "description": "Request timeout in seconds (default: 60)",
                "default": 60,
                "minimum": 10,
                "maximum": 600
            }
        },
        "required": ["url"]
    }

    def __init__(self, timeout: int = 60):
        self.timeout = timeout

    async def execute(
        self,
        url: str,
        selector: str | None = None,
        extract: str = "text",
        attribute: str | None = None,
        solve_cloudflare: bool = True,
        headless: bool = True,
        timeout: int | None = None,
        **kwargs: Any
    ) -> str:
        if not SCRAPLING_AVAILABLE:
            return json.dumps({
                "error": "Scrapling is not installed. Install with: pip install 'scrapling[fetchers]' && scrapling install",
                "url": url
            }, ensure_ascii=False)

        is_valid, error_msg = _validate_url(url)
        if not is_valid:
            return json.dumps({"error": f"URL validation failed: {error_msg}", "url": url}, ensure_ascii=False)

        timeout = timeout or self.timeout

        try:
            # Fetch with stealthy fetcher
            page = StealthyFetcher.fetch(
                url,
                headless=headless,
                network_idle=True,
                solve_cloudflare=solve_cloudflare,
                timeout=timeout
            )

            # Reuse extraction logic from ScrapePageTool
            if not selector:
                content = page.html if extract == "html" else page.text
                return _format_results(content, url, "stealthy_fetcher", extract)

            base_selector, attr_in_selector = _extract_attribute(selector)
            selector_type, cleaned_selector = _parse_selector(base_selector)
            extract_attr = attribute or attr_in_selector

            if extract == "attr" and extract_attr:
                if selector_type == "css":
                    results = page.css(cleaned_selector + f"::attr({extract_attr})")
                else:
                    results = page.xpath(cleaned_selector + f"/@{extract_attr}")
                results = results.getall() if hasattr(results, 'getall') else [results]
                return _format_results(results, url, "stealthy_fetcher", f"attr:{extract_attr}")

            elif extract == "html":
                if selector_type == "css":
                    elements = page.css(cleaned_selector)
                else:
                    elements = page.xpath(cleaned_selector)
                results = elements.getall() if hasattr(elements, 'getall') else [elements.html if hasattr(elements, 'html') else str(elements)]
                return _format_results(results, url, "stealthy_fetcher", "html")

            elif extract == "text":
                if selector_type == "css":
                    results = page.css(cleaned_selector + "::text")
                else:
                    results = page.xpath(cleaned_selector + "/text()")
                results = results.getall() if hasattr(results, 'getall') else [results]
                results = [r.strip() for r in results if r and r.strip()]
                return _format_results(results, url, "stealthy_fetcher", "text")

            else:  # extract == "all"
                if selector_type == "css":
                    elements = page.css(cleaned_selector)
                else:
                    elements = page.xpath(cleaned_selector)

                if hasattr(elements, '__iter__'):
                    results = [
                        {
                            "text": el.get(),
                            "html": el.html if hasattr(el, 'html') else None,
                            "attributes": el.attrib if hasattr(el, 'attrib') else {}
                        }
                        for el in elements
                    ]
                else:
                    results = [{
                        "text": elements.get(),
                        "html": elements.html if hasattr(elements, 'html') else None,
                        "attributes": elements.attrib if hasattr(elements, 'attrib') else {}
                    }]
                return _format_results(results, url, "stealthy_fetcher", "all")

        except Exception as e:
            logger.error(f"Stealthy scraping error for {url}: {e}")
            return json.dumps({
                "error": str(e),
                "url": url,
                "method": "stealthy_fetcher"
            }, ensure_ascii=False)


class ScrapeDynamicTool(Tool):
    """Browser automation for JavaScript-rendered content."""

    name = "scrape_dynamic"
    description = "Full browser automation for JavaScript-rendered pages. Uses Playwright to render dynamic content. Slower but handles SPA and complex sites."
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL to scrape"
            },
            "selector": {
                "type": "string",
                "description": "CSS or XPath selector"
            },
            "extract": {
                "type": "string",
                "enum": ["text", "html", "attr", "all"],
                "description": "What to extract (default: text)",
                "default": "text"
            },
            "attribute": {
                "type": "string",
                "description": "Attribute name to extract"
            },
            "wait_for": {
                "type": "string",
                "description": "CSS selector to wait for before scraping (e.g., '.content-loaded')"
            },
            "network_idle": {
                "type": "boolean",
                "description": "Wait for network to be idle (default: true)",
                "default": True
            },
            "headless": {
                "type": "boolean",
                "description": "Run headless browser (default: true)",
                "default": True
            },
            "timeout": {
                "type": "integer",
                "description": "Page load timeout in seconds (default: 60)",
                "default": 60,
                "minimum": 10,
                "maximum": 600
            }
        },
        "required": ["url"]
    }

    def __init__(self, timeout: int = 60):
        self.timeout = timeout

    async def execute(
        self,
        url: str,
        selector: str | None = None,
        extract: str = "text",
        attribute: str | None = None,
        wait_for: str | None = None,
        network_idle: bool = True,
        headless: bool = True,
        timeout: int | None = None,
        **kwargs: Any
    ) -> str:
        if not SCRAPLING_AVAILABLE:
            return json.dumps({
                "error": "Scrapling is not installed. Install with: pip install 'scrapling[fetchers]' && scrapling install",
                "url": url
            }, ensure_ascii=False)

        is_valid, error_msg = _validate_url(url)
        if not is_valid:
            return json.dumps({"error": f"URL validation failed: {error_msg}", "url": url}, ensure_ascii=False)

        timeout = timeout or self.timeout

        try:
            # Fetch with dynamic fetcher
            page = DynamicFetcher.fetch(
                url,
                headless=headless,
                network_idle=network_idle,
                timeout=timeout
            )

            # Wait for specific element if requested
            if wait_for:
                try:
                    page.wait_for(wait_for, timeout=timeout)
                except Exception:
                    logger.warning(f"Wait for selector '{wait_for}' timed out, continuing anyway")

            # Reuse extraction logic
            if not selector:
                content = page.html if extract == "html" else page.text
                return _format_results(content, url, "dynamic_fetcher", extract)

            base_selector, attr_in_selector = _extract_attribute(selector)
            selector_type, cleaned_selector = _parse_selector(base_selector)
            extract_attr = attribute or attr_in_selector

            if extract == "attr" and extract_attr:
                if selector_type == "css":
                    results = page.css(cleaned_selector + f"::attr({extract_attr})")
                else:
                    results = page.xpath(cleaned_selector + f"/@{extract_attr}")
                results = results.getall() if hasattr(results, 'getall') else [results]
                return _format_results(results, url, "dynamic_fetcher", f"attr:{extract_attr}")

            elif extract == "html":
                if selector_type == "css":
                    elements = page.css(cleaned_selector)
                else:
                    elements = page.xpath(cleaned_selector)
                results = elements.getall() if hasattr(elements, 'getall') else [elements.html if hasattr(elements, 'html') else str(elements)]
                return _format_results(results, url, "dynamic_fetcher", "html")

            elif extract == "text":
                if selector_type == "css":
                    results = page.css(cleaned_selector + "::text")
                else:
                    results = page.xpath(cleaned_selector + "/text()")
                results = results.getall() if hasattr(results, 'getall') else [results]
                results = [r.strip() for r in results if r and r.strip()]
                return _format_results(results, url, "dynamic_fetcher", "text")

            else:  # extract == "all"
                if selector_type == "css":
                    elements = page.css(cleaned_selector)
                else:
                    elements = page.xpath(cleaned_selector)

                if hasattr(elements, '__iter__'):
                    results = [
                        {
                            "text": el.get(),
                            "html": el.html if hasattr(el, 'html') else None,
                            "attributes": el.attrib if hasattr(el, 'attrib') else {}
                        }
                        for el in elements
                    ]
                else:
                    results = [{
                        "text": elements.get(),
                        "html": elements.html if hasattr(elements, 'html') else None,
                        "attributes": elements.attrib if hasattr(elements, 'attrib') else {}
                    }]
                return _format_results(results, url, "dynamic_fetcher", "all")

        except Exception as e:
            logger.error(f"Dynamic scraping error for {url}: {e}")
            return json.dumps({
                "error": str(e),
                "url": url,
                "method": "dynamic_fetcher"
            }, ensure_ascii=False)


class ScrapeSpiderTool(Tool):
    """Multi-page spider-based crawling."""

    name = "scrape_spider"
    description = "Multi-page spider crawling. Follows links and extracts content from multiple pages concurrently. Good for blogs, product listings, etc."
    parameters = {
        "type": "object",
        "properties": {
            "start_urls": {
                "type": "string",
                "description": "JSON array of starting URLs, e.g., '[\"https://example.com/page1\"]'"
            },
            "follow_selector": {
                "type": "string",
                "description": "CSS selector for links to follow (e.g., 'a.next', 'a.product-link')"
            },
            "extract_selector": {
                "type": "string",
                "description": "CSS selector for content to extract (e.g., '.post-content', '.price')"
            },
            "max_pages": {
                "type": "integer",
                "description": "Maximum pages to crawl (default: 10)",
                "default": 10,
                "minimum": 1,
                "maximum": 1000
            },
            "concurrent": {
                "type": "integer",
                "description": "Concurrent requests (default: 5)",
                "default": 5,
                "minimum": 1,
                "maximum": 20
            },
            "extract_type": {
                "type": "string",
                "enum": ["text", "html", "all"],
                "description": "What to extract (default: text)",
                "default": "text"
            }
        },
        "required": ["start_urls"]
    }

    def __init__(self, max_pages: int = 10):
        self.max_pages = max_pages

    async def execute(
        self,
        start_urls: str,
        follow_selector: str | None = None,
        extract_selector: str | None = None,
        max_pages: int | None = None,
        concurrent: int = 5,
        extract_type: str = "text",
        **kwargs: Any
    ) -> str:
        if not SCRAPLING_AVAILABLE:
            return json.dumps({
                "error": "Scrapling is not installed. Install with: pip install 'scrapling[fetchers]' && scrapling install"
            }, ensure_ascii=False)

        # Parse start_urls JSON
        try:
            urls = json.loads(start_urls)
            if not isinstance(urls, list):
                return json.dumps({"error": "start_urls must be a JSON array"})
        except json.JSONDecodeError:
            return json.dumps({"error": "start_urls must be valid JSON array, e.g., '[\"https://example.com\"]'"})

        max_pages = min(max_pages or self.max_pages, 1000)

        try:
            from scrapling.spiders import Spider, Response
            import asyncio

            # Build spider class dynamically
            class DynamicSpider(Spider):
                name = "nanobot_spider"
                start_urls = urls
                concurrent_requests = concurrent
                max_pages = max_pages

                def __init__(self, *args, extract_sel=None, follow_sel=None, ext_type="text", **kwargs):
                    super().__init__(*args, **kwargs)
                    self.extract_selector = extract_sel
                    self.follow_selector = follow_sel
                    self.extract_type = ext_type
                    self.pages_crawled = 0
                    self.results = []

                async def parse(self, response: Response):
                    # Check max pages
                    self.pages_crawled += 1
                    if self.pages_crawled > self.max_pages:
                        return

                    # Extract content if selector provided
                    if self.extract_selector:
                        if self.extract_type == "text":
                            items = response.css(f"{self.extract_selector}::text").getall()
                            items = [i.strip() for i in items if i and i.strip()]
                        elif self.extract_type == "html":
                            items = response.css(self.extract_selector).getall()
                        else:  # all
                            elements = response.css(self.extract_selector)
                            items = [
                                {
                                    "text": el.get(),
                                    "html": el.html if hasattr(el, 'html') else None
                                }
                                for el in elements
                            ]
                        self.results.append({
                            "url": str(response.url),
                            "status": response.status,
                            "content": items
                        })

                    # Follow links if selector provided
                    if self.follow_selector and self.pages_crawled < self.max_pages:
                        links = response.css(f'{self.follow_selector}::attr("href")').getall()
                        for link in links:
                            if link and not link.startswith('#'):
                                yield response.follow(link, callback=self.parse)

            # Create and run spider
            spider = DynamicSpider(
                extract_sel=extract_selector,
                follow_sel=follow_selector,
                ext_type=extract_type
            )

            # Note: Scrapling's spider.start() is synchronous
            # For async compatibility, we run it in an executor
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, spider.start)

            return json.dumps({
                "status": "success",
                "pages_crawled": spider.pages_crawled,
                "results": spider.results[:100],  # Limit results
                "truncated": len(spider.results) > 100
            }, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"Spider crawling error: {e}")
            return json.dumps({
                "error": str(e),
                "method": "spider"
            }, ensure_ascii=False)
