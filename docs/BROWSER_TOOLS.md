# Nanobot Browser Automation Tools

Nanobot now supports full browser automation using Playwright. This enables the AI to navigate websites, interact with elements, take screenshots, execute JavaScript, and more.

## Table of Contents

- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Available Tools](#available-tools)
- [Docker Deployment](#docker-deployment)
- [Usage Examples](#usage-examples)
- [Troubleshooting](#troubleshooting)

## Quick Start

### 1. Install Dependencies

```bash
# In the nanobot directory
pip install playwright
playwright install chromium
```

### 2. Enable Browser Tools

Edit your `~/.nanobot/config.json`:

```json
{
  "tools": {
    "browser": {
      "enabled": true,
      "headless": true,
      "viewportWidth": 1280,
      "viewportHeight": 720
    }
  }
}
```

### 3. Start Using

```bash
nanobot agent -m "Open https://example.com and take a screenshot"
```

## Configuration

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | boolean | `false` | Enable browser automation tools |
| `headless` | boolean | `true` | Run browser without UI |
| `browserType` | string | `"chromium"` | Browser: chromium, firefox, webkit |
| `viewportWidth` | integer | `1280` | Browser viewport width |
| `viewportHeight` | integer | `720` | Browser viewport height |
| `defaultTimeout` | integer | `30000` | Default timeout in milliseconds |
| `slowMo` | integer | `0` | Slow down operations by N ms (for debugging) |
| `screenshotsPath` | string | `"~/workspace/screenshots"` | Screenshot save location |
| `downloadsPath` | string | `"~/workspace/downloads"` | Download save location |
| `dockerMode` | boolean | `false` | Force Docker compatibility mode |
| `noSandbox` | boolean | `true` | Disable Chrome sandbox (Docker) |
| `disableDevShm` | boolean | `true` | Disable /dev/shm usage (Docker) |

### Full Configuration Example

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5"
    }
  },
  "tools": {
    "browser": {
      "enabled": true,
      "headless": false,
      "browserType": "chromium",
      "viewportWidth": 1920,
      "viewportHeight": 1080,
      "defaultTimeout": 30000,
      "slowMo": 100,
      "screenshotsPath": "~/nanobot/screenshots",
      "downloadsPath": "~/nanobot/downloads",
      "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
      "locale": "zh-CN",
      "timezone": "Asia/Shanghai"
    }
  }
}
```

## Available Tools

### Navigation Tools

#### `browser_navigate`
Navigate to a URL.

```json
{
  "url": "https://github.com",
  "waitUntil": "networkidle",
  "timeout": 30000
}
```

#### `browser_go_back`
Go back in browser history.

```json
{}
```

#### `browser_go_forward`
Go forward in browser history.

```json
{}
```

#### `browser_refresh`
Refresh the current page.

```json
{}
```

#### `browser_close`
Close the browser and release resources.

```json
{}
```

### Interaction Tools

#### `browser_click`
Click on an element.

```json
{
  "selector": "#submit-button",
  "button": "left",
  "doubleClick": false,
  "timeout": 10000
}
```

Or click by text:
```json
{
  "text": "Submit",
  "button": "left"
}
```

#### `browser_type`
Type text into an input field.

```json
{
  "selector": "input[name='q']",
  "text": "playwright python",
  "clearFirst": true,
  "submit": true,
  "delay": 50
}
```

#### `browser_get_text`
Get text content from page or element.

```json
{
  "selector": "article",
  "maxLength": 5000,
  "includeHidden": false
}
```

#### `browser_wait`
Wait for element, text, or time.

```json
{
  "selector": ".loading",
  "state": "hidden",
  "timeout": 10000
}
```

Or wait for text:
```json
{
  "text": "Results loaded",
  "timeout": 15000
}
```

#### `browser_scroll`
Scroll the page.

```json
{
  "direction": "down",
  "amount": 500,
  "smooth": true
}
```

Or scroll to element:
```json
{
  "direction": "to",
  "selector": "#footer"
}
```

### Screenshot Tools

#### `browser_screenshot`
Take a screenshot.

```json
{
  "fullPage": true,
  "filename": "github_homepage",
  "format": "png",
  "quality": 90
}
```

Screenshot specific element:
```json
{
  "selector": ".repository-content",
  "filename": "repo_content"
}
```

#### `browser_pdf`
Generate PDF from page.

```json
{
  "filename": "page_export",
  "format": "A4",
  "landscape": false,
  "printBackground": true
}
```

### JavaScript Tools

#### `browser_evaluate`
Execute JavaScript in page context.

```json
{
  "script": "return document.title;"
}
```

With arguments:
```json
{
  "script": "(args) => args[0] + args[1]",
  "args": [10, 20]
}
```

Extract data:
```json
{
  "script": "return Array.from(document.querySelectorAll('h2')).map(h => h.innerText);"
}
```

On specific element:
```json
{
  "selector": "#data-table",
  "script": "(element) => element.innerText;"
}
```

#### `browser_add_script`
Inject a script into the page.

```json
{
  "url": "https://cdn.jsdelivr.net/npm/lodash@4/lodash.min.js"
}
```

Or inline:
```json
{
  "content": "function greet(name) { return 'Hello ' + name; }"
}
```

## Docker Deployment

### Upgrading from Standard Docker Compose to Browser Mode

If you were already running `docker compose up -d nanobot-gateway` with the standard `docker-compose.yml`, follow these steps to switch to the browser-enabled image:

**1. Pull the latest code:**
```bash
git pull origin main
```

**2. Stop the current container:**
```bash
docker compose down nanobot-gateway
```

**3. Build and start the browser-enabled service:**
```bash
docker compose -f docker/docker-compose.browser.yml up -d --build
```

> `--build` is required the first time — it builds a new image based on `docker/Dockerfile.browser`, which includes Playwright and Chromium. Subsequent restarts don't need `--build` unless the code changes.

**4. Enable browser in `~/.nanobot/config.json`:**
```json
{
  "tools": {
    "browser": {
      "enabled": true,
      "headless": true
    }
  }
}
```

> The browser Compose file already passes `NANOBOT__TOOLS__BROWSER__ENABLED=true` as an environment variable, so this step is optional but recommended for clarity.

**Key differences between standard and browser mode:**

| | Standard (`docker-compose.yml`) | Browser (`docker/docker-compose.browser.yml`) |
|---|---|---|
| Container name | `nanobot-gateway` | `nanobot-browser` |
| Image base | Standard Python | Playwright official image |
| Includes Chromium | No | Yes |
| Memory limit | 1 GB | 2 GB |
| Extra ports | — | 5900, 6080 (VNC) |
| Config/workspace | `~/.nanobot` (host mount) | Docker volume + `~/.nanobot` |

Your existing config (`~/.nanobot`) is still mounted into the new container — conversation history and settings are preserved.

---

### Quick Start with Docker (Fresh Install)

1. **Copy environment file:**
   ```bash
   cd nanobot
   cp docker/.env.example docker/.env
   # Edit docker/.env with your API keys
   ```

2. **Start the service:**
   ```bash
   docker-compose -f docker/docker-compose.browser.yml up -d
   ```

3. **Test browser automation:**
   ```bash
   docker-compose -f docker/docker-compose.browser.yml exec nanobot \
     nanobot agent -m "Open https://example.com and screenshot"
   ```

### With VNC Debugging

Enable remote desktop to see the browser:

```bash
VNC_ENABLED=true docker-compose -f docker/docker-compose.browser.yml up -d
```

Then open http://localhost:6080/vnc.html in your browser.

### Docker Commands

```bash
# Build image
docker-compose -f docker/docker-compose.browser.yml build

# Run interactively
docker-compose -f docker/docker-compose.browser.yml run --rm nanobot bash

# View logs
docker-compose -f docker/docker-compose.browser.yml logs -f

# Stop
docker-compose -f docker/docker-compose.browser.yml down

# Stop and remove volumes
docker-compose -f docker/docker-compose.browser.yml down -v
```

### Docker Environment Variables

| Variable | Description |
|----------|-------------|
| `VNC_ENABLED` | Enable VNC server for remote desktop |
| `OPENROUTER_API_KEY` | OpenRouter API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `DEFAULT_MODEL` | Default LLM model |
| `NANOBOT_PORT` | Gateway port (default: 18790) |

## Usage Examples

### Example 1: Search and Screenshot

```
User: Go to Google, search for "Python asyncio tutorial", and take a screenshot

Agent:
1. browser_navigate(url="https://google.com")
2. browser_type(selector="textarea[name='q']", text="Python asyncio tutorial", submit=true)
3. browser_wait(selector="#search")
4. browser_screenshot(full_page=true, filename="google_search_results")
```

### Example 2: Login to a Website

```
User: Log in to example.com with username "user" and password "pass"

Agent:
1. browser_navigate(url="https://example.com/login")
2. browser_type(selector="#username", text="user")
3. browser_type(selector="#password", text="pass")
4. browser_click(selector="button[type='submit']")
5. browser_wait(text="Welcome")
6. browser_screenshot(filename="logged_in")
```

### Example 3: Extract Data with JavaScript

```
User: Get all product names and prices from this page

Agent:
1. browser_navigate(url="https://store.example.com/products")
2. browser_evaluate(script=""
     return Array.from(document.querySelectorAll('.product')).map(p => ({
       name: p.querySelector('.name').innerText,
       price: p.querySelector('.price').innerText
     }));
   """)
```

### Example 4: Generate PDF Report

```
User: Save this page as a PDF with A4 format

Agent:
1. browser_navigate(url="https://report.example.com/monthly")
2. browser_wait(selector=".report-content")
3. browser_pdf(filename="monthly_report", format="A4", landscape=false)
```

### Example 5: Scroll and Capture Long Page

```
User: Capture the full documentation page

Agent:
1. browser_navigate(url="https://docs.example.com/guide")
2. browser_scroll(direction="to_bottom")
3. browser_wait(delay=1000)
4. browser_screenshot(full_page=true, filename="docs_full")
```

## Troubleshooting

### Common Issues

#### "Browser automation tools are not available"
- Check `tools.browser.enabled` is `true` in config
- Restart nanobot after config change

#### "Error: No element found with selector"
- Wait for element: Use `browser_wait` before interacting
- Check selector: Use browser dev tools to verify
- Try text-based selection: Use `text` parameter instead of `selector`

#### "Timeout waiting for navigation"
- Increase timeout: Add `timeout: 60000` parameter
- Check URL: Ensure it's accessible from your network
- Check waitUntil: Try `domcontentloaded` instead of `networkidle`

#### Docker: "Failed to launch browser"
- Ensure Docker has enough memory (minimum 1GB, recommended 2GB)
- Check logs: `docker-compose logs nanobot`
- Verify `noSandbox` and `disableDevShm` are `true`

#### Docker: "Cannot connect to display"
- Ensure Xvfb is running in container
- Check `DISPLAY=:99` environment variable
- For VNC: Verify `VNC_ENABLED=true`

### Debug Mode

Enable slow motion to see operations:

```json
{
  "tools": {
    "browser": {
      "slowMo": 500
    }
  }
}
```

### Getting Help

1. Check browser status: `nanobot status`
2. View tool list: The agent knows available tools
3. Enable logs: `nanobot agent -m "..." --logs`
4. Test manually: Use `browser_evaluate` with `return document.body.innerHTML`

## Advanced Topics

### Multi-Page Support

Currently, tools operate on a single default page. Multi-page support can be added for complex workflows.

### File Downloads

Downloads are automatically saved to `downloadsPath`. Use `browser_evaluate` to trigger downloads:

```javascript
// Trigger file download
browser_evaluate(script="document.querySelector('#download-link').click()")
```

### Authentication

For sites requiring login, you can:
1. Navigate and login manually first
2. Use `browser_evaluate` to set cookies/localStorage
3. (Future) Use persistent browser context

### Custom User-Agent

Some sites block automation. Set a realistic User-Agent:

```json
{
  "tools": {
    "browser": {
      "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
  }
}
```

## Contributing

To add new browser tools:

1. Create a new class inheriting from `Tool`
2. Implement `name`, `description`, `parameters`, and `execute`
3. Add to `nanobot/agent/tools/browser/__init__.py`
4. Register in `nanobot/agent/loop.py`

See existing tools for examples.
