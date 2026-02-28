/* ── Session storage ──────────────────────────────────────────────────── */

function getSessions() {
  try { return JSON.parse(localStorage.getItem('nanobot_sessions') || '[]'); }
  catch { return []; }
}

function saveSessions(list) {
  localStorage.setItem('nanobot_sessions', JSON.stringify(list));
}

function getHistory(id) {
  try { return JSON.parse(localStorage.getItem('nanobot_history_' + id) || '[]'); }
  catch { return []; }
}

function saveHistory(id, history) {
  localStorage.setItem('nanobot_history_' + id, JSON.stringify(history));
}

function createSession(name = 'New chat') {
  const id = crypto.randomUUID();
  const sessions = getSessions();
  sessions.unshift({ id, name, created: Date.now(), updated: Date.now() });
  saveSessions(sessions);
  return id;
}

function renameSession(id, name) {
  const sessions = getSessions();
  const s = sessions.find(s => s.id === id);
  if (s) { s.name = name; s.updated = Date.now(); saveSessions(sessions); }
}

function touchSession(id) {
  const sessions = getSessions();
  const s = sessions.find(s => s.id === id);
  if (s) { s.updated = Date.now(); saveSessions(sessions); }
}

/* ── Session init ─────────────────────────────────────────────────────── */

let sessionId;
{
  const stored   = localStorage.getItem('nanobot_session');
  const sessions = getSessions();
  if (stored && sessions.find(s => s.id === stored)) {
    sessionId = stored;
  } else {
    sessionId = createSession();
    localStorage.setItem('nanobot_session', sessionId);
  }
}

/* ── State ────────────────────────────────────────────────────────────── */

let isStreaming = false;

/* ── DOM refs ─────────────────────────────────────────────────────────── */

const messagesEl    = document.getElementById('messages');
const form          = document.getElementById('chat-form');
const input         = document.getElementById('input');
const btnSend       = document.getElementById('btn-send');
const btnNew        = document.getElementById('btn-new');
const sessionListEl = document.getElementById('session-list');

/* ── marked config ────────────────────────────────────────────────────── */

marked.setOptions({ breaks: true, gfm: true });

/* ── Helpers ──────────────────────────────────────────────────────────── */

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function setStreaming(active) {
  isStreaming = active;
  btnSend.disabled = active;
  input.disabled   = active;
}

function resizeInput() {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 200) + 'px';
}

function clearEmptyState() {
  const empty = document.getElementById('empty-state');
  if (empty) empty.remove();
}

function escapeHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/* ── Sidebar ──────────────────────────────────────────────────────────── */

function renderSidebar() {
  const sessions = getSessions();
  sessionListEl.innerHTML = '';
  for (const s of sessions) {
    const item = document.createElement('button');
    item.className = 'session-item' + (s.id === sessionId ? ' active' : '');
    item.textContent = s.name;
    item.title = s.name;
    item.addEventListener('click', () => switchSession(s.id));
    sessionListEl.appendChild(item);
  }
}

function switchSession(id) {
  if (id === sessionId || isStreaming) return;
  sessionId = id;
  localStorage.setItem('nanobot_session', id);
  renderSidebar();
  replayHistory(id);
}

/* ── Message builders ─────────────────────────────────────────────────── */

function appendUserMessage(text) {
  clearEmptyState();
  const div = document.createElement('div');
  div.className = 'message user';
  div.innerHTML = `
    <div class="avatar">👤</div>
    <div class="bubble">${escapeHtml(text)}</div>
  `;
  messagesEl.appendChild(div);
  scrollToBottom();
  return div;
}

function appendBotSkeleton() {
  clearEmptyState();
  const wrapper = document.createElement('div');
  wrapper.className = 'message bot';
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  wrapper.innerHTML = `<div class="avatar">🐱</div>`;
  wrapper.appendChild(bubble);
  messagesEl.appendChild(wrapper);
  scrollToBottom();
  return { wrapper, bubble };
}

/* ── Hint chips ───────────────────────────────────────────────────────── */

function setupHintChip(chip, toolName, fullText) {
  chip.className = 'hint';
  chip.textContent = '⚙ ' + toolName;
  chip.title = 'Click to expand';
  chip.addEventListener('click', () => {
    if (chip.classList.contains('expanded')) {
      chip.classList.remove('expanded');
      chip.textContent = '⚙ ' + toolName;
      chip.title = 'Click to expand';
    } else {
      chip.classList.add('expanded');
      chip.textContent = fullText;
      chip.title = 'Click to collapse';
    }
  });
}

function appendHint(text, wrapper) {
  const bubble = wrapper.querySelector('.bubble');
  let hintsEl = bubble.querySelector('.hints');
  if (!hintsEl) {
    hintsEl = document.createElement('div');
    hintsEl.className = 'hints';
    bubble.insertBefore(hintsEl, bubble.firstChild);
  }
  const chip = document.createElement('span');
  const toolName = text.includes('(') ? text.slice(0, text.indexOf('(')).trim() : text;
  setupHintChip(chip, toolName, text);
  hintsEl.appendChild(chip);
  scrollToBottom();
  return { toolName, fullText: text };
}

/* ── History replay ───────────────────────────────────────────────────── */

