# Web Interface Plan

## Goal

Add a web interface as **another interface layer**, alongside CLI. Same level, same capabilities.

```
CLI ──┐
      ├──▶ AgentLoop (core, unchanged)
Web ──┘
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Backend: FastAPI + SSE                                  │
│  - /api/chat    → SSE streaming endpoint                 │
│  - /api/sessions → CRUD for sessions                     │
│  - /static      → serve frontend                         │
└─────────────────────────────────────────────────────────┘
                         │
                         ▼ calls
┌─────────────────────────────────────────────────────────┐
│  AgentLoop.process_direct()  ← 100% reuse existing code │
│  - All tools, memory, sessions, MCP available           │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  Frontend: Single HTML file + vanilla JS                 │
│  - Tailwind CSS (CDN)                                    │
│  - Marked.js (CDN) for Markdown                          │
│  - EventSource for SSE streaming                         │
└─────────────────────────────────────────────────────────┘
```

## Implementation Steps

### 1. Backend (`nanobot/web/`)

```
nanobot/web/
├── __init__.py
├── server.py          # FastAPI app, ~100 lines
└── static/
    └── index.html     # Single page app, ~200 lines
```

**Key endpoints:**

```python
# POST /api/chat - Stream response via SSE
async def chat(message: str, session_id: str = "web:default"):
    async def stream():
        async for chunk in agent.process_direct(
            message,
            session_key=session_id,
            on_progress=lambda msg: yield f"event: progress\ndata: {msg}\n\n"
        ):
            yield f"data: {chunk}\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream")

# GET  /api/sessions      - List sessions
# GET  /api/sessions/{id}  - Get session history
# DEL  /api/sessions/{id}  - Delete session
```

### 2. Frontend (`static/index.html`)

- Input box + send button
- Chat history container
- SSE client for streaming
- Markdown rendering
- Session switcher

### 3. CLI Integration

Add new command:
```bash
nanobot web        # Start web server on :8000
nanobot web -p 3000  # Custom port
```

## Tech Stack Rationale

| Choice | Why |
|--------|-----|
| FastAPI | nanobot already uses asyncio, native fit |
| SSE | Simpler than WebSocket, one-way streaming is all we need |
| Vanilla JS | Zero build step, single file, easy to modify |
| Tailwind CDN | No npm, quick styling |

## Dependencies

Add to `pyproject.toml`:
```toml
[project.optional-dependencies]
web = ["fastapi", "uvicorn[standard]"]
```

## Estimated Effort

- Backend: ~100 lines
- Frontend: ~200 lines
- Total: ~300 lines

## Reference

See `nanobot/cli/commands.py` for how CLI uses `AgentLoop.process_direct()`.
Web will do the exact same thing.
