'use strict';

// -- State --------------------------------------------------------------------
let _data = null;
let _openSession = null;
let _refreshTimer = null;
let _sessionTimer = null;
const REFRESH_MS = 5000;
const SESSION_REFRESH_MS = 2000;

// -- Helpers ------------------------------------------------------------------

function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function fmtUptime(seconds) {
  if (seconds == null) return '\u2014';
  if (seconds < 60) return seconds + 's';
  if (seconds < 3600) return Math.floor(seconds / 60) + 'm ' + (seconds % 60) + 's';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h + 'h ' + m + 'm';
}

function fmtAgo(isoStr) {
  if (!isoStr) return '\u2014';
  const diff = Math.floor((Date.now() - new Date(isoStr)) / 1000);
  if (diff < 5) return 'just now';
  if (diff < 60) return diff + 's ago';
  if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
  if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
  return Math.floor(diff / 86400) + 'd ago';
}

function fmtCountdown(ms) {
  if (!ms) return '\u2014';
  const diff = Math.floor((ms - Date.now()) / 1000);
  if (diff <= 0) return 'due now';
  return 'in ' + fmtUptime(diff);
}

function fmtBytes(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1048576).toFixed(1) + ' MB';
}

function fmtToolList(toolsObj) {
  if (!toolsObj || Object.keys(toolsObj).length === 0) return '';
  return Object.entries(toolsObj)
    .map(function(pair) {
      return pair[1] > 1 ? pair[0] + ' \u00d7' + pair[1] : pair[0];
    })
    .join(', ');
}

// -- Fetch --------------------------------------------------------------------

async function fetchDashboard() {
  try {
    const res = await fetch('/api/dashboard');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    _data = await res.json();
    render(_data);
    updateTimestamp();
  } catch (e) {
    console.warn('Dashboard fetch failed:', e);
  }
}

async function fetchSession(key) {
  try {
    const res = await fetch('/api/session/' + encodeURIComponent(key));
    if (!res.ok) return null;
    return await res.json();
  } catch (e) {
    console.warn('Session fetch failed:', e);
    return null;
  }
}

// -- Render: Main dispatch ----------------------------------------------------

function render(data) {
  if (data.status === 'initializing') {
    document.getElementById('agent-name').textContent = 'WorldClaw';
    document.getElementById('header-badges').innerHTML =
      '<span class="badge status-initializing"><span class="spinner"></span> Initializing</span>';
    return;
  }
  renderHeader(data.identity);
  renderHeaderCards(data);
  renderActivity(data.activity || []);

  // System tab
  renderSystemChannels(data.channels || {});
  renderSystemBus(data.system || {});
  renderSystemCron(data.cron || {});
  renderSystemHeartbeat(data.system || {});

  // Agent Sheet tab
  renderAgentSheet(data);
}

// -- Render: Header -----------------------------------------------------------

function renderHeader(id) {
  if (!id) return;
  document.getElementById('agent-name').textContent = id.name || 'nanobot';
  var statusClass = 'status-' + (id.status || 'idle');
  var statusLabel = id.status === 'processing'
    ? '<span class="spinner"></span> Processing'
    : (id.status || 'idle');
  document.getElementById('header-badges').innerHTML =
    '<span class="badge model">' + esc(id.model) + '</span>' +
    '<span class="badge ' + statusClass + '">' + statusLabel + '</span>' +
    '<span class="badge">up ' + fmtUptime(id.uptime_seconds || 0) + '</span>';
}

function renderHeaderCards(data) {
  var activity = data.activity || [];
  var identity = data.identity || {};

  // Count sessions with activity in last 24h
  var now = Date.now();
  var sessions24h = 0;
  activity.forEach(function(e) {
    if (e.updated_at) {
      var diff = now - new Date(e.updated_at).getTime();
      if (diff < 86400000) sessions24h++;
    }
  });

  var activeNow = identity.active_count || 0;
  var errors = activity.filter(function(e) { return e.error; }).length;

  var el = document.getElementById('header-cards');
  el.innerHTML =
    cardHtml('Sessions', sessions24h, 'today') +
    cardHtml('Active', activeNow, 'now') +
    cardHtml('Errors', errors, 'total', errors > 0 ? 'card-error' : '');
}

