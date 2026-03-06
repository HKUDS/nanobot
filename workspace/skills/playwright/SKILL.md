---
name: playwright
description: Browser automation via Playwright MCP (headless Chromium). Use for JavaScript-heavy pages, login flows, screenshots, and sites that block plain HTTP fetches.
metadata: {"nanobot":{"requires":{"bins":["docker","curl"]}}}
---

# Playwright Browser Automation

Use the `mcp_playwright_*` tools for full browser automation: navigation, clicks,
form fills, screenshots, JavaScript evaluation, and accessibility snapshots.

## Container Lifecycle (REQUIRED)

The `playwright-mcp` container is stopped when idle to conserve RAM. You MUST
start it before use and stop it when done — every time, even if the task fails.

### Step 1 — Start the container

```
exec: docker compose -f /home/admin/infra/docker-compose.yml start playwright-mcp
```

Then wait ~3 seconds for Chromium to initialize.

### Step 2 — Verify it is ready

```
exec: curl -sf http://127.0.0.1:8931/mcp > /dev/null && echo "ready" || echo "not ready"
```

If "not ready", wait 2 more seconds and retry once before proceeding.

### Step 3 — Use MCP tools

Common tools:
- `mcp_playwright_navigate` — go to a URL
- `mcp_playwright_snapshot` — get page accessibility tree
- `mcp_playwright_click` — click an element by ref
- `mcp_playwright_fill` — fill a form field
- `mcp_playwright_screenshot` — capture a screenshot
- `mcp_playwright_evaluate` — run JavaScript on the page

### Step 4 — Stop the container when done

```
exec: docker compose -f /home/admin/infra/docker-compose.yml stop playwright-mcp
```

Always run this step, even if the browser task failed or was interrupted.

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
- The MCP server runs at `http://127.0.0.1:8931/mcp` when the container is active.
- Do not leave the container running after your turn ends.
