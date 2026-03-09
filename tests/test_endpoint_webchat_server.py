import threading
import time
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
  <title>endpoint direct test</title>
  <style>
    :root { --panel: #7f81861e; --line: #8f90a054; --accent: #6f5ff07f; --accent-dim: #4f46a07f; --danger: #9f12397f; }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: ui-rounded, sans-serif; min-height: 100vh; }
    .shell { display: grid; grid-template-columns: 340px 1fr; height: 100vh; background: var(--panel); }
    .panel { overflow: hidden; display: flex; flex-direction: column; height: 100%; }
    .chats { border-right: 1px solid var(--line); }
    .panel h2 { margin: 0; padding: 16px; font-size: 14px; border-bottom: 1px solid var(--line); }
    #chat-list { list-style: none; overflow-y: auto; flex: 1; padding: 0; }
    #chat-list li { padding: 12px 16px; border-bottom: 1px solid #7f7f7f5f; cursor: pointer; }
    #chat-list li.active { border-left: 3px solid var(--accent); }
    form { display: flex; gap: 8px; padding: 12px; border-top: 1px solid var(--line); }
    textarea { flex: 1; border-radius: 6px; border: 1px solid var(--line); padding: 8px; }
    button { cursor: pointer; background: var(--accent); border: none; border-radius: 6px; padding: 8px 16px; }
    #messages { padding: 20px; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; flex: 1; }
    .msg { max-width: 80%; border-radius: 12px; padding: 10px; border: 1px solid var(--line); }
    .user { align-self: flex-end; background: #94a1b933; }
    .assistant { align-self: flex-start; background: #7f7f7f1f; }
  </style>
</head>
<body>
  <main class="shell">
    <section class="panel chats">
      <h2>Direct Endpoint Test</h2>
      <ul id="chat-list"></ul>
      <form id="new-chat-form"><input id="chat-title" placeholder="Session Name" required /><button type="submit">Start</button></form>
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
    const endpointUrl = "/v1/responses"; // Direct URL

    const addMsg = (role, content) => {
      const el = document.createElement('div');
      el.className = `msg ${role}`;
      el.textContent = content;
      document.getElementById('messages').appendChild(el);
    };

    document.getElementById('new-chat-form').onsubmit = (e) => {
      e.preventDefault();
      activeId = Date.now().toString(16);
      const li = document.createElement('li');
      li.textContent = document.getElementById('chat-title').value;
      li.className = 'active';
      document.getElementById('chat-list').appendChild(li);
      document.getElementById('messages').innerHTML = '';
      addMsg('system', 'Connected directly to ' + endpointUrl);
    };

    document.getElementById('send-form').onsubmit = async (e) => {
      e.preventDefault();
      const content = document.getElementById('prompt').value;
      addMsg('user', content);
      document.getElementById('prompt').value = '';

      try {
        const r = await fetch(endpointUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            messages: [{role: 'user', content}],
            user: "direct-test-user"
          })
        });
        const data = await r.json();
        addMsg('assistant', data.choices[0].message.content);
      } catch (err) {
        addMsg('system', 'Connection failed: ' + err.message);
      }
    };
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
