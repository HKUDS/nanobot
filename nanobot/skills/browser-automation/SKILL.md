---
name: browser-automation
description: >
  Browser automation via Playwright CLI. Navigate pages, click elements,
  fill forms, take screenshots, and extract data from websites.
  Use this skill whenever the user asks to interact with a website,
  scrape data, fill a form, take a screenshot, or automate any browser task.
metadata: '{"nanobot":{"requires":{"bins":["playwright-cli"]}}}'
---

# Browser Automation (Playwright CLI)

You have browser automation capabilities via the `playwright-cli` command.
All browser commands are executed through the `exec` (shell) tool.

## Quick Reference

### Navigation
```bash
playwright-cli open <url>              # Open a URL
playwright-cli go-back                 # Go back
playwright-cli go-forward              # Go forward
playwright-cli reload                  # Reload page
```

### Page Inspection
```bash
playwright-cli snapshot                # Get accessibility tree (preferred)
playwright-cli screenshot              # Screenshot entire page
playwright-cli screenshot <ref>        # Screenshot specific element
```

### Interaction
```bash
playwright-cli click <ref>             # Click element by ref number
playwright-cli type <text>             # Type text into focused element
playwright-cli type --ref <ref> <text> # Type into specific element
playwright-cli press Enter             # Press a key
playwright-cli select <ref> <value>    # Select dropdown option
playwright-cli hover <ref>             # Hover over element
```

### Sessions (multiple tabs/contexts)
```bash
playwright-cli --session=myname open <url>   # Named session
playwright-cli tab-list                       # List open tabs
playwright-cli tab-new <url>                  # New tab
playwright-cli tab-select <index>             # Switch tab
playwright-cli tab-close <index>              # Close tab
```

### File Operations
```bash
playwright-cli screenshot --output /tmp/shot.png
playwright-cli pdf --output /tmp/page.pdf
```

## Workflow Pattern

For any browser task, follow this pattern:

1. **Open the page**: `playwright-cli open <url>`
2. **Snapshot the page**: `playwright-cli snapshot` to see the accessibility tree with element references like [1], [2], etc.
3. **Interact**: Use `click`, `type`, `press` with the ref numbers from the snapshot.
4. **Re-snapshot after actions**: The page may have changed — always snapshot again before the next interaction.
5. **Extract or screenshot**: Get the data you need or take a screenshot.

## Example: Login to a website

```bash
# Step 1: Navigate
playwright-cli open https://example.com/login

# Step 2: See what's on the page
playwright-cli snapshot
# Output shows: [1] input "Username"  [2] input "Password"  [3] button "Sign In"

# Step 3: Fill in credentials
playwright-cli type --ref 1 "myusername"
playwright-cli type --ref 2 "mypassword"
playwright-cli click 3

# Step 4: Verify login worked
playwright-cli snapshot
```

## Example: Scrape data from a page

```bash
playwright-cli open https://example.com/products
playwright-cli snapshot
# Parse the accessibility tree output to extract product names, prices, etc.
```

## Important Notes

- Always use `snapshot` (not screenshot) as your primary way to understand page structure. It returns a text-based accessibility tree that you can reason about.
- Element refs (like [1], [2]) expire after page changes. Always re-snapshot after navigation or clicks.
- If `playwright-cli` is not installed, install it with: `pip install playwright`
- For sites that need JavaScript to render, add a short wait: `sleep 2` before snapshot.
- Use `--session` flag to maintain separate browser contexts for different sites.
