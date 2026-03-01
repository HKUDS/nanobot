# Computer Use

> **Status: Not implemented**
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/computer-use

## What It Is

Agents that "see" screens via screenshots and "act" through UI interactions. Automates form filling, web testing, cross-site research, and more.

## Gemini API Capabilities

### Models

- `gemini-2.5-computer-use-preview-10-2025`
- `gemini-3-pro-preview` (built-in support)
- `gemini-3-flash-preview` (built-in support)

### Token limits

- Input: 128,000 tokens
- Output: 64,000 tokens

### Four-step loop

1. **Send:** screenshot + user goal → model
2. **Receive:** model returns `function_call` (UI action)
3. **Execute:** client runs the action
4. **Capture:** screenshot after action → send back

### 14 supported UI actions

| Action | Purpose |
|--------|---------|
| `open_web_browser` | Launch browser |
| `navigate` | Go to URL |
| `click_at` | Click coordinates (0–999) |
| `type_text_at` | Type at location |
| `hover_at` | Reveal submenus |
| `key_combination` | Keyboard shortcuts |
| `scroll_document` | Scroll page |
| `scroll_at` | Scroll element |
| `drag_and_drop` | Drag between coordinates |
| `wait_5_seconds` | Pause for loading |
| `go_back` / `go_forward` | Browser history |
| `search` | Go to search engine |

### Safety

- `safety_decision` field: regular / requires confirmation
- Human-in-the-loop for risky actions
- Custom functions for non-browser environments (e.g., Android)

### Requirements

- Sandboxed execution environment (VM, container, isolated browser)
- Screenshot capture capability (e.g., Playwright)
- Recommended resolution: 1440x900
- Normalized 1000x1000 coordinate grid

## Nanobot Implementation

Not implemented. No screen interaction, browser automation, or screenshot-based agent loops.

**Potential use:** automated web research, form filling, browser testing via chat command.