function replayHistory(id) {
  messagesEl.innerHTML = '';
  const history = getHistory(id);

  if (history.length === 0) {
    messagesEl.innerHTML = `
      <div id="empty-state">
        <div class="big-logo">🐱</div>
        <p>How can I help you today?</p>
      </div>
    `;
    return;
  }

  for (const msg of history) {
    if (msg.role === 'user') {
      appendUserMessage(msg.content);
    } else {
      const { bubble } = appendBotSkeleton();
      if (msg.hints && msg.hints.length > 0) {
        const hintsEl = document.createElement('div');
        hintsEl.className = 'hints';
        for (const h of msg.hints) {
          const chip = document.createElement('span');
          setupHintChip(chip, h.toolName, h.fullText);
          hintsEl.appendChild(chip);
        }
        bubble.appendChild(hintsEl);
      }
      const rendered = document.createElement('div');
      rendered.className = 'rendered-content';
      rendered.innerHTML = marked.parse(msg.content);
      bubble.appendChild(rendered);
    }
  }
  scrollToBottom();
}

/* ── SSE stream parser ────────────────────────────────────────────────── */

function parseSSEChunk(buffer) {
  const events = [];
  const blocks = buffer.split('\n\n');
  const remaining = blocks.pop();
  for (const block of blocks) {
    if (!block.trim()) continue;
    let type = 'message';
    let dataStr = '';
    for (const line of block.split('\n')) {
      if (line.startsWith('event: '))      type    = line.slice(7).trim();
      else if (line.startsWith('data: '))  dataStr = line.slice(6).trim();
    }
    try {
      events.push({ type, data: JSON.parse(dataStr) });
    } catch { }
  }
  return { events, remaining };
}

/* ── Core send ────────────────────────────────────────────────────────── */

async function sendMessage(text) {
  if (!text.trim() || isStreaming) return;

  setStreaming(true);
  appendUserMessage(text);
  const { wrapper, bubble } = appendBotSkeleton();

  const streamEl = document.createElement('div');
  streamEl.className = 'streaming-content';
  bubble.appendChild(streamEl);

  let tokenBuffer = '';
  const collectedHints = [];

  // Name the session after the first message
  const history = getHistory(sessionId);
  if (history.length === 0) {
    renameSession(sessionId, text.length > 35 ? text.slice(0, 32) + '…' : text);
    renderSidebar();
  }

  // Persist user turn immediately
  history.push({ role: 'user', content: text });
  saveHistory(sessionId, history);

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, session_id: sessionId }),
    });

    if (!res.ok) throw new Error(`Server returned ${res.status}`);

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let   sseBuffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      sseBuffer += decoder.decode(value, { stream: true });
      const { events, remaining } = parseSSEChunk(sseBuffer);
      sseBuffer = remaining;

      for (const { type, data } of events) {
        if (type === 'token') {
          tokenBuffer += data.text;
          streamEl.textContent = tokenBuffer;
          scrollToBottom();

        } else if (type === 'progress') {
          const hint = appendHint(data.text, wrapper);
          collectedHints.push(hint);

        } else if (type === 'done') {
          const finalText = data.text || tokenBuffer;
          streamEl.remove();
          const rendered = document.createElement('div');
          rendered.className = 'rendered-content';
          rendered.innerHTML = marked.parse(finalText);
          bubble.appendChild(rendered);
          scrollToBottom();

          // Persist bot turn
          const h = getHistory(sessionId);
          h.push({ role: 'bot', content: finalText, hints: collectedHints });
          saveHistory(sessionId, h);
          touchSession(sessionId);
          renderSidebar();
          return;

        } else if (type === 'error') {
          streamEl.remove();
          const err = document.createElement('div');
          err.className = 'error-bubble';
          err.textContent = '⚠ ' + (data.message || 'Unknown error');
          bubble.appendChild(err);
          scrollToBottom();
          return;
        }
      }
    }

    // Stream ended without a 'done' event — render whatever we have
    if (tokenBuffer) {
      streamEl.remove();
      const rendered = document.createElement('div');
      rendered.className = 'rendered-content';
      rendered.innerHTML = marked.parse(tokenBuffer);
      bubble.appendChild(rendered);
      scrollToBottom();
    }

  } catch (err) {
    streamEl.remove();
    const errEl = document.createElement('div');
    errEl.className = 'error-bubble';
    errEl.textContent = '⚠ ' + err.message;
    bubble.appendChild(errEl);
    scrollToBottom();
  } finally {
    setStreaming(false);
    input.focus();
  }
}

/* ── New conversation ─────────────────────────────────────────────────── */

function newConversation() {
  if (isStreaming) return;
  sessionId = createSession();
  localStorage.setItem('nanobot_session', sessionId);
  renderSidebar();
  messagesEl.innerHTML = `
    <div id="empty-state">
      <div class="big-logo">🐱</div>
      <p>New conversation started.</p>
    </div>
  `;
  input.focus();
}

/* ── Event listeners ──────────────────────────────────────────────────── */

form.addEventListener('submit', (e) => {
  e.preventDefault();
  const text = input.value;
  input.value = '';
  resizeInput();
  sendMessage(text);
});

input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    form.dispatchEvent(new Event('submit'));
  }
});

input.addEventListener('input', resizeInput);

btnNew.addEventListener('click', newConversation);

/* ── Init ─────────────────────────────────────────────────────────────── */

renderSidebar();
replayHistory(sessionId);
input.focus();
