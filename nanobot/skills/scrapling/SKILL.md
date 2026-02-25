---
name: scrapling
description: "Advanced web scraping tool using Scrapling library. Supports adaptive scraping, anti-bot bypass, JavaScript rendering, and spider-based crawling."
homepage: https://github.com/D4Vinci/Scrapling
metadata: {"nanobot":{"emoji":"[&#`~\\\\]","requires":{"bins":["python3"],"env":[]}}}
---

# Scrapling Web Scraping

Advanced web scraping using **Scrapling** library - an adaptive framework that learns from website changes and automatically relocates elements when pages update.

## Available Scraping Tools

### 1. scrape_page - Basic Page Scraping
Fast HTTP-based scraping with TLS impersonation. Best for static pages and APIs.

```
scrape_page: url="https://example.com" selector=".product" extract="text"
```

**Parameters:**
- `url` (required): URL to scrape
- `selector` (optional): CSS/XPath selector (default: returns full page)
- `extract` (optional): What to extract - "text", "html", "attr", "all" (default: "text")
- `attribute` (optional): Attribute name when extract="attr"
- `impersonate` (optional): Browser to impersonate - "chrome", "firefox", "safari", "edge" (default: "chrome")
- `timeout` (optional): Request timeout in seconds (default: 30)

**Example: Extract all product names**
```
scrape_page: url="https://shop.example.com/products" selector=".product-name::text" extract="text"
```

**Example: Extract all links**
```
scrape_page: url="https://example.com" selector="a::attr(href)" extract="attr" attribute="href"
```

### 2. scrape_stealthy - Anti-Bot Bypass Scraping
Advanced scraping that bypasses Cloudflare, anti-bot protection, and interstitials.

```
scrape_stealthy: url="https://protected-site.com" selector=".content"
```

**Parameters:**
- `url` (required): URL to scrape
- `selector` (optional): CSS/XPath selector
- `extract` (optional): What to extract - "text", "html", "attr", "all" (default: "text")
- `attribute` (optional): Attribute name when extract="attr"
- `solve_cloudflare` (optional): Auto-solve Cloudflare challenges (default: true)
- `headless` (optional): Run headless browser (default: true)
- `timeout` (optional): Request timeout in seconds (default: 60)

**Example: Scrape protected site**
```
scrape_stealthy: url="https://protected-site.com" selector=".price" extract="text"
```

### 3. scrape_dynamic - JavaScript-Rendered Scraping
Full browser automation for pages with JavaScript-rendered content.

```
scrape_dynamic: url="https://js-heavy-site.com" selector=".data" wait_for=".loaded"
```

**Parameters:**
- `url` (required): URL to scrape
- `selector` (optional): CSS/XPath selector
- `extract` (optional): What to extract - "text", "html", "attr", "all" (default: "text")
- `attribute` (optional): Attribute name when extract="attr"
- `wait_for` (optional): CSS selector to wait for before scraping
- `network_idle` (optional): Wait for network to be idle (default: true)
- `headless` (optional): Run headless browser (default: true)
- `timeout` (optional): Page load timeout in seconds (default: 60)

**Example: Wait for content to load**
```
scrape_dynamic: url="https://spa.example.com" selector=".item" wait_for=".items-container" extract="text"
```

### 4. scrape_spider - Multi-Page Crawling
Spider-based crawling for multiple pages with concurrent requests.

```
scrape_spider: start_urls='["https://example.com/page1"]' follow_selector="a.next" extract_selector=".content"
```

**Parameters:**
- `start_urls` (required): JSON array of starting URLs
- `follow_selector` (optional): CSS selector for links to follow
- `extract_selector` (optional): CSS selector for content to extract
- `max_pages` (optional): Maximum pages to crawl (default: 10)
- `concurrent` (optional): Concurrent requests (default: 5)
- `extract_type` (optional): What to extract - "text", "html", "all" (default: "text")

**Example: Crawl blog posts**
```
scrape_spider: start_urls='["https://blog.example.com"]' follow_selector="a.post-link" extract_selector=".post-content" max_pages=20
```

---

## Selector Guide

### CSS Selectors (default)
```
.element              # Element by tag name
.class                # Element by class
#id                   # Element by ID
.parent .child        # Nested element
a::attr(href)         # Extract attribute
.text::text           # Extract text content
```

### XPath Selectors (prefix with `xpath:`)
```
xpath://div[@class="example"]
xpath://a[contains(@href, "/product/")]
xpath://h1/text()
```

---

## Output Format

Results are returned as structured JSON:
```json
{
  "url": "https://example.com",
  "status": "success",
  "method": "fetcher",
  "results": ["Item 1", "Item 2", "Item 3"],
  "count": 3
}
```

For spider crawling:
```json
{
  "status": "success",
  "pages_crawled": 10,
  "items": [
    {"url": "...", "content": "..."},
    {"url": "...", "content": "..."}
  ]
}
```

---

## Choosing the Right Tool

| Tool | Use Case | Speed | Anti-Bot |
|------|----------|-------|----------|
| `scrape_page` | Static content, APIs | Fastest | Basic |
| `scrape_stealthy` | Cloudflare/protected sites | Medium | Best |
| `scrape_dynamic` | JS-rendered content | Slowest | Good |
| `scrape_spider` | Multi-page crawling | Medium | Good |

---

## Common Workflows

### Extract Product Information
```
scrape_page: url="https://shop.example.com/products" selector=".product-card" extract="all"
```

Then parse individual products from returned HTML.

### Scrape Behind Cloudflare
```
scrape_stealthy: url="https://protected-site.com/data" selector=".data-row" extract="text"
```

### Crawl Multiple Pages
```
scrape_spider: start_urls='["https://example.com"]' follow_selector="a.pagination-next" extract_selector=".article-content" max_pages=50
```

---

## Notes

- Scrapling uses **adaptive scraping** - it can relocate elements if page structure changes
- First scrape with `auto_save` capability learns element patterns
- Subsequent scrapes with `adaptive` mode find elements even after structure changes
- Always respect `robots.txt` and website terms of service
- Use appropriate delays to avoid overwhelming servers

## Installation

If Scrapling is not installed:
```bash
pip install "scrapling[fetchers]"
scrapling install
```

## Documentation

- GitHub: https://github.com/D4Vinci/Scrapling
- Docs: https://scrapling.readthedocs.io/
