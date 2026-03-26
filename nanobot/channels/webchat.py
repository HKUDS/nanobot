"""Web Chat channel implementation with WebSocket support."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from aiohttp import web, WSMsgType
from loguru import logger
from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Base


class WebChatConfig(Base):
    """Web Chat channel configuration."""

    enabled: bool = True  # Enabled by default for easy local development
    host: str = "0.0.0.0"
    port: int = 8080
    allow_from: list[str] = Field(default_factory=lambda: ["*"])
    streaming: bool = True
    static_path: str | None = None  # Custom static files path
    show_typing: bool = True  # Show "typing..." indicator while processing
    typing_emoji: str = "🔄"  # Emoji to show while processing


class WebChatChannel(BaseChannel):
    """
    Web Chat channel that provides a web-based chat interface.

    Features:
    - WebSocket-based real-time messaging
    - Optional Server-Sent Events (SSE) fallback
    - Built-in HTML chat interface
    - Support for streaming responses
    - Multi-user support with session management
    """

    name = "webchat"
    display_name = "Web Chat"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return WebChatConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = WebChatConfig.model_validate(config)
        super().__init__(config, bus)
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        # Map chat_id -> list of WebSocket connections
        self._connections: dict[str, list[web.WebSocketResponse]] = defaultdict(list)
        # Map session_id -> chat_id for tracking user sessions
        self._session_chat_map: dict[str, str] = {}
        # Message buffers for streaming (chat_id -> accumulated content)
        self._stream_buffers: dict[str, str] = {}
        # Track typing state per chat_id
        self._typing_sent: set[str] = set()

    async def start(self) -> None:
        """Start the Web Chat HTTP/WebSocket server."""
        self._running = True
        host = getattr(self.config, "host", "0.0.0.0")
        port = getattr(self.config, "port", 8080)

        self._app = web.Application()
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/ws", self._handle_websocket)
        self._app.router.add_post("/api/message", self._handle_http_message)
        self._app.router.add_get("/api/health", self._handle_health)

        # Serve custom static files if configured
        static_path = getattr(self.config, "static_path", None)
        if static_path and Path(static_path).exists():
            self._app.router.add_static("/static", static_path)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host, port)
        await self._site.start()

        logger.info("Web Chat server started at http://{}:{}", host, port)

        # Keep running until stopped
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the Web Chat server."""
        self._running = False

        # Close all WebSocket connections
        for chat_id, connections in list(self._connections.items()):
            for ws in connections:
                if not ws.closed:
                    await ws.close()
        self._connections.clear()
        self._session_chat_map.clear()

        # Cleanup server
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()

        logger.info("Web Chat server stopped")

    async def _send_typing(self, chat_id: str, is_typing: bool = True) -> None:
        """Send typing indicator to web clients."""
        connections = self._connections.get(chat_id, [])
        if not connections:
            return

        payload = {
            "type": "typing",
            "is_typing": is_typing,
            "emoji": getattr(self.config, "typing_emoji", "🔄"),
        }

        for ws in connections:
            if not ws.closed:
                try:
                    await ws.send_json(payload)
                except Exception as e:
                    logger.warning("Failed to send typing indicator: {}", e)

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message to web clients."""
        chat_id = msg.chat_id
        connections = self._connections.get(chat_id, [])

        if not connections:
            logger.debug("No active WebSocket connections for chat_id: {}", chat_id)
            return

        # Clear typing indicator when sending actual message
        if chat_id in self._typing_sent:
            await self._send_typing(chat_id, is_typing=False)
            self._typing_sent.discard(chat_id)

        payload = {
            "type": "message",
            "content": msg.content,
            "media": msg.media or [],
            "metadata": msg.metadata,
        }

        for ws in connections:
            if not ws.closed:
                try:
                    await ws.send_json(payload)
                except Exception as e:
                    logger.warning("Failed to send message via WebSocket: {}", e)

    async def send_delta(self, chat_id: str, delta: str, metadata: dict[str, Any] | None = None) -> None:
        """Send a streaming delta to web clients."""
        meta = metadata or {}
        connections = self._connections.get(chat_id, [])

        if not connections:
            return

        # Clear typing indicator on first delta
        if chat_id in self._typing_sent:
            await self._send_typing(chat_id, is_typing=False)
            self._typing_sent.discard(chat_id)

        # Accumulate buffer for potential re-sends
        if chat_id not in self._stream_buffers:
            self._stream_buffers[chat_id] = ""
        self._stream_buffers[chat_id] += delta

        payload = {
            "type": "delta",
            "delta": delta,
            "content": self._stream_buffers[chat_id],
            "is_end": meta.get("_stream_end", False),
            "metadata": meta,
        }

        for ws in connections:
            if not ws.closed:
                try:
                    await ws.send_json(payload)
                except Exception as e:
                    logger.warning("Failed to send delta via WebSocket: {}", e)

        # Clean up buffer on stream end
        if meta.get("_stream_end"):
            self._stream_buffers.pop(chat_id, None)

    async def _handle_index(self, request: web.Request) -> web.Response:
        """Serve the main chat interface HTML."""
        html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nanobot Web Chat</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }
        .header {
            background: #1a1a2e;
            color: white;
            padding: 1rem;
            text-align: center;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .header h1 { font-size: 1.25rem; font-weight: 500; }
        .chat-container {
            flex: 1;
            overflow-y: auto;
            padding: 1rem;
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
        }
        .message {
            max-width: 80%;
            padding: 0.75rem 1rem;
            border-radius: 1rem;
            word-wrap: break-word;
            animation: fadeIn 0.2s ease;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .message.user {
            align-self: flex-end;
            background: #007bff;
            color: white;
            border-bottom-right-radius: 0.25rem;
        }
        .message.bot {
            align-self: flex-start;
            background: white;
            color: #333;
            border-bottom-left-radius: 0.25rem;
            box-shadow: 0 1px 2px rgba(0,0,0,0.1);
        }
        .message.streaming {
            border-left: 3px solid #007bff;
        }
        .input-container {
            background: white;
            padding: 1rem;
            border-top: 1px solid #e0e0e0;
            display: flex;
            gap: 0.5rem;
        }
        #messageInput {
            flex: 1;
            padding: 0.75rem 1rem;
            border: 1px solid #ddd;
            border-radius: 1.5rem;
            outline: none;
            font-size: 1rem;
        }
        #messageInput:focus {
            border-color: #007bff;
        }
        #sendBtn {
            padding: 0.75rem 1.5rem;
            background: #007bff;
            color: white;
            border: none;
            border-radius: 1.5rem;
            cursor: pointer;
            font-size: 1rem;
            transition: background 0.2s;
        }
        #sendBtn:hover { background: #0056b3; }
        #sendBtn:disabled { background: #ccc; cursor: not-allowed; }
        .status {
            text-align: center;
            padding: 0.5rem;
            font-size: 0.875rem;
            color: #666;
        }
        .status.connected { color: #28a745; }
        .status.disconnected { color: #dc3545; }
        .typing-indicator {
            display: flex;
            gap: 0.25rem;
            padding: 0.5rem 1rem;
        }
        .typing-indicator span {
            width: 8px;
            height: 8px;
            background: #999;
            border-radius: 50%;
            animation: bounce 1.4s infinite ease-in-out both;
        }
        .typing-indicator span:nth-child(1) { animation-delay: -0.32s; }
        .typing-indicator span:nth-child(2) { animation-delay: -0.16s; }
        @keyframes bounce {
            0%, 80%, 100% { transform: scale(0); }
            40% { transform: scale(1); }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🤖 Nanobot Web Chat</h1>
    </div>
    <div class="status disconnected" id="status">Disconnected</div>
    <div class="chat-container" id="chatContainer"></div>
    <div class="input-container">
        <input type="text" id="messageInput" placeholder="Type a message..." autocomplete="off">
        <button id="sendBtn">Send</button>
    </div>

    <script>
        const chatContainer = document.getElementById('chatContainer');
        const messageInput = document.getElementById('messageInput');
        const sendBtn = document.getElementById('sendBtn');
        const statusEl = document.getElementById('status');

        let ws = null;
        let reconnectAttempts = 0;
        let currentBotMessage = null;

        // Parse URL params for fixed session/agent ID
        const urlParams = new URLSearchParams(window.location.search);
        const urlSessionId = urlParams.get('session_id') || urlParams.get('session') || urlParams.get('sid');
        const agentId = urlParams.get('agent') || urlParams.get('agent_id');

        // Priority: URL session_id > URL agent_id > localStorage > generate new
        let sessionId;
        if (urlSessionId) {
            sessionId = urlSessionId;
        } else if (agentId) {
            // Map agent to a fixed session ID: agent_{agentId}
            sessionId = 'agent_' + agentId;
        } else {
            sessionId = localStorage.getItem('webchat_session_id') || generateSessionId();
            localStorage.setItem('webchat_session_id', sessionId);
        }

        // Update page title if agent specified
        if (agentId) {
            document.querySelector('.header h1').textContent = `🤖 ${agentId}`;
            document.title = `${agentId} - Nanobot Chat`;
        }

        function generateSessionId() {
            return 'web_' + Math.random().toString(36).substr(2, 9);
        }

        function connect() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws?session_id=${sessionId}`);

            ws.onopen = () => {
                console.log('WebSocket connected');
                statusEl.textContent = 'Connected';
                statusEl.className = 'status connected';
                sendBtn.disabled = false;
                reconnectAttempts = 0;
            };

            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                handleMessage(data);
            };

            ws.onclose = () => {
                console.log('WebSocket disconnected');
                statusEl.textContent = 'Disconnected - Reconnecting...';
                statusEl.className = 'status disconnected';
                sendBtn.disabled = true;

                // Exponential backoff
                const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000);
                reconnectAttempts++;
                setTimeout(connect, delay);
            };

            ws.onerror = (error) => {
                console.error('WebSocket error:', error);
            };
        }

        // handleMessage is defined below with typing support

        function addMessage(text, sender) {
            const msgDiv = document.createElement('div');
            msgDiv.className = `message ${sender}`;
            msgDiv.textContent = text;
            chatContainer.appendChild(msgDiv);
            scrollToBottom();
            return msgDiv;
        }

        function scrollToBottom() {
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }

        function sendMessage() {
            const text = messageInput.value.trim();
            if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;

            addMessage(text, 'user');
            ws.send(JSON.stringify({ text }));
            messageInput.value = '';
            currentBotMessage = null;
        }
        
        sendBtn.addEventListener('click', sendMessage);
        messageInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') sendMessage();
        });
        
        // Typing indicator element
        let typingIndicator = null;
        
        function showTyping(emoji) {
            if (typingIndicator) return;
            typingIndicator = document.createElement('div');
            typingIndicator.className = 'message bot typing-message';
            typingIndicator.innerHTML = `<span style="margin-right: 8px;">${emoji}</span><span class="typing-indicator"><span></span><span></span><span></span></span>`;
            chatContainer.appendChild(typingIndicator);
            scrollToBottom();
        }
        
        function hideTyping() {
            if (typingIndicator) {
                typingIndicator.remove();
                typingIndicator = null;
            }
        }
        
        function handleMessage(data) {
            if (data.type === 'typing') {
                if (data.is_typing) {
                    showTyping(data.emoji || '🔄');
                } else {
                    hideTyping();
                }
            } else if (data.type === 'delta') {
                hideTyping();
                if (!currentBotMessage) {
                    currentBotMessage = addMessage('', 'bot');
                    currentBotMessage.classList.add('streaming');
                }
                currentBotMessage.textContent = data.content;
                scrollToBottom();
        
                if (data.is_end) {
                    currentBotMessage.classList.remove('streaming');
                    currentBotMessage = null;
                }
            } else if (data.type === 'message') {
                hideTyping();
                if (currentBotMessage) {
                    currentBotMessage.classList.remove('streaming');
                    currentBotMessage = null;
                }
                addMessage(data.content, 'bot');
            }
        }
        
        // Override previous handleMessage
        window.handleMessage = handleMessage;

        // Initial connection
        connect();
    </script>
</body>
</html>"""
        return web.Response(text=html, content_type="text/html")

    async def _handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """Handle WebSocket connections."""
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        # Get or create session/chat ID
        session_id = request.query.get("session_id") or str(uuid.uuid4())
        chat_id = self._session_chat_map.get(session_id)
        if not chat_id:
            chat_id = f"webchat_{session_id}"
            self._session_chat_map[session_id] = chat_id

        # Track connection
        self._connections[chat_id].append(ws)
        logger.info("WebSocket client connected: session={}, chat_id={}", session_id, chat_id)

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        text = data.get("text", "").strip()
                        if text:
                            # Show typing indicator before processing
                            if getattr(self.config, "show_typing", True):
                                await self._send_typing(chat_id, is_typing=True)
                                self._typing_sent.add(chat_id)
                            await self._handle_message(
                                sender_id=session_id,
                                chat_id=chat_id,
                                content=text,
                                metadata={"session_id": session_id, "via": "websocket"},
                            )
                    except json.JSONDecodeError:
                        logger.warning("Invalid JSON from WebSocket client")
                elif msg.type == WSMsgType.ERROR:
                    logger.error("WebSocket error: {}", ws.exception())
        except Exception as e:
            logger.error("WebSocket handler error: {}", e)
        finally:
            # Remove connection
            if chat_id in self._connections:
                self._connections[chat_id] = [c for c in self._connections[chat_id] if c != ws]
                if not self._connections[chat_id]:
                    del self._connections[chat_id]
            logger.info("WebSocket client disconnected: session={}, chat_id={}", session_id, chat_id)

        return ws

    async def _handle_http_message(self, request: web.Request) -> web.Response:
        """Handle HTTP POST messages (for non-WebSocket clients)."""
        try:
            data = await request.json()
            text = data.get("text", "").strip()
            session_id = data.get("session_id") or str(uuid.uuid4())

            if not text:
                return web.json_response({"error": "Empty message"}, status=400)

            chat_id = f"webchat_{session_id}"

            await self._handle_message(
                sender_id=session_id,
                chat_id=chat_id,
                content=text,
                metadata={"session_id": session_id, "via": "http"},
            )

            return web.json_response({"status": "ok", "chat_id": chat_id})
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error("Error handling HTTP message: {}", e)
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({
            "status": "ok",
            "channel": self.name,
            "running": self._running,
            "active_sessions": len(self._session_chat_map),
            "active_connections": sum(len(conns) for conns in self._connections.values()),
        })