function cardHtml(label, value, sub, cls) {
  return '<div class="summary-card ' + (cls || '') + '">' +
    '<div class="card-value">' + esc(value) + '</div>' +
    '<div class="card-label">' + esc(label) + '</div>' +
    '<div class="card-sub">' + esc(sub) + '</div>' +
    '</div>';
}

// -- Render: Activity Feed ----------------------------------------------------

function renderActivity(entries) {
  var el = document.getElementById('activity-feed');
  if (entries.length === 0) {
    el.innerHTML = '<div class="empty">No sessions yet.</div>';
    return;
  }

  el.innerHTML = entries.map(function(e) {
    var isActive = e.active;
    var statusDot = isActive
      ? '<span class="act-dot active" title="Active"></span>'
      : '<span class="act-dot" title="Idle"></span>';
    var statusLabel = isActive ? 'ACTIVE' : 'DONE';
    var statusClass = isActive ? 'act-status-active' : 'act-status-done';

    var channel = e.channel ? '<span class="act-channel">' + esc(e.channel) + '</span>' : '';
    var tools = fmtToolList(e.tools_used);
    var toolsHtml = tools
      ? '<div class="act-tools">Tools: ' + esc(tools) + '</div>'
      : '';

    var prompt = e.user_prompt
      ? '<div class="act-prompt">' + esc(e.user_prompt) + '</div>'
      : '';

    var response = '';
    if (!isActive && e.last_response) {
      response = '<div class="act-response">' + esc(e.last_response) + '</div>';
    } else if (isActive) {
      response = '<div class="act-response act-working"><span class="spinner"></span> Working</div>';
    }

    var meta = '<span class="act-iter">' + (e.iterations || 0) + ' turns</span>';
    meta += '<span class="act-msgs">' + (e.message_count || 0) + ' msgs</span>';

    var errorBadge = e.error ? '<span class="badge act-error">error</span>' : '';

    return '<div class="act-entry ' + (isActive ? 'act-entry-active' : '') + '" data-key="' + esc(e.key) + '" onclick="openDrawer(this)">' +
      '<div class="act-header">' +
        statusDot +
        '<span class="' + statusClass + '">' + statusLabel + '</span>' +
        channel +
        '<span class="act-key">' + esc(e.key) + '</span>' +
        errorBadge +
        '<span class="act-time">' + fmtAgo(e.updated_at) + '</span>' +
      '</div>' +
      prompt +
      '<div class="act-detail">' +
        '<div class="act-meta">' + meta + '</div>' +
        toolsHtml +
      '</div>' +
      response +
    '</div>';
  }).join('');
}

// -- Render: System Tab -------------------------------------------------------

function renderSystemChannels(channels) {
  var el = document.getElementById('sys-channels');
  var names = Object.keys(channels);
  if (names.length === 0) {
    el.innerHTML = '<div class="empty">No channels enabled.</div>';
    return;
  }
  el.innerHTML = '<div class="status-grid">' + names.map(function(name) {
    var ch = channels[name];
    var ok = ch.running || ch.enabled;
    return '<div class="status-row">' +
      '<span class="status-label">' + esc(name) + '</span>' +
      '<span class="status-value ' + (ok ? 'dot-ok' : 'dot-off') + '">' +
        (ok ? 'running' : 'stopped') +
      '</span></div>';
  }).join('') + '</div>';
}

