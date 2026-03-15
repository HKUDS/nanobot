"""
Nanobot Web UI Server
======================
Self-contained HTTP + WebSocket server.  Zero extra dependencies — uses only
the packages already listed in nanobot's pyproject.toml:

  • Python stdlib  (http.server, threading, asyncio, json, …)
  • websockets >=16.0  (already a dependency)

HTTP  → port 8790   serves chat.html
WS    → port 8791   handles chat messages in real-time

Usage:
    python -m webui.server                      # from nano1/nanobot/
    python nano1/nanobot/webui/server.py        # directly
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import websockets
from websockets.server import WebSocketServerProtocol

# ── Make sure nanobot package is importable ──────────────────────────────────
_PKG_ROOT = Path(__file__).parents[1]          # nano1/nanobot/
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

# ── Config ──────────────────────────────────────────────────────────────────
HTTP_HOST = "127.0.0.1"
HTTP_PORT = 8790
WS_HOST   = "127.0.0.1"
WS_PORT   = 8791

_HTML_FILE = Path(__file__).parent / "chat.html"

# ── HTTP handler — serves chat.html ─────────────────────────────────────────

class _ChatHTTPHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/chat", "/index.html"):
            try:
                content = _HTML_FILE.read_bytes()
            except FileNotFoundError:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"chat.html not found")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")

    def log_message(self, fmt, *args):  # suppress default access logs
        pass


def _run_http_server() -> None:
    server = HTTPServer((HTTP_HOST, HTTP_PORT), _ChatHTTPHandler)
    server.serve_forever()


# ── Nanobot agent factory ────────────────────────────────────────────────────

def _create_provider(config):
    """Minimal provider factory that handles auto/litellm/custom/openai_codex."""
    from nanobot.providers.base import GenerationSettings

    model = config.agents.defaults.model
    provider_name = config.get_provider_name(model)
    p = config.get_provider(model)

    if provider_name == "openai_codex" or model.startswith("openai-codex/"):
        from nanobot.providers.openai_codex_provider import OpenAICodexProvider
        provider = OpenAICodexProvider(default_model=model)

    elif provider_name == "azure_openai":
        from nanobot.providers.azure_openai_provider import AzureOpenAIProvider
        provider = AzureOpenAIProvider(
            api_key=p.api_key,
            api_base=p.api_base,
            default_model=model,
        )

    elif provider_name == "custom":
        from nanobot.providers.custom_provider import CustomProvider
        provider = CustomProvider(
            api_key=p.api_key if p else "no-key",
            api_base=config.get_api_base(model) or "http://localhost:8000/v1",
            default_model=model,
        )

    else:
        from nanobot.providers.litellm_provider import LiteLLMProvider
        provider = LiteLLMProvider(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(model),
            default_model=model,
            extra_headers=p.extra_headers if p else None,
            provider_name=provider_name,
        )

    defaults = config.agents.defaults
    provider.generation = GenerationSettings(
        temperature=defaults.temperature,
        max_tokens=defaults.max_tokens,
        reasoning_effort=defaults.reasoning_effort,
    )
    return provider


def _create_agent():
    """Bootstrap a nanobot AgentLoop from the default config."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.config.loader import load_config
    from nanobot.session.manager import SessionManager

    config = load_config()
    provider = _create_provider(config)

    workspace = config.workspace_path
    workspace.mkdir(parents=True, exist_ok=True)

    bus = MessageBus()
    session_manager = SessionManager(workspace)

    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=workspace,
        model=config.agents.defaults.model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        context_window_tokens=config.agents.defaults.context_window_tokens,
        web_search_config=config.tools.web.search,
        web_proxy=config.tools.web.proxy or None,
        exec_config=config.tools.exec,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        session_manager=session_manager,
        mcp_servers=config.tools.mcp_servers,
    )

    return agent, config.agents.defaults.model


# ── WebSocket handler ────────────────────────────────────────────────────────

_agent = None
_model_name = "unknown"


async def _ws_handler(websocket: WebSocketServerProtocol) -> None:
    """Handle a single WebSocket connection (one session per connection)."""
    session_id = f"webui:{id(websocket)}"

    # Send a welcome / ready message
    await websocket.send(json.dumps({
        "type": "ready",
        "model": _model_name,
    }))

    try:
        async for raw in websocket:
            try:
                data = json.loads(raw)
                kind = data.get("type", "message")

                # Ping/keepalive
                if kind == "ping":
                    await websocket.send(json.dumps({"type": "pong"}))
                    continue

                msg = data.get("message", "").strip()
                if not msg:
                    continue

                # Tell the UI we're working
                await websocket.send(json.dumps({"type": "status", "text": "Thinking..."}))

                # Stream tool-call progress to UI
                async def on_progress(text: str, **_: object) -> None:
                    try:
                        await websocket.send(json.dumps({"type": "progress", "text": text}))
                    except Exception:
                        pass

                # Run agent
                response = await _agent.process_direct(
                    msg,
                    session_key=session_id,
                    channel="web",
                    chat_id=session_id,
                    on_progress=on_progress,
                )

                await websocket.send(json.dumps({
                    "type": "response",
                    "text": response or "(no response)",
                }))

            except json.JSONDecodeError:
                await websocket.send(json.dumps({
                    "type": "error",
                    "text": "Invalid JSON message",
                }))
            except Exception as exc:
                await websocket.send(json.dumps({
                    "type": "error",
                    "text": f"Agent error: {exc}",
                }))

    except websockets.exceptions.ConnectionClosed:
        pass


# ── Main ─────────────────────────────────────────────────────────────────────

async def _main_async() -> None:
    global _agent, _model_name

    print("  Loading nanobot agent...", flush=True)
    _agent, _model_name = _create_agent()
    print(f"  Agent ready  (model: {_model_name})", flush=True)

    async with websockets.serve(_ws_handler, WS_HOST, WS_PORT):
        print(f"  WebSocket  -> ws://{WS_HOST}:{WS_PORT}")
        print(f"  Chat UI    -> http://{HTTP_HOST}:{HTTP_PORT}")
        print()
        print("  Press Ctrl+C to stop.")
        print()
        await asyncio.Future()  # run forever


def main() -> None:
    print()
    print("=" * 43)
    print("     Nanobot  Web  UI  Server")
    print("=" * 43)
    print()

    # Start HTTP server in background thread
    http_thread = threading.Thread(target=_run_http_server, daemon=True, name="http-server")
    http_thread.start()
    print(f"  HTTP server started on port {HTTP_PORT}", flush=True)

    try:
        asyncio.run(_main_async())
    except KeyboardInterrupt:
        print("\n  Stopped.")


if __name__ == "__main__":
    main()
