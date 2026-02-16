---
name: browser-automation
description: >
  Browser automation via Playwright. Navigate pages, click elements,
  fill forms, take screenshots, and extract data from websites.
  Use this skill whenever the user asks to interact with a website,
  scrape data, fill a form, take a screenshot, or automate any browser task.
---

# Browser Automation (Playwright)

You have browser automation capabilities via Playwright.
All browser commands are executed through the `exec` (shell) tool.

## IMPORTANT: First-Run Setup

Before running ANY Playwright command, you MUST check if Playwright is installed.
Run this check **every time** this skill is loaded for the first time in a session:

```bash
python -c "import playwright; print('OK')"
```

If that fails (ModuleNotFoundError or non-zero exit), run the full setup:

```bash
pip install playwright
playwright install chromium
```

Wait for both commands to complete successfully before proceeding.
If `playwright install chromium` fails due to missing system dependencies on Linux, try:

```bash
playwright install-deps chromium
playwright install chromium
```

Once setup succeeds, confirm to the user: "Browser automation is now ready."
Do NOT attempt any browser automation until setup is confirmed.

## Usage

Use Python with Playwright's sync API via the exec tool. Example pattern:

```bash
python -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto('https://example.com')
    print(page.title())
    browser.close()
"
```

For longer scripts, write a .py file to the workspace first, then execute it.

## Common Tasks

### Navigate and get page content
```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(URL)
    print(page.content())       # Full HTML
    print(page.title())         # Page title
    print(page.inner_text("body"))  # Visible text only
    browser.close()
```

### Take a screenshot
```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(URL)
    page.screenshot(path="/tmp/screenshot.png", full_page=True)
    browser.close()
```

### Fill a form and submit
```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(URL)

    page.fill('input[name="username"]', 'myuser')
    page.fill('input[name="password"]', 'mypass')
    page.click('button[type="submit"]')

    page.wait_for_load_state("networkidle")
    print(page.title())
    browser.close()
```

### Click and interact with elements
```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(URL)

    # Click by text
    page.click("text=Sign In")

    # Click by CSS selector
    page.click("#submit-button")

    # Select dropdown
    page.select_option("select#country", "US")

    # Type into focused element
    page.keyboard.type("search query")
    page.keyboard.press("Enter")

    browser.close()
```

### Wait for dynamic content
```python
# Wait for a specific element to appear
page.wait_for_selector(".results-loaded", timeout=10000)

# Wait for navigation to complete
page.wait_for_load_state("networkidle")

# Wait for a specific URL pattern
page.wait_for_url("**/dashboard")
```

### Extract structured data
```python
from playwright.sync_api import sync_playwright
import json

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(URL)

    items = page.query_selector_all(".product-card")
    results = []
    for item in items:
        name = item.query_selector(".name").inner_text()
        price = item.query_selector(".price").inner_text()
        results.append({"name": name, "price": price})

    print(json.dumps(results, indent=2))
    browser.close()
```

## Workflow Pattern

For any browser automation task:

1. **Check Playwright is installed** (first-run setup above)
2. **Write a Python script** to the workspace if the task is multi-step
3. **Execute it** via the exec tool
4. **Return results** to the user (text, data, or path to screenshots)

## Tips

- Always use `headless=True` unless the user specifically needs a visible browser
- Set reasonable timeouts: `page.goto(url, timeout=15000)`
- Use `page.wait_for_load_state("networkidle")` for JS-heavy pages
- Close the browser in a `finally` block or use `with` context managers
- For sites needing JavaScript rendering, add `page.wait_for_timeout(2000)` as fallback
- Store screenshots and PDFs in `/tmp/` or the workspace directory
