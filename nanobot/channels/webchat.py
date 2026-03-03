"""Web channel implementation for a flask server and browser-based chat interface."""

import asyncio
import json
import threading
import uuid
import queue
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sys

from flask import Flask, Response, request, jsonify, render_template_string
from werkzeug.serving import make_server
from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import WebChatConfig


HTML_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="color-scheme" content="light dark">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no" />
  <title>web chat</title>
  <style>
    :root {
      --panel: #7f81861e;
      --line: #8f90a054;
      --accent: #6f5ff07f;
      --accent-dim: #4f46a07f;
      --danger: #9f12397f;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-rounded, "SF Pro Rounded", "Avenir Next", "Trebuchet MS", sans-serif;
      min-height: 100vh;
    }
    .shell {
      display: grid;
      grid-template-columns: 340px 1fr;
      margin: 0;
      padding: 0;
      height: 100vh;
      background: var(--panel);
    }
    .panel {
      overflow: hidden;
      display: flex;
      flex-direction: column;
      height: 100%;
    }
    .chats {
      border-right: 1px solid var(--line);
    }
    .panel h2 {
      margin: 0;
      padding: 16px;
      font-size: 14px;
      font-weight: 600;
      letter-spacing: 0.05em;
      color: var(--ink-soft);
      border-bottom: 1px solid var(--line);
    }
    #chat-list {
      margin: 0;
      padding: 0;
      list-style: none;
      overflow-y: auto;
      flex: 1;
    }
    #chat-list li {
      padding: 12px 16px;
      border-bottom: 1px solid #7f7f7f5f;
      cursor: pointer;
      transition: background .15s ease;
    }
    #chat-list li.active { border-left: 3px solid var(--accent); }
    #chat-list .meta { color: var(--ink-soft); font-size: 11px; margin-top: 4px; }

    form {
      display: flex;
      gap: 8px;
      padding: 12px;
      border-top: 1px solid var(--line);
    }
    input, textarea, button {
      font: inherit;
      border-radius: 6px;
      border: 1px solid var(--line);
      padding: 8px 12px;
    }
    button {
      cursor: pointer;
      background: var(--accent);
      border-color: var(--accent);
      transition: background .15s ease;
    }
    button:hover { background: var(--accent-dim); }
    button[disabled] { cursor: not-allowed; opacity: 0.7; }

    .chat {
      display: grid;
      grid-template-rows: 1fr auto;
      height: 100%;
    }
    #back-btn {
      display: none;
      margin-right: 12px;
      padding: 4px 8px;
      background: transparent;
      color: var(--accent);
      border-color: var(--accent);
      font-size: 12px;
    }
    #messages {
      padding: 20px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .msg {
      max-width: 84%;
      border-radius: 12px;
      padding: 10px 12px;
      border: 1px solid var(--line);
      white-space: pre-wrap;
      line-height: 1.35;
      animation: fadein .2s ease;
    }
    .user { align-self: flex-end; background: #94a1b933; border-color: var(--line); }
    .assistant { align-self: flex-start; background: #7f7f7f1f; }
    .system { align-self: center; font-size: 12px; }
    .error { border-color: #fecdd3; background: #fff1f27f; color: var(--danger); }

    #send-form { border-top: 1px solid var(--line); }
    #prompt { flex: 1; min-height: 54px; max-height: 170px; resize: vertical; }

    @keyframes fadein {
      from { opacity: 0; transform: translateY(3px); }
      to { opacity: 1; transform: translateY(0); }
    }

    /* Mobile specific styles */
    @media (max-width: 768px) {
      body { background: var(--bg); }
      .shell {
        display: block;
        margin: 0;
        padding: 0;
        height: 100vh;
      }
      .panel {
        border: none;
        border-radius: 0;
        height: 100vh;
        width: 100%;
        box-shadow: none;
      }
      .chats, .chat {
        display: none;
        min-height: 100vh;
      }
      .shell.show-list .chats { display: flex; }
      .shell.show-chat .chat { display: grid; }
      #back-btn { display: inline-block; }
    }
  </style>
</head>
<body>
  <main class="shell show-list">
    <section class="panel chats">
      <h2>Chats</h2>
      <ul id="chat-list"></ul>
      <form id="new-chat-form">
        <input id="chat-title" placeholder="New chat title" required />
        <button type="submit">Create</button>
      </form>
    </section>

    <section class="panel chat">
      <div id="messages"></div>
      <form id="send-form">
        <button id="back-btn">&larr; Back</button>
        <textarea id="prompt" placeholder="Type a message" required></textarea>
        <button type="submit" id="send-btn" aria-label="Send">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"
               stroke-linecap="round" stroke-linejoin="round" width="18" height="18">
            <line x1="22" y1="2" x2="11" y2="13"/>
            <polygon points="22 2 15 22 11 13 2 9 22 2"/>
          </svg>
        </button>
      </form>
    </section>
  </main>

  <script>
    let chats = [];
    let activeChatId = null;
    let eventSource = null;

    const shell = document.querySelector('.shell');
    const chatList = document.getElementById('chat-list');
    const messages = document.getElementById('messages');
    const newChatForm = document.getElementById('new-chat-form');
    const chatTitleInput = document.getElementById('chat-title');
    const sendForm = document.getElementById('send-form');
    const promptBox = document.getElementById('prompt');
    const sendBtn = document.getElementById('send-btn');
    const backBtn = document.getElementById('back-btn');

    function addMessage(role, text, extraClass='') {
      const el = document.createElement('div');
      el.className = `msg ${role} ${extraClass}`;
      el.textContent = text;
      messages.appendChild(el);
      messages.scrollTop = messages.scrollHeight;
    }

    function renderChats() {
      chatList.innerHTML = '';
      for (const t of chats) {
        const li = document.createElement('li');
        if (t.id === activeChatId) li.classList.add('active');
        li.innerHTML = `<div>${t.title}</div><div class="meta">${t.created_at}</div>`;
        li.onclick = () => selectChat(t.id);
        chatList.appendChild(li);
      }
    }

    function loadChats() {
      const data = localStorage.getItem('webchat_chats');
      chats = data ? JSON.parse(data) : [];
      if (!activeChatId && chats.length && window.innerWidth > 768) {
        activeChatId = chats[0].id;
      }
      renderChats();
      if (activeChatId) selectChat(activeChatId);
    }

    function saveChats(list) {
      localStorage.setItem('webchat_chats', JSON.stringify(list));
    }

    function loadMessages(id) {
      const data = localStorage.getItem(`webchat_messages_${id}`);
      try {
        return data ? JSON.parse(data) : [];
      } catch (e) {
        return [];
      }
    }

    function saveMessages(id, msgs) {
      localStorage.setItem(`webchat_messages_${id}`, JSON.stringify(msgs));
    }

    function refreshMessages() {
      if (!activeChatId) return;
      const data = localStorage.getItem(`webchat_messages_${activeChatId}`);
      const rows = data ? JSON.parse(data) : [];
      messages.innerHTML = '';
      if (!rows.length) {
        addMessage('system', 'No messages yet. Start the chat.');
      } else {
        rows.forEach(m => addMessage(m.role, m.content, m.role === 'assistant_error' ? 'error' : ''));
      }
    }

    function selectChat(chatId) {
      activeChatId = chatId;
      renderChats();
      const t = chats.find(x => x.id === chatId);
      if (!t) return;

      shell.classList.add('show-chat');
      shell.classList.remove('show-list');

      refreshMessages();
    }

    function setupSSE() {
      if (eventSource) eventSource.close();
      eventSource = new EventSource('/api/events');
      eventSource.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          if (msg.chat_id === activeChatId) {
            const sys = messages.querySelector('.msg.system');
            if (sys) sys.remove();
            const msgs = loadMessages(activeChatId);
            msgs.push(msg);
            saveMessages(activeChatId, msgs);
            addMessage(msg.role, msg.content, msg.role === 'assistant_error' ? 'error' : '');
          }
        } catch (e) {}
      };
      eventSource.onerror = () => {
        setTimeout(setupSSE, 3000);
      };
    }

    backBtn.onclick = () => {
      shell.classList.add('show-list');
      shell.classList.remove('show-chat');
    };

    newChatForm.onsubmit = (ev) => {
      ev.preventDefault();
      const title = chatTitleInput.value.trim();
      if (!title) return;
      const id = ((Math.floor(512 * (1 + Math.random())) + (Date.now() & 0x3FF)) * Date.now()).toString(16);
      const newChat = { id, title, created_at: new Date().toISOString().replace('T', ' ').replace('Z', '') };
      chats.push(newChat);
      saveChats(chats);
      renderChats();
      chatTitleInput.value = '';
      selectChat(newChat.id);
    };

    sendForm.onsubmit = async (ev) => {
      ev.preventDefault();
      if (!activeChatId) return;
      const content = promptBox.value.trim();
      if (!content) return;

      const sys = messages.querySelector('.msg.system');
      if (sys) sys.remove();

      // Add user message locally
      const msgs = loadMessages(activeChatId);
      msgs.push({ role: 'user', content });
      saveMessages(activeChatId, msgs);
      addMessage('user', content);

      promptBox.value = '';
      sendBtn.disabled = true;

      const r = await fetch(`/api/chats/${activeChatId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content })
      });

      if (!r.ok) {
        const data = await r.json();
        addMessage('assistant_error', data.error || 'Request failed', 'error');
      }

      sendBtn.disabled = false;
    };

    loadChats();
    setupSSE();
  </script>
</body>
</html>
"""

class WebChatChannel(BaseChannel):
    """
    Web channel that provides a browser-based chat interface using Flask and SSE.
    """

    name: str = "webchat"

    def __init__(self, config: WebChatConfig, bus: MessageBus):
        super().__init__(config, bus)
        self._server = None
        self._server_thread = None
        self._sse_queues = []
        self._sse_lock = threading.Lock()

        self.app = Flask(__name__)
        self._setup_routes()

    def _setup_routes(self) -> None:
        """Define Flask routes for the chat interface."""

        @self.app.route('/')
        def index():
            return render_template_string(HTML_PAGE)

        @self.app.route('/api/events')
        def events():
            return Response(self._sse_generator(), mimetype='text/event-stream')


        @self.app.route('/api/chats/<chat_id>/messages', methods=['POST'])
        async def post_message(chat_id):
            data = request.json
            content = data.get('content', '').strip()
            if not content:
                return jsonify({"error": "content is required"}), 400

            try:
                # Use the BaseChannel._handle_message directly via await
                await self._handle_message(
                    sender_id="web-user",
                    chat_id=chat_id,
                    content=content
                )
                return jsonify({"status": "accepted"}), 202
            except Exception as e:
                logger.exception("Failed to publish message")
                return jsonify({"error": str(e)}), 500

    def _sse_generator(self) -> Any:
        """Generate SSE events for the event stream."""
        q = queue.Queue()
        with self._sse_lock:
            self._sse_queues.append(q)

        try:
            while True:
                try:
                    data = q.get(timeout=20)
                    yield f"data: {data}\n\n"
                except queue.Empty:
                    yield ": heartbeat\n\n"
        finally:
            with self._sse_lock:
                self._sse_queues.remove(q)

    async def start(self) -> None:
        """Start the Flask server."""
        host = getattr(self.config, "host", "127.0.0.1")
        port = getattr(self.config, "port", 8080)

        self._server = make_server(host, port, self.app, threaded=True)
        self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._server_thread.start()

        self._running = True
        logger.info(f"Web channel (Flask) running on http://{host}:{port}")

    async def stop(self) -> None:
        """Stop the Flask server."""
        if self._server:
            self._server.shutdown()
        if self._server_thread:
            self._server_thread.join(timeout=2.0)
        self._running = False
        logger.info("Web channel stopped")

    def _notify_sse(self, chat_id: str, role: str, content: str) -> None:
        """Notify all SSE listeners of a new message."""
        data = json.dumps({
            "chat_id": chat_id,
            "role": role,
            "content": content
        })
        with self._sse_lock:
            for q in self._sse_queues:
                q.put(data)

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message to the web client (saves to history and notifies via SSE)."""
        chat_id = msg.chat_id
        content = msg.content

        self._notify_sse(chat_id, "assistant", content)