function renderSystemBus(sys) {
  var el = document.getElementById('sys-bus');
  var rows = [
    ['Inbound queue', sys.inbound_queue_depth ?? '\u2014', sys.inbound_queue_depth === 0 ? 'dot-ok' : 'dot-warn'],
    ['Outbound queue', sys.outbound_queue_depth ?? '\u2014', sys.outbound_queue_depth === 0 ? 'dot-ok' : 'dot-warn'],
  ];
  el.innerHTML = '<div class="status-grid">' + rows.map(function(r) {
    return '<div class="status-row">' +
      '<span class="status-label">' + esc(r[0]) + '</span>' +
      '<span class="status-value ' + r[2] + '">' + esc(r[1]) + '</span>' +
    '</div>';
  }).join('') + '</div>';
}

function renderSystemHeartbeat(sys) {
  var el = document.getElementById('sys-heartbeat');
  var rows = [
    ['Status', sys.heartbeat_enabled ? 'enabled' : 'disabled', sys.heartbeat_enabled ? 'dot-ok' : 'dot-off'],
    ['Interval', sys.heartbeat_enabled ? sys.heartbeat_interval_s + 's' : '\u2014', ''],
  ];
  el.innerHTML = '<div class="status-grid">' + rows.map(function(r) {
    return '<div class="status-row">' +
      '<span class="status-label">' + esc(r[0]) + '</span>' +
      '<span class="status-value ' + r[2] + '">' + esc(r[1]) + '</span>' +
    '</div>';
   }).join('') + '</div>';
}

function renderSystemCron(cron) {
  var el = document.getElementById('sys-cron');
  if (!cron.enabled) {
    el.innerHTML = '<div class="empty">Cron disabled</div>';
    return;
  }

  var jobs = cron.jobs || [];
  if (jobs.length === 0) {
    el.innerHTML = '<div class="status-grid"><div class="status-row">' +
      '<span class="status-label">Status</span>' +
      '<span class="status-value dot-ok">Running, no jobs</span></div></div>';
    return;
  }

  el.innerHTML = '<div class="cron-jobs">' + jobs.map(function(j) {
    var statusDot = j.last_status === 'ok' ? 'dot-ok'
      : j.last_status === 'error' ? 'dot-err'
      : 'dot-off';
    var schedule = j.schedule_expr || j.schedule_kind || '';
    var nextRun = j.next_run_ms ? fmtCountdown(j.next_run_ms) : '\u2014';
    var lastStatus = j.last_status || 'never run';

    return '<div class="cron-job">' +
      '<div class="cron-job-header">' +
        '<span class="cron-dot ' + statusDot + '"></span>' +
        '<span class="cron-name">' + esc(j.name) + '</span>' +
        (!j.enabled ? '<span class="badge">disabled</span>' : '') +
      '</div>' +
      '<div class="cron-detail">' +
        '<span>' + esc(schedule) + '</span>' +
        '<span>Next: ' + nextRun + '</span>' +
        '<span>Last: ' + esc(lastStatus) + '</span>' +
      '</div>' +
      (j.last_error ? '<div class="cron-error">' + esc(j.last_error) + '</div>' : '') +
    '</div>';
  }).join('') + '</div>';
}

function renderSystemMCP(tools) {
  var mcp = tools.mcp || [];
  var el = document.getElementById('sys-mcp');
  if (mcp.length === 0) {
    el.innerHTML = '<div class="empty">No MCP servers configured.</div>';
    return;
  }
  el.innerHTML = mcp.map(function(srv) {
    var connClass = srv.connected ? 'connected' : 'disconnected';
    var statusText = srv.status || (srv.connected ? 'connected' : 'disconnected');
    var toolChips = srv.tools.length
      ? '<div class="tool-chips">' + srv.tools.map(function(t) {
          return '<span class="tool-chip">' + esc(t) + '</span>';
        }).join('') + '</div>'
      : '<span class="muted">no tools</span>';
    return '<div class="mcp-card">' +
      '<div class="mcp-header">' +
        '<span class="conn-dot ' + connClass + '"></span>' +
        '<span class="mcp-name">' + esc(srv.server) + '</span>' +
        '<span class="mcp-transport">' + esc(srv.transport) + '</span>' +
      '</div>' +
      (srv.endpoint ? '<div class="mcp-endpoint">' + esc(srv.endpoint) + '</div>' : '') +
      '<div class="muted" style="font-size:11px;margin:2px 0">' + esc(statusText) + '</div>' +
      toolChips +
      '<div class="muted" style="font-size:10px;margin-top:6px">' +
        srv.tool_count + ' tool' + (srv.tool_count !== 1 ? 's' : '') + '</div>' +
    '</div>';
  }).join('');
}

