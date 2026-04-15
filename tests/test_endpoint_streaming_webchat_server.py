import threading
import time
import os
from typing import Any, Iterable
from flask import Flask, render_template_string, request, Response, jsonify
import requests
from werkzeug.serving import make_server
from loguru import logger

HTML_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="color-scheme" content="light dark">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no" />
  <title>endpoint webchat streaming test</title>
  <style>
    :root { --panel: #7f81861e; --line: #8f90a054; --accent: #0f766e; --accent-dim: #115e59; --danger: #b91c1c; }
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
        <input id="image-file" type="file" accept="image/*" />
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
      return el;
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

    const readFileAsDataUrl = (file) => new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(reader.error || new Error('Failed to read file'));
      reader.readAsDataURL(file);
    });

    const parseSse = (chunk, onEvent) => {
      const events = chunk.split('\\n\\n');
      for (const evt of events) {
        if (!evt.trim()) continue;
        let eventName = '';
        let dataLines = [];
        evt.split('\\n').forEach(line => {
          if (line.startsWith('event:')) eventName = line.slice(6).trim();
          if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
        });
        const data = dataLines.join('\\n');
        if (!data) continue;
        onEvent(eventName, data);
      }
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
      const imageInput = document.getElementById('image-file');
      const imageFile = imageInput.files && imageInput.files[0] ? imageInput.files[0] : null;
      const content = promptEl.value.trim();
      if (!content && !imageFile) return;

      const sendBtn = document.getElementById('send-btn');
      promptEl.value = '';
      imageInput.value = '';
      promptEl.disabled = true;
      sendBtn.disabled = true;

      const history = getHistory(activeId);
      const lastAssistantMsg = [...history].reverse().find(m => m.role === 'assistant' && m.id);
      const prevId = lastAssistantMsg ? lastAssistantMsg.id : undefined;

      const userLabel = imageFile ? (content ? content + " [image]" : "[image]") : content;
      addMsgToUI('user', userLabel);
      history.push({ role: 'user', content: userLabel });
      saveHistory(activeId, history);

      let streamEl = null;
      let streamText = '';

      try {
        const imageDataUrl = imageFile ? await readFileAsDataUrl(imageFile) : null;
        const contentParts = [];
        if (content) contentParts.push({ type: "text", text: content });
        if (imageDataUrl) contentParts.push({ type: "image_url", image_url: { url: imageDataUrl } });
        const inputPayload = [
          { type: "message", role: "user", content: contentParts }
        ];
        const r = await fetch(endpointUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer """ + os.getenv('NANOBOT_API_KEY', '') + """' },
          body: JSON.stringify({
            input: inputPayload,
            user: "web-test-user",
            previous_response_id: prevId,
            stream: true
          })
        });

        const contentType = r.headers.get('content-type') || '';
        if (!r.ok || !contentType.includes('text/event-stream')) {
          const data = await r.json();
          throw new Error(data.error || 'Server error');
        }

        streamEl = addMsgToUI('assistant', '');

        const reader = r.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let finalResponseId = null;

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split('\\n\\n');
          buffer = parts.pop();
          parts.forEach(part => {
            parseSse(part, (event, data) => {
              if (data === '[DONE]') return;
              let payload = null;
              try { payload = JSON.parse(data); } catch (_) { payload = null; }

              if (event === 'response.output_text.delta' && payload && payload.delta) {
                streamText += payload.delta;
                streamEl.textContent = streamText;
              } else if (event === 'response.completed' && payload) {
                finalResponseId = payload.id || finalResponseId;
                if (payload.output && Array.isArray(payload.output)) {
                  const msgItem = payload.output.find(item => item.type === 'message');
                  if (msgItem && msgItem.content && Array.isArray(msgItem.content)) {
                    const textPart = msgItem.content.find(c => c.type === 'text');
                    if (textPart) streamText = textPart.text;
                  }
                }
                streamEl.textContent = streamText;
              } else if (event === 'response.error') {
                throw new Error((payload && payload.error) || 'Server error');
              }
            });
          });
        }

        if (streamText) {
          history.push({ role: 'assistant', content: streamText, id: finalResponseId });
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

    if (sessions.length > 0) {
      selectSession(sessions[0].id);
    } else {
      renderSessions();
    }
  </script>
</body>
</html>
"""

class TestEndpointStreamingWebChat:
    def __init__(self, port=8082):
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
        def proxy_stream():
            """Proxy the streaming request to the actual EndpointChannel."""
            endpoint_url = getattr(self.config, "endpoint_url", "http://localhost:8080/v1/responses")
            payload = dict(request.json or {})
            payload["stream"] = True
            try:
                upstream = requests.post(
                    endpoint_url,
                    headers={ 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + os.getenv('NANOBOT_API_KEY', '') },
                    json=payload,
                    timeout=getattr(self.config, "request_timeout", 65.0),
                    stream=True
                )

                def generate():
                    for chunk in upstream.iter_content(chunk_size=8192):
                        if chunk:
                            yield chunk

                headers = {
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no"
                }
                return Response(generate(), status=upstream.status_code, mimetype="text/event-stream", headers=headers)
            except Exception as e:
                logger.error(f"Responses streaming proxy error: {e}")
                return jsonify({"error": str(e)}), 500

    def start(self):
        self._server = make_server("0.0.0.0", self.port, self.app)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        logger.info(f"Streaming test UI running on http://0.0.0.0:{self.port}")

if __name__ == "__main__":
    ui = TestEndpointStreamingWebChat()
    ui.start()
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt: pass
