---
name: agent-browser
description: "Automate web browser interactions via CLI commands. Use when user asks to: browse websites, navigate pages, extract data, take screenshots, fill forms, click buttons, or interact with web apps. Triggers: 浏览, 导航到, 访问网站, 从网页提取数据, 截图, 网页抓取, 填写表单, 点击, 在网页上搜索, browse, navigate, visit, screenshot, scrape, fill form, click"
allowed-tools: Read, Bash
---

# Agent Browser - Web Automation Skill

Automate web browser interactions using the `agent-browser` CLI tool. This skill enables natural language control of a headless Chromium browser.

## Setup Check

Before executing any browser commands, check the setup status:

1. Read `~/.claude/skills/agent-browser/setup.json`
2. If `{"installed": true}` - proceed with browser commands
3. If `{"installed": false}` or file doesn't exist - run installation first

### Installation (if needed)

```bash
# Install globally
npm install -g agent-browser

# Download Chromium browser
agent-browser install

# On Linux, include system dependencies:
# agent-browser install --with-deps
```

After successful installation, update setup.json:
```json
{"installed": true}
```

## Core Workflow

The recommended workflow for AI agents:

```bash
# 1. Open a webpage
agent-browser open <url>

# 2. Get page snapshot with element refs
agent-browser snapshot -i    # -i for interactive elements only

# 3. Interact using refs from snapshot
agent-browser click @e1
agent-browser fill @e2 "text"

# 4. Re-snapshot after page changes
agent-browser snapshot -i

# 5. Close when done
agent-browser close
```

## Command Reference

### Navigation

| Command | Description |
|---------|-------------|
| `agent-browser open <url>` | Navigate to URL |
| `agent-browser back` | Go back |
| `agent-browser forward` | Go forward |
| `agent-browser reload` | Reload page |
| `agent-browser get url` | Get current URL |
| `agent-browser get title` | Get page title |

### Page Analysis

| Command | Description |
|---------|-------------|
| `agent-browser snapshot` | Full accessibility tree with refs |
| `agent-browser snapshot -i` | Interactive elements only (buttons, inputs, links) |
| `agent-browser snapshot -c` | Compact (remove empty structural elements) |
| `agent-browser snapshot -d 3` | Limit depth to 3 levels |
| `agent-browser snapshot -s "#main"` | Scope to CSS selector |
| `agent-browser screenshot [path]` | Take screenshot |
| `agent-browser screenshot --full` | Full page screenshot |

### Element Interaction

Use refs from snapshot (e.g., `@e1`, `@e2`) or CSS selectors:

| Command | Description |
|---------|-------------|
| `agent-browser click @e1` | Click element |
| `agent-browser dblclick @e1` | Double-click |
| `agent-browser fill @e1 "text"` | Clear and fill input |
| `agent-browser type @e1 "text"` | Type into element |
| `agent-browser hover @e1` | Hover over element |
| `agent-browser focus @e1` | Focus element |
| `agent-browser check @e1` | Check checkbox |
| `agent-browser uncheck @e1` | Uncheck checkbox |
| `agent-browser select @e1 "value"` | Select dropdown option |

### Keyboard & Mouse

| Command | Description |
|---------|-------------|
| `agent-browser press Enter` | Press key |
| `agent-browser press Control+a` | Key combination |
| `agent-browser scroll down 500` | Scroll direction and pixels |
| `agent-browser scrollintoview @e1` | Scroll element into view |

### Get Information

| Command | Description |
|---------|-------------|
| `agent-browser get text @e1` | Get text content |
| `agent-browser get html @e1` | Get innerHTML |
| `agent-browser get value @e1` | Get input value |
| `agent-browser get attr @e1 href` | Get attribute |
| `agent-browser get count ".item"` | Count matching elements |

### State Checks

| Command | Description |
|---------|-------------|
| `agent-browser is visible @e1` | Check if visible |
| `agent-browser is enabled @e1` | Check if enabled |
| `agent-browser is checked @e1` | Check if checked |

### Wait Commands

| Command | Description |
|---------|-------------|
| `agent-browser wait @e1` | Wait for element visible |
| `agent-browser wait 2000` | Wait milliseconds |
| `agent-browser wait --text "Welcome"` | Wait for text |
| `agent-browser wait --url "**/dashboard"` | Wait for URL pattern |
| `agent-browser wait --load networkidle` | Wait for network idle |

### Browser Control

| Command | Description |
|---------|-------------|
| `agent-browser close` | Close browser |
| `agent-browser tab` | List tabs |
| `agent-browser tab new [url]` | Open new tab |
| `agent-browser tab 2` | Switch to tab |
| `agent-browser tab close` | Close current tab |

