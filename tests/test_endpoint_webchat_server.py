import threading
import time
import os
from typing import Any
from flask import Flask, render_template_string, request, jsonify
import requests
from werkzeug.serving import make_server
from loguru import logger

HTML_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="color-scheme" content="light dark">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no" />
  <title>endpoint webchat test</title>
  <style>
    :root { --panel: #7f81861e; --line: #8f90a054; --accent: #6f5ff07f; --accent-dim: #4f46a07f; --danger: #9f12397f; }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: ui-rounded, sans-serif; min-height: 100vh; }
    .shell { display: grid; grid-template-columns: 340px 1fr; height: 100vh; background: var(--panel); }
    .panel { overflow: hidden; display: flex; flex-direction: column; height: 100%; }
    .chats { border-right: 1px solid var(--line); }
    .panel h2 { margin: 0; padding: 16px; font-size: 14px; border-bottom: 1px solid var(--line); }
    #chat-list { list-style: none; overflow-y: auto; flex: 1; padding: 0; margin: 0; }
    #chat-list li { padding: 12px 16px; border-bottom: 1px solid #7f7f7f5f; cursor: pointer; transition: background .2s; }
    #chat-list li:hover { background: #7f7f7f1a; }
    #chat-list li.active { border-left: 3px solid var(--accent); background: #7f7f7f2a; }
    form { display: flex; gap: 8px; padding: 12px; border-top: 1px solid var(--line); }
    textarea { flex: 1; border-radius: 6px; border: 1px solid var(--line); padding: 8px; font: inherit; }
    button { cursor: pointer; background: var(--accent); border: none; border-radius: 6px; padding: 8px 16px; color: white; font-weight: 600; }
    button:hover { background: var(--accent-dim); }
    #messages { padding: 20px; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; flex: 1; }
    .msg { max-width: 80%; border-radius: 12px; padding: 10px 14px; border: 1px solid var(--line); line-height: 1.4; }
    .user { align-self: flex-end; background: #94a1b933; border-bottom-right-radius: 4px; }
    .assistant { align-self: flex-start; background: #7f7f7f1f; border-bottom-left-radius: 4px; }
    .system { align-self: center; font-size: 12px; opacity: 0.7; font-style: italic; border: none; background: none; }
    .error { color: #f87171; border-color: #f87171; }
  </style>
</head>
<body>
  <main class="shell">
    <section class="panel chats">
      <h2>Chats</h2>
      <ul id="chat-list"></ul>
      <form id="new-chat-form"><input id="chat-title" placeholder="Session Name" required style="flex:1; padding:8px; border-radius:6px; border:1px solid var(--line);" /><button type="submit">New</button></form>
    </section>
    <section class="panel chat">
      <div id="messages"></div>
      <form id="send-form">
        <textarea id="prompt" placeholder="Type a message" required></textarea>
        <button type="submit" id="send-btn">Send</button>
      </form>
    </section>
  </main>

  <script>
    let activeId = null;
    let sessions = JSON.parse(localStorage.getItem('endpoint_sessions') || '[]');
    const endpointUrl = "/v1/responses";

    const addMsgToUI = (role, content, isError = false) => {
      const el = document.createElement('div');
      el.className = `msg ${role} ${isError ? 'error' : ''}`;
      el.textContent = content;
      document.getElementById('messages').appendChild(el);
      document.getElementById('messages').scrollTop = document.getElementById('messages').scrollHeight;
    };

    const saveHistory = (id, history) => {
      localStorage.setItem(`history_${id}`, JSON.stringify(history));
    };

    const getHistory = (id) => {
      return JSON.parse(localStorage.getItem(`history_${id}`) || '[]');
    };

    const selectSession = (id) => {
      activeId = id;
      renderSessions();
      const messagesContainer = document.getElementById('messages');
      messagesContainer.innerHTML = '';

      const history = getHistory(id);
      if (history.length === 0) {
        addMsgToUI('system', 'New session started.');
      } else {
        history.forEach(m => addMsgToUI(m.role, m.content));
      }
    };

    const renderSessions = () => {
      const list = document.getElementById('chat-list');
      list.innerHTML = '';
      sessions.forEach(s => {
        const li = document.createElement('li');
        li.textContent = s.title;
        if (s.id === activeId) li.className = 'active';
        li.onclick = () => selectSession(s.id);
        list.appendChild(li);
      });
      localStorage.setItem('endpoint_sessions', JSON.stringify(sessions));
    };

    document.getElementById('new-chat-form').onsubmit = (e) => {
      e.preventDefault();
      const title = document.getElementById('chat-title').value;
      const id = 'sess_' + Date.now().toString(16);
      sessions.unshift({ id, title });
      document.getElementById('chat-title').value = '';
      selectSession(id);
    };

    document.getElementById('send-form').onsubmit = async (e) => {
      e.preventDefault();
      if (!activeId) {
        alert("Please select or create a session first.");
        return;
      }

      const promptEl = document.getElementById('prompt');
      const content = promptEl.value.trim();
      if (!content) return;

      const sendBtn = document.getElementById('send-btn');
      promptEl.value = '';
      promptEl.disabled = true;
      sendBtn.disabled = true;

      const history = getHistory(activeId);

      // Find the last assistant response to get the previous_response_id
      const lastAssistantMsg = [...history].reverse().find(m => m.role === 'assistant' && m.id);
      const prevId = lastAssistantMsg ? lastAssistantMsg.id : undefined;

      addMsgToUI('user', content);
      history.push({ role: 'user', content });
      saveHistory(activeId, history);

      try {
        const r = await fetch(endpointUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer """ + os.getenv('NANOBOT_API_KEY', '') + """' },
          body: JSON.stringify({
            input: content,
            user: "web-test-user",
            previous_response_id: prevId
          })
        });
        const data = await r.json();

        if (!r.ok) throw new Error(data.error || 'Server error');

        let reply = '';
        if (data.output && Array.isArray(data.output)) {
          const msgItem = data.output.find(item => item.type === 'message');
          if (msgItem && msgItem.content && Array.isArray(msgItem.content)) {
            const textPart = msgItem.content.find(c => c.type === 'text');
            if (textPart) reply = textPart.text;
          }
        }

        if (reply) {
          addMsgToUI('assistant', reply);
          history.push({ role: 'assistant', content: reply, id: data.id });
          saveHistory(activeId, history);
        } else {
          addMsgToUI('system', 'No output received.', true);
        }

      } catch (err) {
        addMsgToUI('system', 'Error: ' + err.message, true);
      } finally {
        promptEl.disabled = false;
        sendBtn.disabled = false;
        promptEl.focus();
      }
    };

    // Initial load
    if (sessions.length > 0) {
      selectSession(sessions[0].id);
    } else {
      renderSessions();
    }
  </script>
</body>
</html>
"""

class TestEndpointWebChat:
    def __init__(self, port=8081):
        self.app = Flask(__name__)
        self.port = port
        self._setup_routes()
        self.config = {}

    def _setup_routes(self) -> None:
        """Define routes for the test interface."""

        @self.app.route('/')
        def index():
            return render_template_string(HTML_PAGE)

        @self.app.route('/v1/responses', methods=['POST'])
        def proxy():
            """Proxy the request to the actual EndpointChannel."""
            endpoint_url = getattr(self.config, "endpoint_url", "http://localhost:8080/v1/responses")
            try:
                response = requests.post(
                    endpoint_url,
                    headers={ 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + os.getenv('NANOBOT_API_KEY', '') },
                    json=request.json,
                    timeout=getattr(self.config, "request_timeout", 65.0)
                )
                return jsonify(response.json()), response.status_code
            except Exception as e:
                logger.error(f"Responses proxy error: {e}")
                return jsonify({"error": str(e)}), 500

    def start(self):
        self._server = make_server("0.0.0.0", self.port, self.app)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        logger.info(f"Test UI running on http://0.0.0.0:{self.port}")

if __name__ == "__main__":
    ui = TestEndpointWebChat()
    ui.start()
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt: pass