function renderSystemMemory(mem) {
  var el = document.getElementById('sys-memory');
  if (!mem.available) {
    el.innerHTML = '<div class="empty">Memory not available</div>';
    return;
  }
  var files = mem.files || [];
  if (files.length === 0) {
    el.innerHTML = '<div class="empty">No memory files</div>';
    return;
  }
  el.innerHTML = '<div class="status-grid">' + files.map(function(f) {
    return '<div class="status-row mem-file-row" data-filename="' + esc(f.name) + '" onclick="openFileModal(this)">' +
      '<span class="status-label mem-file-link">' + esc(f.name) + '</span>' +
      '<span class="status-value">' + fmtBytes(f.size_bytes || 0) + '</span>' +
    '</div>';
  }).join('') + '</div>';
}

// -- Render: Agent Sheet Tab ---------------------------------------------------

function renderAgentSheet(data) {
  renderSheetSkills(data.skills || []);
  renderSheetMCP(data.tools?.mcp || []);
  renderSheetTools(data.tools?.builtin || []);
  renderSheetMemory(data.memory || {});
}

function renderSheetSkills(skills) {
  var el = document.getElementById('sheet-skills');
  document.getElementById('sheet-skills-count').textContent = skills.length;

  if (skills.length === 0) {
    el.innerHTML = '<div class="empty">No skills configured</div>';
    return;
  }

  el.innerHTML = '<div class="item-list">' + skills.map(function(s) {
    var availClass = s.available ? 'item-ok' : 'item-warn';
    var sourceBadge = s.source === 'workspace' ? '<span class="badge-small badge-ws">workspace</span>' : '';
    var alwaysBadge = s.always ? '<span class="badge-small badge-always">always</span>' : '';
    return '<div class="item-row clickable" data-skill="' + esc(s.name) + '" onclick="openSkillModal(this)">' +
      '<span class="item-dot ' + availClass + '"></span>' +
      '<span class="item-name">' + esc(s.name) + '</span>' +
      sourceBadge + alwaysBadge +
      '<span class="item-desc">' + esc(s.description || '') + '</span>' +
    '</div>';
  }).join('') + '</div>';
}

function renderSheetTools(tools) {
  var el = document.getElementById('sheet-tools');
  document.getElementById('sheet-tools-count').textContent = tools.length;

  if (tools.length === 0) {
    el.innerHTML = '<div class="empty">No tools registered</div>';
    return;
  }

  el.innerHTML = '<div class="item-list">' + tools.map(function(t) {
    return '<div class="item-row clickable" data-tool="' + esc(t.name) + '" onclick="openToolModal(this)">' +
      '<span class="item-name">' + esc(t.name) + '</span>' +
      '<span class="item-desc">' + esc(t.description || '') + '</span>' +
    '</div>';
  }).join('') + '</div>';
}

function renderSheetMCP(mcpServers) {
  var el = document.getElementById('sheet-mcp');
  document.getElementById('sheet-mcp-count').textContent = mcpServers.length;

  if (mcpServers.length === 0) {
    el.innerHTML = '<div class="empty">No MCP servers configured</div>';
    return;
  }

  el.innerHTML = '<div class="item-list">' + mcpServers.map(function(s) {
    var connClass = s.connected ? 'item-ok' : (s.status === 'failed' ? 'item-err' : 'item-warn');
    return '<div class="item-row clickable" data-mcp="' + esc(s.server) + '" onclick="openMCPModal(this)">' +
      '<span class="item-dot ' + connClass + '"></span>' +
      '<span class="item-name">' + esc(s.server) + '</span>' +
      '<span class="item-badge">' + esc(s.transport) + '</span>' +
      '<span class="item-desc">' + s.tool_count + ' tools</span>' +
    '</div>';
  }).join('') + '</div>';
}

