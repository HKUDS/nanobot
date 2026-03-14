---
name: playwright
description: Browser automation via Playwright MCP (headless Chromium). Use for JavaScript-heavy pages, login flows, screenshots, and sites that block plain HTTP fetches.
metadata: {"nanobot":{"requires":{"bins":[]}}}
---

# Playwright Browser Automation

Use the `mcp_playwright_*` tools for full browser automation: navigation, clicks,
form fills, screenshots, JavaScript evaluation, and accessibility snapshots.

The `playwright-mcp` container runs persistently — no startup or shutdown steps needed.

## How to Use It

Recommended workflow:

1. Use `mcp_playwright_browser_navigate` to open the target page.
2. Use `mcp_playwright_browser_snapshot` to inspect the current page structure.
3. Use the refs from the snapshot with `mcp_playwright_browser_click`, `mcp_playwright_browser_hover`, or `mcp_playwright_browser_fill_form`.
4. Use `mcp_playwright_browser_wait_for` after actions that trigger loading or page changes.
5. Use `mcp_playwright_browser_take_screenshot` when visual confirmation is useful.
   The screenshot result now includes a local file path saved inside the nanobot container.
   If the user wants the screenshot delivered in chat, call `message` with that file path in `media`.
6. Use `mcp_playwright_browser_evaluate` or `mcp_playwright_browser_run_code` only when the normal browser tools are insufficient.

## Available Tools

- `mcp_playwright_browser_navigate` — go to a URL
- `mcp_playwright_browser_snapshot` — get the accessibility tree and element refs
- `mcp_playwright_browser_click` — click an element by ref
- `mcp_playwright_browser_hover` — hover over an element by ref
- `mcp_playwright_browser_fill_form` — fill one or more fields in a form
- `mcp_playwright_browser_type` — type text into the active element
- `mcp_playwright_browser_press_key` — press keyboard keys
- `mcp_playwright_browser_select_option` — choose a select option
- `mcp_playwright_browser_wait_for` — wait for text, element, or time-based conditions
- `mcp_playwright_browser_take_screenshot` — capture a screenshot
- `mcp_playwright_browser_evaluate` — run JavaScript in the page
- `mcp_playwright_browser_run_code` — run more advanced Playwright code
- `mcp_playwright_browser_tabs` — inspect or switch browser tabs
- `mcp_playwright_browser_network_requests` — inspect network activity
- `mcp_playwright_browser_console_messages` — inspect console output
- `mcp_playwright_browser_handle_dialog` — accept or dismiss alerts/prompts
- `mcp_playwright_browser_file_upload` — upload files
- `mcp_playwright_browser_drag` — drag and drop
- `mcp_playwright_browser_resize` — resize the browser viewport
- `mcp_playwright_browser_close` — close the browser session

## When to Use Playwright vs web_fetch

| Situation | Use |
|-----------|-----|
| Static page, API, or JSON endpoint | `web_fetch` |
| Page requires JavaScript to render | `mcp_playwright_*` |
| Login / cookie session needed | `mcp_playwright_*` |
| Site blocks automated HTTP requests | `mcp_playwright_*` |
| Screenshot or visual inspection needed | `mcp_playwright_*` |

## Notes

- Browser storage (cookies, localStorage) persists between sessions via a Docker volume.
- The MCP server is always available at `http://playwright-mcp:8931/mcp` on the internal network.
- The server is already connected to nanobot via MCP; do not try to start or stop it manually as part of normal use.
- Prefer `mcp_playwright_browser_snapshot` before clicking or filling so you can use stable element refs instead of guessing selectors.
- `mcp_playwright_browser_take_screenshot` returns image data that nanobot saves as a local file.
- To send a screenshot to the user, pass the returned saved path into `message(media=[...])`.
