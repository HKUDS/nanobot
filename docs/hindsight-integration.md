# Hindsight Integration

## Overview

**Hindsight** is an external semantic memory system for AI agents ([vectorize-io/hindsight](https://github.com/vectorize-io/hindsight)). It supports storing facts and experience (**retain**), semantic search (**recall**), and generating summaries from memory (**reflect**).

In nanobot, Hindsight integration is **optional** and complements the built-in file-based memory (diaries, MEMORY.md):

- Before building the agent context, nanobot calls Hindsight **recall** (and optionally **reflect**) for the current message and injects the result into the system prompt as a "Hindsight (learned memory)" section.
- After the agent responds, the conversation is sent asynchronously to Hindsight via **retain**, so memory is updated over time.

Hindsight runs as a separate service: nanobot only talks to it over HTTP (recall/reflect/retain). Which LLM Hindsight uses (OpenAI, OpenRouter, etc.) is configured on the **Hindsight server**, not in nanobot's config.

## Configuration

Config file: `~/.nanobot/config.json`. Section: `hindsight`.

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `enabled` | bool | `false` | Enable Hindsight (recall/reflect/retain). |
| `base_url` | string | `http://localhost:8888` | Hindsight API base URL. |
| `bank_id` | string | `"default"` | Memory bank ID in Hindsight. |
| `use_reflect` | bool | `false` | When true, also call reflect() and add result to agent context. |
| `bank_id_per_session` | bool | `false` | When true, use per-session bank: `nanobot:{session_key}`. |

### Example

```json
{
  "hindsight": {
    "enabled": true,
    "base_url": "http://localhost:8888",
    "bank_id": "default",
    "use_reflect": false,
    "bank_id_per_session": true
  }
}
```

Install the optional dependency and run a Hindsight server:

```bash
pip install nanobot-ai[hindsight]
# or
pip install hindsight-client
```

## Running Hindsight with Docker (OpenRouter)

Hindsight supports any **OpenAI-compatible** API. OpenRouter provides such an API, so you can point Hindsight at OpenRouter by setting provider to `openai` and base URL to OpenRouter.

### Environment variables for Hindsight

- `HINDSIGHT_API_LLM_PROVIDER=openai` — use OpenAI-compatible protocol.
- `HINDSIGHT_API_LLM_BASE_URL=https://openrouter.ai/api/v1` — OpenRouter endpoint.
- `HINDSIGHT_API_LLM_API_KEY=sk-or-v1-...` — API key from [openrouter.ai](https://openrouter.ai).
- `HINDSIGHT_API_LLM_MODEL` — model ID (e.g. `anthropic/claude-3.5-sonnet` or `openai/gpt-4o`).

### Run the container

```bash
docker run --rm -it -p 8888:8888 -p 9999:9999 \
  -e HINDSIGHT_API_LLM_PROVIDER=openai \
  -e HINDSIGHT_API_LLM_BASE_URL=https://openrouter.ai/api/v1 \
  -e HINDSIGHT_API_LLM_API_KEY=sk-or-v1-YOUR_OPENROUTER_KEY \
  -e HINDSIGHT_API_LLM_MODEL=anthropic/claude-3.5-sonnet \
  -v "$HOME/.hindsight-docker:/home/hindsight/.pg0" \
  ghcr.io/vectorize-io/hindsight:latest
```

- **8888** — API (use this as `hindsight.base_url` in nanobot config, e.g. `http://localhost:8888`).
- **9999** — Hindsight web UI (optional).

Set nanobot config to something like:

```json
"hindsight": {
  "enabled": true,
  "base_url": "http://localhost:8888"
}
```

Then run the gateway or agent; with Hindsight enabled, nanobot will call recall/reflect at `base_url` and send each dialogue to retain after the response. The LLM used by Hindsight itself is determined by the container's environment variables (e.g. OpenRouter).