function renderSheetMemory(memory) {
  var el = document.getElementById('sheet-memory');

  if (!memory.available) {
    el.innerHTML = '<div class="empty">Memory not available</div>';
    document.getElementById('sheet-memory-count').textContent = '0';
    return;
  }

  var files = memory.files || [];
  document.getElementById('sheet-memory-count').textContent = files.length;

  if (files.length === 0) {
    el.innerHTML = '<div class="empty">No memory files</div>';
    return;
  }

  el.innerHTML = '<div class="item-list">' + files.map(function(f) {
    return '<div class="item-row clickable" data-file="' + esc(f.name) + '" onclick="openFileModalByName(this.dataset.file)">' +
      '<span class="item-name">' + esc(f.name) + '</span>' +
      '<span class="item-desc">' + fmtBytes(f.size_bytes) + '</span>' +
    '</div>';
  }).join('') + '</div>';
}

// -- File Viewer Modal --------------------------------------------------------

async function openFileModal(rowEl) {
  var filename = rowEl.dataset.filename;
  if (!filename) return;
  openFileModalByName(filename);
}

async function openFileModalByName(filename) {
  if (!filename) return;

  var overlay = document.getElementById('file-modal');
  var titleEl = document.getElementById('file-modal-title');
  var sizeEl = document.getElementById('file-modal-size');
  var contentEl = document.getElementById('file-modal-content');

  titleEl.textContent = filename;
  sizeEl.textContent = '';
  contentEl.textContent = 'Loading\u2026';
  overlay.classList.add('open');

  try {
    var res = await fetch('/api/memory/' + encodeURIComponent(filename));
    if (!res.ok) {
      var err = await res.json().catch(function() { return {}; });
      contentEl.textContent = err.error || 'Failed to load file (HTTP ' + res.status + ')';
      return;
    }
    var data = await res.json();
    sizeEl.textContent = fmtBytes(data.size_bytes || 0);
    contentEl.textContent = data.content || '(empty file)';
  } catch (e) {
    contentEl.textContent = 'Error: ' + e.message;
  }
}

function closeFileModal(event) {
  if (event && event.target && !event.target.classList.contains('modal-overlay')) return;
  document.getElementById('file-modal').classList.remove('open');
}

// -- Detail Modal (Tool/Skill/MCP) ---------------------------------------------

function showDetailModal(title, content) {
  document.getElementById('detail-modal-title').textContent = title;
  document.getElementById('detail-modal-badge').textContent = '';
  document.getElementById('detail-modal-subtitle').textContent = '';
  document.getElementById('detail-modal-content').innerHTML = content;
  document.getElementById('detail-modal-json').style.display = 'none';
  document.getElementById('detail-modal-json-btn').style.display = 'none';
  document.getElementById('detail-modal').classList.add('open');
}

function closeDetailModal(event) {
  if (event && event.target && !event.target.classList.contains('modal-overlay')) return;
  document.getElementById('detail-modal').classList.remove('open');
}

async function openToolModal(rowEl) {
  var name = rowEl.dataset.tool;
  if (!name) return;

  showDetailModal('Tool: ' + name, '<div class="empty"><span class="spinner"></span> Loading</div>');

  try {
    var res = await fetch('/api/tool/' + encodeURIComponent(name));
    if (!res.ok) throw new Error('HTTP ' + res.status);
    var data = await res.json();
    renderToolDetail(data);
  } catch (e) {
    document.getElementById('detail-modal-content').innerHTML = '<div class="empty">Error: ' + esc(e.message) + '</div>';
  }
}

