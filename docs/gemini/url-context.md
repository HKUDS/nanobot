# URL Context

> **Status: Not implemented** — scorpion has agent-side URL fetching
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/url-context

## What It Is

Gemini natively fetches and analyzes content from provided URLs. Two-step retrieval: checks index cache first, then live fallback.

## Gemini API Capabilities

### Configuration

```python
tools = [{"url_context": {}}]
```

### Limits

- Max 20 URLs per request
- Max 34MB per URL
- URLs must be publicly accessible

### Supported content

- Text formats: HTML, JSON, text, XML, CSS, JS, CSV, RTF
- Images: PNG, JPEG, BMP, WebP
- PDFs

### Not supported

- Paywalled content
- YouTube videos
- Google Workspace files
- Video/audio files
- Cannot combine with function calling

### Response metadata

`url_context_metadata` with retrieved URLs and status. Content counts toward input tokens.

### Supported models

Gemini 3.1 Pro, 3 Flash, 2.5 Pro/Flash/Flash-Lite

## Nanobot Implementation

**Current URL fetching:** Agent-side tool (`scorpion/agent/tools/web.py`)

```python
# WebFetchTool: fetches URLs via httpx, extracts with Readability
# Converts HTML to markdown, returns as tool result text
```

URL fetching is an agent tool, not Gemini-native. Content is fetched by the agent and passed as text in tool results.

**What Gemini URL Context would enable:**
- Model fetches and processes URLs natively (no agent tool call needed)
- Better content extraction (Gemini's own parser)
- PDF and image analysis from URLs
- Response metadata with retrieval status
- One fewer tool call round-trip
