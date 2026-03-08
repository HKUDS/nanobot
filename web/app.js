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

function pinSession(id) {
  const sessions = getSessions();
  const s = sessions.find(s => s.id === id);
  if (s) { s.pinned = !s.pinned; saveSessions(sessions); renderSidebar(); }
}

function deleteSession(id) {
  let sessions = getSessions().filter(s => s.id !== id);
  saveSessions(sessions);
  localStorage.removeItem('nanobot_history_' + id);
  if (id === sessionId) {
    sessionId = sessions.length > 0 ? sessions[0].id : createSession();
    localStorage.setItem('nanobot_session', sessionId);
    replayHistory(sessionId);
  }
  renderSidebar();
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
let abortController = null;

/* ── DOM refs ─────────────────────────────────────────────────────────── */

const messagesEl    = document.getElementById('messages');
const form          = document.getElementById('chat-form');
const input         = document.getElementById('input');
const btnSend       = document.getElementById('btn-send');
const btnNew        = document.getElementById('btn-new');
const btnMenu       = document.getElementById('btn-menu');
const sidebar       = document.getElementById('sidebar');
const sidebarOverlay = document.getElementById('sidebar-overlay');
const sessionListEl = document.getElementById('session-list');

/* ── marked config ────────────────────────────────────────────────────── */

marked.setOptions({ breaks: true, gfm: true });

/* ── Sidebar toggle (mobile) ──────────────────────────────────────────── */

function openSidebar() {
  sidebar.classList.add('open');
  sidebarOverlay.classList.add('visible');
}

function closeSidebar() {
  sidebar.classList.remove('open');
  sidebarOverlay.classList.remove('visible');
}

btnMenu.addEventListener('click', () =>
  sidebar.classList.contains('open') ? closeSidebar() : openSidebar()
);
sidebarOverlay.addEventListener('click', closeSidebar);

/* ── Helpers ──────────────────────────────────────────────────────────── */

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function setStreaming(active) {
  isStreaming = active;
  input.disabled = active;
  if (active) {
    btnSend.classList.add('stopping');
    btnSend.setAttribute('aria-label', 'Stop');
  } else {
    btnSend.classList.remove('stopping');
    btnSend.setAttribute('aria-label', 'Send');
    abortController = null;
  }
}

function stopGeneration() {
  if (abortController) abortController.abort();
  fetch('/api/stop', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId }),
  }).catch(() => {});
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
  // Pinned sessions first, then by last updated
  sessions.sort((a, b) => {
    if (a.pinned && !b.pinned) return -1;
    if (!a.pinned && b.pinned) return 1;
    return (b.updated || 0) - (a.updated || 0);
  });
  sessionListEl.innerHTML = '';
  for (const s of sessions) {
    const item = document.createElement('div');
    item.className = 'session-item' + (s.id === sessionId ? ' active' : '') + (s.pinned ? ' pinned' : '');

    const nameBtn = document.createElement('button');
    nameBtn.className = 'session-name';
    nameBtn.textContent = (s.pinned ? '📌 ' : '') + s.name;
    nameBtn.title = s.name;
    nameBtn.addEventListener('click', () => switchSession(s.id));

    const menuBtn = document.createElement('button');
    menuBtn.className = 'session-menu-btn';
    menuBtn.setAttribute('aria-label', 'Session options');
    menuBtn.textContent = '⋮';

    const dropdown = document.createElement('div');
    dropdown.className = 'session-dropdown hidden';

    const pinItem = document.createElement('button');
    pinItem.className = 'session-dropdown-item';
    pinItem.textContent = s.pinned ? '📌 Unpin' : '📌 Pin';

    const deleteItem = document.createElement('button');
    deleteItem.className = 'session-dropdown-item danger';
    deleteItem.textContent = '🗑 Delete';

    dropdown.appendChild(pinItem);
    dropdown.appendChild(deleteItem);

    menuBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      document.querySelectorAll('.session-dropdown:not(.hidden)').forEach(d => {
        if (d !== dropdown) d.classList.add('hidden');
      });
      dropdown.classList.toggle('hidden');
    });

    pinItem.addEventListener('click', (e) => {
      e.stopPropagation();
      pinSession(s.id);
      dropdown.classList.add('hidden');
    });

    deleteItem.addEventListener('click', (e) => {
      e.stopPropagation();
      deleteSession(s.id);
      dropdown.classList.add('hidden');
    });

    item.appendChild(nameBtn);
    item.appendChild(menuBtn);
    item.appendChild(dropdown);
    sessionListEl.appendChild(item);
  }
}