function renderToolDetail(data) {
  var content = '<div class="detail-section">' +
    '<div class="detail-label">Description</div>' +
    '<div class="detail-value">' + esc(data.description || 'No description') + '</div>' +
  '</div>';

  var params = data.parameters || {};
  var props = params.properties || {};
  var required = params.required || [];

  if (Object.keys(props).length > 0) {
    content += '<div class="detail-section">' +
      '<div class="detail-label">Parameters</div>' +
      '<table class="params-table">' +
      '<thead><tr><th>Name</th><th>Type</th><th>Required</th><th>Description</th></tr></thead>' +
      '<tbody>';

    for (var key in props) {
      var p = props[key];
      var type = p.type || 'any';
      if (p.enum) type += ' (' + p.enum.join('|') + ')';
      var desc = p.description || '';
      content += '<tr>' +
        '<td class="param-name">' + esc(key) + '</td>' +
        '<td class="param-type">' + esc(type) + '</td>' +
        '<td class="param-req">' + (required.indexOf(key) >= 0 ? 'yes' : 'no') + '</td>' +
        '<td class="param-desc">' + esc(desc) + '</td>' +
      '</tr>';
    }

    content += '</tbody></table></div>';
  } else {
    content += '<div class="detail-section">' +
      '<div class="detail-label">Parameters</div>' +
      '<div class="detail-value muted">No parameters</div>' +
    '</div>';
  }

  var jsonEl = document.getElementById('detail-modal-json');
  jsonEl.textContent = JSON.stringify(data.parameters, null, 2);
  document.getElementById('detail-modal-json-btn').style.display = 'inline-block';

  document.getElementById('detail-modal-content').innerHTML = content;
}

async function openSkillModal(rowEl) {
  var name = rowEl.dataset.skill;
  if (!name) return;

  showDetailModal('Skill: ' + name, '<div class="empty"><span class="spinner"></span> Loading</div>');

  try {
    var res = await fetch('/api/skill/' + encodeURIComponent(name));
    if (!res.ok) throw new Error('HTTP ' + res.status);
    var data = await res.json();
    renderSkillDetail(data);
  } catch (e) {
    document.getElementById('detail-modal-content').innerHTML = '<div class="empty">Error: ' + esc(e.message) + '</div>';
  }
}

function renderSkillDetail(data) {
  var truncatedNotice = data.truncated
    ? '<div class="truncated-notice">Content truncated at 100KB</div>'
    : '';

  document.getElementById('detail-modal-content').innerHTML =
    truncatedNotice +
    '<pre class="skill-content">' + esc(data.content) + '</pre>';
}

async function openMCPModal(rowEl) {
  var server = rowEl.dataset.mcp;
  if (!server) return;

  showDetailModal('MCP Server: ' + server, '<div class="empty"><span class="spinner"></span> Loading</div>');

  try {
    var res = await fetch('/api/mcp/' + encodeURIComponent(server));
    if (!res.ok) throw new Error('HTTP ' + res.status);
    var data = await res.json();
    renderMCPDetail(data);
  } catch (e) {
    document.getElementById('detail-modal-content').innerHTML = '<div class="empty">Error: ' + esc(e.message) + '</div>';
  }
}