### Sessions (Multiple Browsers)

```bash
agent-browser --session agent1 open site-a.com
agent-browser --session agent2 open site-b.com
agent-browser session list
```

## Usage Patterns

### Browse and Extract Data

```bash
agent-browser open https://example.com
agent-browser snapshot -i
# Identify target elements from snapshot
agent-browser get text @e3
agent-browser close
```

### Fill and Submit Form

```bash
agent-browser open https://example.com/login
agent-browser snapshot -i
# Find form fields
agent-browser fill @e2 "username"
agent-browser fill @e3 "password"
agent-browser click @e4  # Submit button
agent-browser wait --load networkidle
agent-browser snapshot -i
agent-browser close
```

### Take Screenshot

```bash
agent-browser open https://example.com
agent-browser wait --load networkidle
agent-browser screenshot ~/Desktop/page.png
# Or full page:
agent-browser screenshot ~/Desktop/full.png --full
agent-browser close
```

### Search on Website

```bash
agent-browser open https://example.com
agent-browser snapshot -i
# Find search input
agent-browser fill @e1 "search query"
agent-browser press Enter
agent-browser wait --load networkidle
agent-browser snapshot -i
# Extract results
agent-browser close
```

### Navigate Multi-page Flow

```bash
agent-browser open https://shop.example.com
agent-browser snapshot -i
agent-browser click @e5  # Product link
agent-browser wait --load networkidle
agent-browser snapshot -i
agent-browser click @e3  # Add to cart
agent-browser snapshot -i
agent-browser click @e7  # Checkout
agent-browser close
```

## Tips

1. **Always snapshot first** - Get refs before interacting
2. **Use `-i` flag** - Filter to interactive elements for cleaner output
3. **Re-snapshot after navigation** - Refs change when page changes
4. **Use `--json` for parsing** - Machine-readable output for complex extractions
5. **Wait for page load** - Use `wait --load networkidle` after navigation
6. **Close when done** - Free up browser resources

## Best Practices

### Handling Link Clicks

Links may open in the current tab or spawn a new tab (`target="_blank"`). Verify tab state immediately after clicking:

```bash
# Click the link
agent-browser click @e1

# Check for new tabs
agent-browser tab

# If a new tab appeared, switch to it (highest index)
agent-browser tab <index>

# Wait for page load
agent-browser wait --load networkidle
```

### Handling Dynamic Content

For pages with lazy loading or infinite scroll:

```bash
# Scroll to trigger content loading
agent-browser scroll down 1000

# Wait for network activity to settle
agent-browser wait --load networkidle

# Re-snapshot to capture newly loaded content
agent-browser snapshot -i
```

### Handling Modals and Popups

Modals overlay the page and capture focus:

```bash
# After triggering a modal, re-snapshot
agent-browser snapshot -i

# Modal elements appear in the new snapshot
# Interact with modal, then dismiss
agent-browser click @modal-close-btn

# Snapshot again after modal closes
agent-browser snapshot -i
```

### Handling Authentication Walls

For pages requiring login:

```bash
# Check for login redirect
agent-browser get url

# If redirected to login page, fill credentials
agent-browser fill @username "user"
agent-browser fill @password "pass"
agent-browser click @submit

# Wait for post-login redirect
agent-browser wait --load networkidle
```

### Handling Cookie Consent Banners

Cookie banners often block page interaction:

```bash
# After page load, snapshot to locate cookie banner
agent-browser snapshot -i

# Locate and click accept/dismiss button
agent-browser click @accept-cookies

# Re-snapshot for main page content
agent-browser snapshot -i
```

### Multi-Tab Workflows

When comparing or aggregating data across multiple sources:

```bash
# Open multiple tabs
agent-browser tab new https://site-a.com
agent-browser tab new https://site-b.com

# List tabs to view indices
agent-browser tab

# Switch between tabs as needed
agent-browser tab 1
agent-browser snapshot -i
# Extract data...

agent-browser tab 2
agent-browser snapshot -i
# Extract data...

# Close browser when done
agent-browser close
```

### Handling Page Load Failures

Verify successful navigation before proceeding:

```bash
# Navigate to target URL
agent-browser open https://example.com

# Verify URL matches expected destination
agent-browser get url

# Check for error indicators in page content
agent-browser snapshot -i
```

## Headed Mode (Debug)

For debugging, show the browser window:

```bash
agent-browser open example.com --headed
```

## Error Handling

If browser commands fail:

1. Check if browser is running: `agent-browser get url`
2. If not, re-open: `agent-browser open <url>`
3. For stale refs, re-snapshot: `agent-browser snapshot -i`
4. For timeouts, add explicit waits: `agent-browser wait --load networkidle`
