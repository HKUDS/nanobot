# Tool Usage Notes

Tool signatures are provided automatically via function calling.
This file documents non-obvious constraints and usage patterns.

## exec — Safety Limits

- Commands have a configurable timeout (default 60s)
- Dangerous commands are blocked (rm -rf, format, dd, shutdown, etc.)
- Output is truncated at 10,000 characters
- `restrictToWorkspace` config can limit file access to the workspace

## cron — Scheduled Reminders

- Please refer to cron skill for usage.

## browser — Web Automation

Browser tools are only available when `tools.browser.enabled` is `true` in config.

### Recommended workflow

1. Always `browser_navigate` first before any interaction.
2. Use `browser_wait` before clicking or typing — pages may not be fully loaded.
3. Prefer `text` parameter over `selector` when element identity is ambiguous.
4. Take a `browser_screenshot` to verify state before and after complex actions.

### Non-obvious constraints

- `browser_navigate` default `waitUntil` is `"networkidle"` — use `"domcontentloaded"` for slow or streaming pages.
- `browser_type` with `clearFirst: true` (default) replaces existing value; set `false` to append.
- `browser_scroll direction: "to"` requires a `selector` to scroll that element into view.
- `browser_pdf` only works with Chromium; Firefox and WebKit do not support PDF generation.
- `browser_screenshot` with `fullPage: true` captures the entire scrollable page, not just the viewport.
- `browser_evaluate` must use `return` to get a value back (e.g. `return document.title`).
- All file outputs (screenshots, PDFs) are saved to the configured workspace paths and the full path is returned.