function renderMCPDetail(data) {
  var statusClass = data.status === 'connected' ? 'item-ok' : 'item-warn';
  var content = '<div class="detail-grid">' +
    '<div class="detail-row"><span class="detail-label">Status</span>' +
      '<span class="detail-value"><span class="item-dot ' + statusClass + '"></span> ' + esc(data.status) + '</span></div>' +
    '<div class="detail-row"><span class="detail-label">Transport</span>' +
      '<span class="detail-value">' + esc(data.transport) + '</span></div>' +
    '<div class="detail-row"><span class="detail-label">Endpoint</span>' +
      '<span class="detail-value code">' + esc(data.endpoint || '-') + '</span></div>' +
    '<div class="detail-row"><span class="detail-label">Connect Timeout</span>' +
      '<span class="detail-value">' + data.connect_timeout + 's</span></div>' +
    '<div class="detail-row"><span class="detail-label">Tool Timeout</span>' +
      '<span class="detail-value">' + data.tool_timeout + 's</span></div>' +
    '<div class="detail-row"><span class="detail-label">Loaded</span>' +
      '<span class="detail-value">' + (data.loaded ? 'yes' : 'no') + '</span></div>' +
  '</div>';

  var tools = data.tools || [];
  if (tools.length > 0) {
    content += '<div class="detail-section">' +
      '<div class="detail-label">Tools (' + tools.length + ')</div>' +
      '<div class="tool-list">';

    tools.forEach(function(t) {
      content += '<div class="tool-list-item clickable" data-server="' + esc(data.server) + '" data-tool="' + esc(t.name) + '" onclick="openMCPToolModal(this)">' +
        '<span class="tool-list-name">' + esc(t.name) + '</span>' +
        '<span class="tool-list-desc">' + esc(t.description || '') + '</span>' +
      '</div>';
    });

    content += '</div></div>';
  }

  document.getElementById('detail-modal-content').innerHTML = content;
}

function openMCPToolModal(rowEl) {
  var server = rowEl.dataset.server;
  var tool = rowEl.dataset.tool;

  showDetailModal('MCP Tool: ' + tool, '<div class="empty"><span class="spinner"></span> Loading</div>');

  fetch('/api/mcp/' + encodeURIComponent(server))
    .then(function(res) { return res.json(); })
    .then(function(data) {
      var toolData = (data.tools || []).find(function(t) { return t.name === tool; });
      if (toolData) {
        renderToolDetail({
          name: tool,
          description: toolData.description,
          parameters: toolData.input_schema,
        });
      } else {
        document.getElementById('detail-modal-content').innerHTML = '<div class="empty">Tool not found</div>';
      }
    })
    .catch(function(e) {
      document.getElementById('detail-modal-content').innerHTML = '<div class="empty">Error: ' + esc(e.message) + '</div>';
    });
}

// -- Session Inspector Drawer -------------------------------------------------

async function openDrawer(rowEl) {
  var key = rowEl.dataset.key;
  if (!key) return;
  _openSession = key;

  var drawer = document.getElementById('session-drawer');
  var titleEl = document.getElementById('drawer-title');
  var statsEl = document.getElementById('drawer-stats');
  var msgsEl = document.getElementById('drawer-messages');

  titleEl.textContent = key;
  statsEl.innerHTML = '';
  msgsEl.innerHTML = '<div class="empty"><span class="spinner"></span> Loading</div>';
  drawer.classList.add('open');
  drawer.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  await loadSessionIntoDrawer(key);

  // Auto-refresh for active sessions
  clearInterval(_sessionTimer);
  var entry = (_data && _data.activity || []).find(function(e) { return e.key === key; });
  if (entry && entry.active) {
    _sessionTimer = setInterval(function() {
      if (_openSession === key) loadSessionIntoDrawer(key);
    }, SESSION_REFRESH_MS);
  }
}

async function loadSessionIntoDrawer(key) {
  var session = await fetchSession(key);
  if (!session || _openSession !== key) return;

  var statsEl = document.getElementById('drawer-stats');
  var msgsEl = document.getElementById('drawer-messages');

  if (session.error) {
    msgsEl.innerHTML = '<div class="empty">Session not found.</div>';
    return;
  }

  // Stats bar
  var stats = session.stats || {};
  var toolUsage = stats.tool_usage || {};
  var toolSummary = fmtToolList(toolUsage);

  statsEl.innerHTML =
    '<span>' + session.message_count + ' messages</span>' +
    (toolSummary ? '<span>Tools: ' + esc(toolSummary) + '</span>' : '') +
    (stats.unconsolidated != null
      ? '<span>Unconsolidated: ' + stats.unconsolidated + '</span>'
      : '');

  if (!session.messages || session.messages.length === 0) {
    msgsEl.innerHTML = '<div class="empty">No messages in this session.</div>';
    return;
  }

  // Group messages: merge assistant + its tool_calls + subsequent tool results
  var grouped = groupMessages(session.messages);
  msgsEl.innerHTML = grouped.map(renderMessageGroup).join('');
  msgsEl.scrollTop = msgsEl.scrollHeight;
}

