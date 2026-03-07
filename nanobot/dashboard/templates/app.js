'use strict';

// ── State ──────────────────────────────────────────────────────────────────
let _data = null;
let _selectedSession = null;
let _refreshTimer = null;
const REFRESH_MS = 5000;

// ── Helpers ────────────────────────────────────────────────────────────────

function fmt_uptime(seconds) {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

function fmt_ago(isoStr) {
  if (!isoStr) return '—';
  const diff = Math.floor((Date.now() - new Date(isoStr)) / 1000);
  if (diff < 5)   return 'just now';
  if (diff < 60)  return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function fmt_next_run(ms) {
  if (!ms) return '—';
  const diff = Math.floor((ms - Date.now()) / 1000);
  if (diff <= 0) return 'soon';
  return 'in ' + fmt_uptime(diff);
}

function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Fetch ──────────────────────────────────────────────────────────────────

async function fetchDashboard() {
  try {
    const res = await fetch('/api/dashboard');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    _data = await res.json();
    render(_data);
    updateLastUpdated();
  } catch (e) {
    console.warn('Dashboard fetch failed:', e);
  }
}

async function fetchSession(key) {
  try {
    const res = await fetch('/api/session/' + encodeURIComponent(key));
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (e) {
    console.warn('Session fetch failed:', e);
    return null;
  }
}

// ── Render ─────────────────────────────────────────────────────────────────

function render(data) {
  if (data.status === 'initializing') {
    renderInitializing();
    return;
  }
  renderHeader(data.identity);
  renderSessions(data.sessions || []);
  renderTools(data.tools || {});
  renderChannels(data.channels || {});
  renderSystem(data);
}

function renderInitializing() {
  document.getElementById('agent-name').textContent = 'WorldClaw';
  document.getElementById('header-meta').innerHTML =
    '<span class="badge status-initializing"><span class="spinner"></span> Initializing…</span>';
}

function renderHeader(id) {
  if (!id) return;
  document.getElementById('agent-name').textContent = id.name || 'nanobot';
  const statusClass = 'status-' + (id.status || 'idle');
  const statusLabel = id.status === 'processing'
    ? '<span class="spinner"></span> Processing'
    : id.status || 'idle';
  document.getElementById('header-meta').innerHTML = `
    <span class="badge model">${esc(id.model)}</span>
    <span class="badge ${statusClass}">${statusLabel}</span>
    <span class="badge">up ${fmt_uptime(id.uptime_seconds || 0)}</span>
  `;
}

function renderSessions(sessions) {
  const list = document.getElementById('session-list');
  const count = document.getElementById('sessions-count');
  count.textContent = `${sessions.length} session${sessions.length !== 1 ? 's' : ''}`;

  if (sessions.length === 0) {
    list.innerHTML = '<div class="empty">No sessions yet.</div>';
    return;
  }

  list.innerHTML = sessions.map(s => {
    const active = s.active;
    const indClass = active ? 'active' : '';
    const rowClass = active ? 'active-session' : '';
    const msgs = s.message_count ? `${s.message_count} msg${s.message_count !== 1 ? 's' : ''}` : '';
    const ago = fmt_ago(s.updated_at);
    const preview = s.last_preview || (active ? 'Processing…' : '');
    return `
      <div class="session-row ${rowClass}" data-key="${esc(s.key)}" onclick="openSession(this)">
        <span class="session-indicator ${indClass}" title="${active ? 'active' : 'idle'}"></span>
        <span class="session-key">${esc(s.key)}</span>
        <span class="session-preview">${esc(preview)}</span>
        <span class="session-meta">${esc(ago)}</span>
        <span class="session-msgs">${esc(msgs)}</span>
      </div>`;
  }).join('');
}

function renderTools(tools) {
  const builtin = tools.builtin || [];
  const mcp = tools.mcp || [];

  // Built-in chips
  const builtinEl = document.getElementById('builtin-tools');
  builtinEl.innerHTML = builtin.length
    ? builtin.map(n => `<span class="tool-chip">${esc(n)}</span>`).join('')
    : '<span class="empty">None registered</span>';

  // MCP servers
  const mcpEl = document.getElementById('mcp-servers');
  if (mcp.length === 0) {
    mcpEl.innerHTML = '<div class="empty">No MCP servers configured.</div>';
    return;
  }
  mcpEl.innerHTML = mcp.map(srv => {
    const connClass = srv.connected ? 'connected' : 'disconnected';
    const connLabel = srv.connected ? 'connected' : 'disconnected';
    const toolChips = srv.tools.length
      ? srv.tools.map(t => `<span class="tool-chip">${esc(t)}</span>`).join('')
      : '<span style="color:var(--muted);font-size:11px">no tools</span>';
    return `
      <div class="mcp-server-card">
        <div class="mcp-server-header">
          <span class="conn-dot ${connClass}" title="${connLabel}"></span>
          <span class="mcp-server-name">${esc(srv.server)}</span>
          <span class="mcp-transport">${esc(srv.transport)}</span>
        </div>
        ${srv.endpoint ? `<div class="mcp-endpoint">${esc(srv.endpoint)}</div>` : ''}
        <div class="tool-chips">${toolChips}</div>
        <div style="font-size:10px;color:var(--muted);margin-top:6px">
          ${srv.tool_count} tool${srv.tool_count !== 1 ? 's' : ''} · timeout ${srv.tool_timeout}s
        </div>
      </div>`;
  }).join('');
}

function renderChannels(channels) {
  const el = document.getElementById('channels-body');
  const names = Object.keys(channels);
  if (names.length === 0) {
    el.innerHTML = '<div class="empty">No channels enabled.</div>';
    return;
  }
  el.innerHTML = '<div class="status-grid">' + names.map(name => {
    const ch = channels[name];
    const ok = ch.running || ch.enabled;
    const dot = ok ? 'dot-ok' : 'dot-off';
    const label = ok ? '● running' : '○ stopped';
    return `
      <div class="status-row">
        <span class="status-label">${esc(name)}</span>
        <span class="status-value ${dot}">${label}</span>
      </div>`;
  }).join('') + '</div>';
}

function renderSystem(data) {
  const sys = data.system || {};
  const cron = data.cron || {};
  const el = document.getElementById('system-body');

  const rows = [
    ['Inbound queue',  sys.inbound_queue_depth ?? '—', sys.inbound_queue_depth === 0 ? 'dot-ok' : 'dot-err'],
    ['Outbound queue', sys.outbound_queue_depth ?? '—', sys.outbound_queue_depth === 0 ? 'dot-ok' : 'dot-err'],
    ['Heartbeat',
      sys.heartbeat_enabled
        ? `● every ${sys.heartbeat_interval_s}s`
        : '○ disabled',
      sys.heartbeat_enabled ? 'dot-ok' : 'dot-off'],
    ['Cron',
      cron.enabled
        ? `● ${cron.jobs_count} job${cron.jobs_count !== 1 ? 's' : ''} · next ${fmt_next_run(cron.next_run_ms)}`
        : '○ disabled',
      cron.enabled && cron.jobs_count > 0 ? 'dot-ok' : 'dot-off'],
  ];

  el.innerHTML = '<div class="status-grid">' + rows.map(([label, val, cls]) => `
    <div class="status-row">
      <span class="status-label">${esc(label)}</span>
      <span class="status-value ${cls}">${esc(val)}</span>
    </div>`).join('') + '</div>';
}

// ── Session detail drawer ──────────────────────────────────────────────────

async function openSession(rowEl) {
  const key = rowEl.dataset.key;
  if (!key) return;
  _selectedSession = key;

  const detail = document.getElementById('session-detail');
  const titleEl = document.getElementById('session-detail-title');
  const msgsEl = document.getElementById('session-messages');

  titleEl.textContent = key;
  msgsEl.innerHTML = '<div class="empty"><span class="spinner"></span> Loading…</div>';
  detail.classList.add('open');
  detail.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  const session = await fetchSession(key);
  if (!session) {
    msgsEl.innerHTML = '<div class="empty">Failed to load session.</div>';
    return;
  }

  if (!session.messages || session.messages.length === 0) {
    msgsEl.innerHTML = '<div class="empty">No messages in this session.</div>';
    return;
  }

  msgsEl.innerHTML = session.messages.map(m => {
    const roleClass = 'msg-' + (m.role || 'system');
    const roleLabel = m.role || 'system';
    const content = esc(m.content || '');
    const ts = m.timestamp ? `<div class="msg-timestamp">${esc(m.timestamp)}</div>` : '';

    let toolCallsHtml = '';
    if (m.tool_calls && m.tool_calls.length) {
      toolCallsHtml = '<div class="msg-tool-call">' +
        m.tool_calls.map(tc =>
          `<span class="tool-call-chip">${esc(tc.name)}(${esc(tc.arguments || '')})</span>`
        ).join('') + '</div>';
    }

    let nameHtml = '';
    if (m.name) nameHtml = `<span style="color:var(--yellow);margin-right:4px">${esc(m.name)}</span>`;

    return `
      <div class="msg ${roleClass}">
        <div class="msg-role">${roleLabel}</div>
        ${nameHtml}
        <div class="msg-content">${content}</div>
        ${toolCallsHtml}
        ${ts}
      </div>`;
  }).join('');

  // Scroll to bottom of message list
  msgsEl.scrollTop = msgsEl.scrollHeight;
}

function closeSession() {
  _selectedSession = null;
  const detail = document.getElementById('session-detail');
  detail.classList.remove('open');
}

// ── Refresh ────────────────────────────────────────────────────────────────

function updateLastUpdated() {
  const el = document.getElementById('last-updated');
  if (el) el.textContent = 'updated ' + fmt_ago(new Date().toISOString());
}

function startPolling() {
  if (_refreshTimer) return;
  _refreshTimer = setInterval(fetchDashboard, REFRESH_MS);
}

function stopPolling() {
  if (_refreshTimer) {
    clearInterval(_refreshTimer);
    _refreshTimer = null;
  }
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('refresh-btn').addEventListener('click', fetchDashboard);
  fetchDashboard();
  startPolling();

  // Pause polling when tab is hidden; resume (with immediate fetch) on return
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      stopPolling();
    } else {
      fetchDashboard();
      startPolling();
    }
  });
});
