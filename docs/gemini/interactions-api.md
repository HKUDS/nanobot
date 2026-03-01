# Interactions API

> **Status: Not implemented**
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/interactions

## What It Is

Unified interface for Gemini models and agents. Simplifies state management, tool orchestration, and long-running tasks. Improved alternative to `generateContent`. Currently in Beta.

## Gemini API Capabilities

### Key differences from generateContent

- **Server-side state** — `previous_interaction_id` continues conversations without resending history
- **Central resource model** — `Interaction` object with complete turn records
- **Background execution** — `background=True` for long-running tasks
- **Agent support** — works with Deep Research and other agents

### Features

- Stateful multi-turn conversations
- Multimodal input/output
- Function calling + built-in tools (Search, Code Execution, URL Context, Computer Use, File Search)
- MCP integration
- Structured outputs
- Thinking with configurable depth
- 55-day storage (paid) / 1-day (free)

### Supported models

Gemini 3.1 Pro, 3 Flash, 2.5 Pro/Flash/Flash-Lite

### Supported agents

Deep Research (`deep-research-pro-preview-12-2025`)

### Limitations (Beta)

- Cannot combine MCP + Function Call + Built-in tools
- Breaking changes may occur
- Gemini 3 with remote MCP not supported

## Nanobot Implementation

Not implemented. Nanobot manages conversation state client-side via `SessionManager` and sends full history with each request.

**What Interactions API would enable:**
- Server-side conversation state (reduce payload size)
- Native long-running task support
- Deep Research agent access
- Simplified multi-turn orchestration