function groupMessages(messages) {
  // Group: each "user" or "assistant" message starts a group.
  // Tool results attach to the preceding assistant group.
  var groups = [];
  var current = null;

  for (var i = 0; i < messages.length; i++) {
    var m = messages[i];
    var role = m.role || 'system';

    if (role === 'tool') {
      // Attach to current group if it's an assistant group
      if (current && current.role === 'assistant') {
        current.toolResults.push(m);
      } else {
        groups.push({ role: 'tool', message: m, toolResults: [] });
      }
    } else {
      current = { role: role, message: m, toolResults: [] };
      groups.push(current);
    }
  }
  return groups;
}

function renderMessageGroup(group) {
  var m = group.message;
  var role = group.role;
  var roleClass = 'msg-' + role;
  var content = esc(m.content || '');
  var ts = m.timestamp
    ? '<div class="msg-ts">' + esc(m.timestamp) + '</div>'
    : '';

  // Tool calls inline
  var toolCallsHtml = '';
  if (m.tool_calls && m.tool_calls.length) {
    toolCallsHtml = m.tool_calls.map(function(tc, idx) {
      var result = group.toolResults[idx];
      var resultContent = result ? esc(result.content || '') : '';
      var toolName = result && result.name ? result.name : tc.name;
      return '<div class="tool-block">' +
        '<div class="tool-block-header">' + esc(toolName) + '</div>' +
        '<div class="tool-block-args">' + esc(tc.arguments || '') + '</div>' +
        (resultContent ? '<div class="tool-block-result">' + resultContent + '</div>' : '') +
      '</div>';
    }).join('');
  }

  // Name label for tool messages shown standalone
  var nameHtml = m.name ? '<span class="msg-name">' + esc(m.name) + '</span>' : '';

  return '<div class="msg ' + roleClass + '">' +
    '<div class="msg-role">' + role + '</div>' +
    nameHtml +
    (content ? '<div class="msg-content">' + content + '</div>' : '') +
    toolCallsHtml +
    ts +
  '</div>';
}

function closeDrawer() {
  _openSession = null;
  clearInterval(_sessionTimer);
  document.getElementById('session-drawer').classList.remove('open');
}

// -- Tabs ---------------------------------------------------------------------

function initTabs() {
  document.querySelectorAll('.tab').forEach(function(tab) {
    tab.addEventListener('click', function() {
      document.querySelectorAll('.tab').forEach(function(t) { t.classList.remove('active'); });
      document.querySelectorAll('.tab-content').forEach(function(c) { c.classList.remove('active'); });
      tab.classList.add('active');
      document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
    });
  });
}

// -- Polling ------------------------------------------------------------------

function updateTimestamp() {
  var el = document.getElementById('last-updated');
  if (el) el.textContent = 'updated ' + fmtAgo(new Date().toISOString());
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

// -- Init ---------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', function() {
  initTabs();
  document.getElementById('refresh-btn').addEventListener('click', fetchDashboard);

  // JSON Schema toggle for detail modal
  document.getElementById('detail-modal-json-btn').addEventListener('click', function() {
    var jsonEl = document.getElementById('detail-modal-json');
    var contentEl = document.getElementById('detail-modal-content');
    if (jsonEl.style.display === 'none') {
      jsonEl.style.display = 'block';
      contentEl.style.display = 'none';
      this.textContent = 'Show Table';
    } else {
      jsonEl.style.display = 'none';
      contentEl.style.display = 'block';
      this.textContent = 'Show JSON Schema';
    }
  });

  fetchDashboard();
  startPolling();

  document.addEventListener('visibilitychange', function() {
    if (document.hidden) {
      stopPolling();
      clearInterval(_sessionTimer);
    } else {
      fetchDashboard();
      startPolling();
    }
  });
});
