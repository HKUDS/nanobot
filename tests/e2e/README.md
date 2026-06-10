# computer_use end-to-end tests

Real vision models (via **OpenRouter**) drive the real backends through the full
agent loop. Gated by env vars, excluded from default CI.

## What it proves

- Model-agnostic screenshot delivery: every model goes through one
  OpenAI-compatible endpoint (OpenRouter); screenshots come back as follow-up
  **user** messages, so no provider-specific path is exercised.
- The `computer_use` tool + backends actually see the screen and act
  (read a number, click a button, type into a field).

## Requirements

```bash
pip install 'nanobot-ai[computer-use]'
playwright install chromium          # for the browser backend
```

Models must be **vision + tool-calling** capable on OpenRouter.

## Run the browser e2e locally (no Docker, headless)

```bash
COMPUTER_USE_E2E=1 OPENROUTER_API_KEY=sk-or-... \
  pytest tests/e2e/test_computer_use_e2e.py -v -s
```

Pick models explicitly (default: claude-sonnet-4.5 / gpt-4o / gemini-2.5-pro):

```bash
COMPUTER_USE_E2E_MODELS="anthropic/claude-sonnet-4.5,openai/gpt-4o" \
COMPUTER_USE_E2E=1 OPENROUTER_API_KEY=sk-or-... \
  pytest tests/e2e/test_computer_use_e2e.py -v -s
```

Vision models are non-deterministic; each scenario retries
`COMPUTER_USE_E2E_ATTEMPTS` (default 2) times and passes if any attempt succeeds.

## Run in the sandbox (Docker; also covers the desktop/pyautogui backend)

```bash
docker build -f tests/e2e/Dockerfile -t nanobot-cu-e2e .
docker run --rm -e OPENROUTER_API_KEY=sk-or-... -e COMPUTER_USE_E2E=1 nanobot-cu-e2e
```

The container starts Xvfb on `:99` so the desktop backend (PyAutoGUI + scrot)
works headlessly and contained — it never touches a real machine.

## Scenarios (`model × scenario` matrix)

| Test | What it checks |
|------|----------------|
| `test_read_screen` | reads the rendered number `42` from a screenshot (perception) |
| `test_click_button` | clicks **Submit**; asserts `#status == "SUBMITTED"` via the DOM (click accuracy) |
| `test_type_and_submit` | types a name + clicks **Greet**; asserts the greeting (multi-step loop) |

## Findings (first real run, June 2026, via OpenRouter)

Matrix of 5 model families × 3 scenarios:

| Model | read_screen | click_button | type_and_submit |
|-------|:----------:|:-----------:|:--------------:|
| anthropic/claude-sonnet-4.5 | ✅ | ✅ | ✅ |
| openai/gpt-4o | ✅ | ❌ | ❌ |
| google/gemini-2.5-pro | ✅ | ❌ | ❌ |
| qwen/qwen3-vl-235b-a22b-instruct | ✅ | ❌ | ❌ |
| x-ai/grok-4.3 | ✅ | ❌ | ❌ |

**Takeaway:** the model-agnostic *plumbing* works for everyone — all 5 models
received the screenshot (delivered as a user message) and read the on-screen
number. But **pixel-precise clicking only worked with the computer-use-trained
model (Claude)**. Diagnostics showed gpt-4o clicking a round-number guess
`(100,100)` for a button at `(37,156)`, and qwen3-vl emitting an `[x,y]` array
(now supported) but still mis-grounding the y coordinate. This matches the
field: general/GUI VLMs perceive well but ground pixel coordinates poorly.

**Implication for broad model support:** for the *browser* backend, a
DOM/accessibility-based interaction mode (click an element by ref/description
instead of by pixel — how browser-use / Playwright-MCP work) would make action
reliable across *any* tool-capable model, including non-vision ones. That is the
recommended next step beyond this pixel-based v1.

## Browser DOM mode (model-agnostic) — recommended for the web

`tests/e2e/test_browser_dom_e2e.py` and `tests/e2e/test_browser_complex_e2e.py`
exercise the **`browser`** tool, which acts by element **ref** (DOM/accessibility
snapshot) instead of pixels. This removes the pixel-grounding limitation above:
the same models that miss pixel clicks succeed here.

DOM matrix (simple scenarios) — the models that FAILED pixel clicking:

| Model | DOM click | DOM type+submit | read_text (no vision) |
|-------|:--------:|:--------------:|:--------------------:|
| openai/gpt-4o | ✅ | ✅ | flaky |
| google/gemini-2.5-pro | ✅ | flaky | ✅ |
| qwen/qwen3-vl-235b | ✅ | ✅ | ✅ |

Click went from **0/3 in pixel mode to 3/3 in DOM mode.** Because DOM mode needs
no pixel grounding (run with `include_screenshot=false`), it works with ANY
tool-calling model — including non-vision ones.

**Complex flows** (`test_browser_complex_e2e.py`) drive a small local web app
(served over HTTP so localStorage + navigation work), pages in `tests/e2e/pages/`:

- multi-field form: text inputs + `<select>` + radio group + checkbox + submit
- add-to-cart + checkout across two pages, verifying the cart total
- pick the correct row out of 60 (selecting among many similar elements)
- login (two fields + submit) following the redirect to a dashboard

Default models: `openai/gpt-5.1`, `anthropic/claude-sonnet-4.5` (override with
`COMPUTER_USE_E2E_MODELS`).

```bash
COMPUTER_USE_E2E=1 OPENROUTER_API_KEY=sk-or-... \
  pytest tests/e2e/test_browser_complex_e2e.py -v
```

## Cost

Each scenario makes several model calls with screenshots (~1–2k tokens each).
Keep the model list small; check your OpenRouter spend. The full 5×3 matrix
above cost a few cents and took ~5 minutes.
