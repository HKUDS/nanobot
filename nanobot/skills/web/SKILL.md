---
name: web
description: Web navigation and search using charlotte MCP server tools.
always: true
---

# Web Navigation

All web access — search and page fetching — must go through the charlotte MCP server tools (`mcp_charlotte_*`). Do not use the built-in `web_search` or `web_fetch` tools.

## Search

To search the web, fetch the DuckDuckGo results page directly:

```
mcp_charlotte_fetch url="https://duckduckgo.com/?q={url-encoded query}"
```

Parse the returned HTML for result titles, URLs, and snippets. Follow up by fetching individual result pages as needed.

## Fetching pages

To read any URL:

```
mcp_charlotte_fetch url="https://example.com"
```

## Rules

- Always use `mcp_charlotte_*` tools for all web tasks — never the built-in `web_search` or `web_fetch`.
- Do not narrate intermediate steps or tool calls to the user. Silently perform all search and fetch operations, then respond only with the final answer.
- If charlotte is unavailable, inform the user that web access is currently unavailable rather than falling back to built-in tools.