function switchSession(id) {
  if (id === sessionId || isStreaming) return;
  sessionId = id;
  localStorage.setItem('nanobot_session', id);
  closeSidebar();
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

/* ── Message actions (⋮ dropdown) ─────────────────────────────────────── */

function addMessageActions(el, index) {
  const btn = document.createElement('button');
  btn.className = 'msg-actions-btn';
  btn.setAttribute('aria-label', 'Message options');
  btn.textContent = '⋮';

  const dropdown = document.createElement('div');
  dropdown.className = 'msg-dropdown hidden';

  const pinItem = document.createElement('button');
  pinItem.className = 'msg-dropdown-item';

  const deleteItem = document.createElement('button');
  deleteItem.className = 'msg-dropdown-item danger';
  deleteItem.innerHTML = '<span>🗑</span> Delete';

  dropdown.appendChild(pinItem);
  dropdown.appendChild(deleteItem);
  el.appendChild(btn);
  el.appendChild(dropdown);

  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    document.querySelectorAll('.msg-dropdown:not(.hidden)').forEach(d => {
      if (d !== dropdown) d.classList.add('hidden');
    });
    const opening = dropdown.classList.contains('hidden');
    dropdown.classList.toggle('hidden');
    if (opening) {
      const h = getHistory(sessionId);
      pinItem.innerHTML = h[index]?.pinned
        ? '<span>📌</span> Unpin'
        : '<span>📌</span> Pin';
    }
  });

  pinItem.addEventListener('click', (e) => {
    e.stopPropagation();
    const h = getHistory(sessionId);
    if (h[index]) {
      h[index].pinned = !h[index].pinned;
      saveHistory(sessionId, h);
      el.classList.toggle('pinned', !!h[index].pinned);
    }
    dropdown.classList.add('hidden');
  });

  deleteItem.addEventListener('click', (e) => {
    e.stopPropagation();
    if (isStreaming) return;
    const h = getHistory(sessionId);
    h.splice(index, 1);
    saveHistory(sessionId, h);
    dropdown.classList.add('hidden');
    replayHistory(sessionId);
  });
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

  for (let i = 0; i < history.length; i++) {
    const msg = history[i];
    if (msg.role === 'user') {
      const div = appendUserMessage(msg.content);
      if (msg.pinned) div.classList.add('pinned');
      addMessageActions(div, i);
    } else {
      const { wrapper, bubble } = appendBotSkeleton();
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
      if (msg.pinned) wrapper.classList.add('pinned');
      addMessageActions(wrapper, i);
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

  // Persist user turn first so we know the index before rendering
  const history = getHistory(sessionId);
  if (history.length === 0) {
    renameSession(sessionId, text.length > 35 ? text.slice(0, 32) + '…' : text);
    renderSidebar();
  }
  history.push({ role: 'user', content: text });
  saveHistory(sessionId, history);
  const userMsgIdx = history.length - 1;

  setStreaming(true);
  const userDiv = appendUserMessage(text);
  addMessageActions(userDiv, userMsgIdx);
  const { wrapper, bubble } = appendBotSkeleton();

  // Active streaming section — always appended at end of bubble
  let currentStreamEl = document.createElement('div');
  currentStreamEl.className = 'streaming-content';
  bubble.appendChild(currentStreamEl);

  let tokenBuffer = '';
  let lastToolBlock = null;
  const collectedHints = [];

  // Freeze the current streaming section into a rendered-content div,
  // then add a fresh streaming section at the end of bubble.
  function freezeCurrentSection() {
    if (tokenBuffer.trim()) {
      const rendered = document.createElement('div');
      rendered.className = 'rendered-content';
      rendered.innerHTML = marked.parse(tokenBuffer);
      if (currentStreamEl.parentNode === bubble) {
        bubble.replaceChild(rendered, currentStreamEl);
      } else {
        bubble.appendChild(rendered);
      }
    } else {
      currentStreamEl.remove();
    }
    tokenBuffer = '';
    currentStreamEl = document.createElement('div');
    currentStreamEl.className = 'streaming-content';
    bubble.appendChild(currentStreamEl);
  }

  try {
    abortController = new AbortController();
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, session_id: sessionId }),
      signal: abortController.signal,
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
          currentStreamEl.textContent = tokenBuffer;
          scrollToBottom();

        } else if (type === 'tool_call') {
          // Freeze current text, insert inline tool block before new stream section
          freezeCurrentSection();

          const block = document.createElement('div');
          block.className = 'tool-block tool-pending';

          if (data.tool === 'write_file' && data.args && data.args.path) {
            // Special rendering: filename in header, file content in a code body
            const ext = data.args.path.split('.').pop() || '';
            block.innerHTML = `
              <div class="tool-header">
                <span class="tool-spinner">⟳</span>
                <span class="tool-name tool-filepath">✎ ${escapeHtml(data.args.path)}</span>
              </div>
              <pre class="tool-file-content"><code class="lang-${escapeHtml(ext)}">${escapeHtml(data.args.content || '')}</code></pre>
              <div class="tool-output"></div>
            `;
          } else {
            block.innerHTML = `
              <div class="tool-header">
                <span class="tool-spinner">⟳</span>
                <span class="tool-name">${escapeHtml(data.call_str || data.tool)}</span>
              </div>
              <div class="tool-output"></div>
            `;
          }
          bubble.insertBefore(block, currentStreamEl);
          lastToolBlock = block;
          collectedHints.push({ toolName: data.tool, fullText: data.call_str || data.tool });
          scrollToBottom();

        } else if (type === 'tool_result') {
          if (lastToolBlock) {
            lastToolBlock.classList.remove('tool-pending');
            const spinner = lastToolBlock.querySelector('.tool-spinner');
            if (spinner) spinner.textContent = '$';
            const outputEl = lastToolBlock.querySelector('.tool-output');
            if (outputEl && data.output) {
              outputEl.textContent = data.output;
              if (data.truncated) {
                const notice = document.createElement('div');
                notice.className = 'tool-truncated';
                notice.textContent = '… output truncated';
                lastToolBlock.appendChild(notice);
              }
            }
          }
          scrollToBottom();

        } else if (type === 'progress') {
          // Fallback: old-style progress chips (channels without tool_call support)
          const hint = appendHint(data.text, wrapper);
          collectedHints.push(hint);

        } else if (type === 'done') {
          const finalText = data.text || tokenBuffer;
          if (finalText.trim()) {
            const rendered = document.createElement('div');
            rendered.className = 'rendered-content';
            rendered.innerHTML = marked.parse(finalText);
            if (currentStreamEl.parentNode === bubble) {
              bubble.replaceChild(rendered, currentStreamEl);
            } else {
              bubble.appendChild(rendered);
            }
          } else {
            currentStreamEl.remove();
          }
          scrollToBottom();

          // Persist bot turn
          const h = getHistory(sessionId);
          h.push({ role: 'bot', content: finalText, hints: collectedHints });
          saveHistory(sessionId, h);
          addMessageActions(wrapper, h.length - 1);
          touchSession(sessionId);
          renderSidebar();
          return;

        } else if (type === 'error') {
          currentStreamEl.remove();
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
      const rendered = document.createElement('div');
      rendered.className = 'rendered-content';
      rendered.innerHTML = marked.parse(tokenBuffer);
      if (currentStreamEl.parentNode === bubble) {
        bubble.replaceChild(rendered, currentStreamEl);
      } else {
        bubble.appendChild(rendered);
      }
      scrollToBottom();
    }

  } catch (err) {
    currentStreamEl.remove();
    if (err.name === 'AbortError') {
      // User stopped — render whatever was streamed so far
      if (tokenBuffer.trim()) {
        const rendered = document.createElement('div');
        rendered.className = 'rendered-content';
        rendered.innerHTML = marked.parse(tokenBuffer);
        bubble.appendChild(rendered);
      }
    } else {
      const errEl = document.createElement('div');
      errEl.className = 'error-bubble';
      errEl.textContent = '⚠ ' + err.message;
      bubble.appendChild(errEl);
    }
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

btnSend.addEventListener('click', (e) => {
  if (isStreaming) {
    e.preventDefault();
    stopGeneration();
  }
});

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

document.addEventListener('click', () => {
  document.querySelectorAll('.msg-dropdown:not(.hidden), .session-dropdown:not(.hidden)').forEach(d => d.classList.add('hidden'));
});

renderSidebar();
replayHistory(sessionId);
input.focus();

/* ── Service worker ───────────────────────────────────────────────────── */

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}
