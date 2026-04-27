// ── Nanobot Web UI ──
// Pure vanilla JS — no build tools, no Node.js.

(function () {
  "use strict";

  // ── Elements ──
  const messagesEl = document.getElementById("messages");
  const inputEl    = document.getElementById("input");
  const formEl     = document.getElementById("chat-form");
  const sendBtn    = document.getElementById("btn-send");
  const statusEl   = document.getElementById("status");
  const newBtn     = document.getElementById("btn-new");
  const chatsBtn   = document.getElementById("btn-chats");
  const chatMenu   = document.getElementById("chat-menu");
  const chatListEl = document.getElementById("chat-list");
  const headerTitle = document.getElementById("header-title");

  // ── State ──
  let ws = null;
  let streamBubble = null;   // currently streaming bot message element
  let streamText   = "";     // accumulated raw markdown during stream
  let connected    = false;
  let syncing      = false;  // true while replaying missed messages

  // ── Device ID (unique per browser, never changes) ──
  var deviceId = localStorage.getItem("nanobot_device_id");
  if (!deviceId) {
    deviceId = crypto.randomUUID ? crypto.randomUUID().replace(/-/g, "").slice(0, 12) : Math.random().toString(36).slice(2, 14);
    localStorage.setItem("nanobot_device_id", deviceId);
  }

  // ── Bearer token (stored in localStorage, prompted on 401) ──
  var authToken = localStorage.getItem("nanobot_token") || "";

  function authHeaders() {
    var h = {};
    if (authToken) h["Authorization"] = "Bearer " + authToken;
    return h;
  }

  function promptForToken() {
    var t = prompt("This server requires a bearer token. Paste it here:");
    if (t !== null) {
      authToken = t.trim();
      localStorage.setItem("nanobot_token", authToken);
      return true;
    }
    return false;
  }

  // ── URL-based chat ID ──
  // Check hash first (e.g. /#abc123def456), then fall back to localStorage.
  // This lets users share a URL to pick up a conversation on another device.

  function getChatIdFromHash() {
    var hash = location.hash.replace(/^#\/?/, "").trim();
    return hash || null;
  }

  function setHash(id) {
    if (id) {
      history.replaceState(null, "", "#" + id);
    }
  }

  var hashId = getChatIdFromHash();
  var chatId = hashId || localStorage.getItem("nanobot_chat_id") || null;
  var lastSeenTs = 0;

  // If we got a chat ID from the URL, adopt it — even if it's new to this browser
  if (hashId) {
    chatId = hashId;
    localStorage.setItem("nanobot_chat_id", chatId);
    // Use 0 so we fetch full history from server for this chat
    lastSeenTs = 0;
    localStorage.setItem("nanobot_last_seen", "0");
  } else {
    lastSeenTs = parseFloat(localStorage.getItem("nanobot_last_seen") || "0");
  }

  // ── Chat History (localStorage) ──
  // Stores known chat IDs with local metadata: { id, preview, lastTs }
  // Key: "nanobot_chats" → JSON array

  function getKnownChats() {
    try {
      return JSON.parse(localStorage.getItem("nanobot_chats") || "[]");
    } catch (_) { return []; }
  }

  function saveKnownChats(chats) {
    localStorage.setItem("nanobot_chats", JSON.stringify(chats));
  }

  function upsertChat(id, preview, lastTs) {
    var chats = getKnownChats();
    var existing = chats.find(function (c) { return c.id === id; });
    if (existing) {
      if (preview) existing.preview = preview;
      if (lastTs > (existing.lastTs || 0)) existing.lastTs = lastTs;
    } else {
      chats.push({ id: id, preview: preview || "(new chat)", lastTs: lastTs || 0 });
    }
    // Sort by most recent
    chats.sort(function (a, b) { return (b.lastTs || 0) - (a.lastTs || 0); });
    // Keep last 20
    if (chats.length > 20) chats = chats.slice(0, 20);
    saveKnownChats(chats);
  }

  function removeChat(id) {
    var chats = getKnownChats().filter(function (c) { return c.id !== id; });
    saveKnownChats(chats);
  }

  // Make sure current chat is tracked
  if (chatId) {
    upsertChat(chatId, null, lastSeenTs);
  }

  // ── Lightweight Markdown ──
  // Converts a subset of Markdown to HTML (code blocks, inline code, bold,
  // italic, links, headers, lists, blockquotes, tables).  Good enough for
  // chat — no external library needed.

  function escapeHtml(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function renderMarkdown(src) {
    // Protect code blocks
    var blocks = [];
    src = src.replace(/```(\w*)\n?([\s\S]*?)```/g, function (_, lang, code) {
      blocks.push('<pre><code class="lang-' + escapeHtml(lang) + '">' + escapeHtml(code.replace(/\n$/, "")) + "</code></pre>");
      return "\x00CB" + (blocks.length - 1) + "\x00";
    });

    // Protect inline code
    var inlines = [];
    src = src.replace(/`([^`]+)`/g, function (_, code) {
      inlines.push("<code>" + escapeHtml(code) + "</code>");
      return "\x00IC" + (inlines.length - 1) + "\x00";
    });

    // Split into lines for block-level processing
    var lines = src.split("\n");
    var html = [];
    var inList = null; // "ul" | "ol" | null
    var inBlockquote = false;
    var tableRows = [];

    function flushList() {
      if (inList) { html.push("</" + inList + ">"); inList = null; }
    }
    function flushBlockquote() {
      if (inBlockquote) { html.push("</blockquote>"); inBlockquote = false; }
    }
    function flushTable() {
      if (tableRows.length === 0) return;
      var thead = tableRows[0];
      var tbody = tableRows.slice(2); // skip separator row
      var out = "<table><thead><tr>";
      thead.forEach(function (c) { out += "<th>" + processInline(c.trim()) + "</th>"; });
      out += "</tr></thead><tbody>";
      tbody.forEach(function (row) {
        out += "<tr>";
        row.forEach(function (c) { out += "<td>" + processInline(c.trim()) + "</td>"; });
        out += "</tr>";
      });
      out += "</tbody></table>";
      html.push(out);
      tableRows = [];
    }

    function processInline(s) {
      // Bold
      s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
      s = s.replace(/__(.+?)__/g, "<strong>$1</strong>");
      // Italic
      s = s.replace(/(?<![a-zA-Z0-9])\*([^*]+)\*(?![a-zA-Z0-9])/g, "<em>$1</em>");
      s = s.replace(/(?<![a-zA-Z0-9])_([^_]+)_(?![a-zA-Z0-9])/g, "<em>$1</em>");
      // Strikethrough
      s = s.replace(/~~(.+?)~~/g, "<del>$1</del>");
      // Links [text](url)
      s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
      return s;
    }

    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];

      // Code block placeholder — pass through
      if (/^\x00CB\d+\x00$/.test(line.trim())) {
        flushList(); flushBlockquote(); flushTable();
        var idx = parseInt(line.trim().replace(/\x00CB|\x00/g, ""), 10);
        html.push(blocks[idx]);
        continue;
      }

      // Table row (pipes)
      if (/^\s*\|.+\|/.test(line)) {
        flushList(); flushBlockquote();
        var cells = line.trim().replace(/^\||\|$/g, "").split("|");
        // Separator row?
        if (cells.every(function (c) { return /^[\s:-]+$/.test(c); })) {
          tableRows.push(cells); // keep as marker
        } else {
          tableRows.push(cells);
        }
        continue;
      } else {
        flushTable();
      }

      // Headers
      var hm = line.match(/^(#{1,6})\s+(.+)$/);
      if (hm) {
        flushList(); flushBlockquote();
        var level = hm[1].length;
        html.push("<h" + level + ">" + processInline(escapeHtml(hm[2])) + "</h" + level + ">");
        continue;
      }

      // Blockquote
      if (/^>\s?(.*)$/.test(line)) {
        flushList(); flushTable();
        if (!inBlockquote) { html.push("<blockquote>"); inBlockquote = true; }
        html.push(processInline(escapeHtml(line.replace(/^>\s?/, ""))) + "<br>");
        continue;
      } else {
        flushBlockquote();
      }

      // Unordered list
      if (/^[\s]*[-*+]\s+(.+)$/.test(line)) {
        flushBlockquote(); flushTable();
        if (inList !== "ul") { flushList(); html.push("<ul>"); inList = "ul"; }
        var content = line.replace(/^[\s]*[-*+]\s+/, "");
        html.push("<li>" + processInline(escapeHtml(content)) + "</li>");
        continue;
      }

      // Ordered list
      var olm = line.match(/^[\s]*(\d+)\.\s+(.+)$/);
      if (olm) {
        flushBlockquote(); flushTable();
        if (inList !== "ol") { flushList(); html.push("<ol>"); inList = "ol"; }
        html.push("<li>" + processInline(escapeHtml(olm[2])) + "</li>");
        continue;
      }

      flushList();

      // Empty line
      if (line.trim() === "") {
        continue;
      }

      // Normal paragraph
      html.push("<p>" + processInline(escapeHtml(line)) + "</p>");
    }

    flushList();
    flushBlockquote();
    flushTable();

    var result = html.join("\n");

    // Restore inline code
    inlines.forEach(function (repl, j) {
      result = result.replace("\x00IC" + j + "\x00", repl);
    });
    // Restore code blocks (any remaining in inline context)
    blocks.forEach(function (repl, j) {
      result = result.replace("\x00CB" + j + "\x00", repl);
    });

    return result;
  }

  // ── UI Helpers ──

  function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function setStatus(state) {
    statusEl.className = "status " + state;
    statusEl.textContent = state;
    connected = state === "connected";
    sendBtn.disabled = !connected;
  }

  function updateHeaderTitle() {
    var chats = getKnownChats();
    var current = chats.find(function (c) { return c.id === chatId; });
    headerTitle.textContent = (current && current.name) || "Nanobot";
  }

  function addMessage(role, content) {
    var el = document.createElement("div");
    el.className = "msg " + role;
    if (role === "bot") {
      var inner = document.createElement("div");
      inner.className = "rendered";
      inner.innerHTML = renderMarkdown(content);
      el.appendChild(inner);
    } else {
      el.textContent = content;
    }
    messagesEl.appendChild(el);
    scrollToBottom();
    return el;
  }

  function showThinking() {
    var el = document.createElement("div");
    el.className = "thinking";
    el.id = "thinking";
    el.innerHTML = 'Thinking<span class="dots"></span>';
    messagesEl.appendChild(el);
    scrollToBottom();
  }

  function hideThinking() {
    var el = document.getElementById("thinking");
    if (el) el.remove();
  }

  function startStream() {
    hideThinking();
    streamText = "";
    var el = document.createElement("div");
    el.className = "msg bot streaming";
    var inner = document.createElement("div");
    inner.className = "rendered";
    el.appendChild(inner);
    messagesEl.appendChild(el);
    streamBubble = el;
    scrollToBottom();
  }

  function appendStream(delta) {
    if (!streamBubble) startStream();
    streamText += delta;
    var inner = streamBubble.querySelector(".rendered");
    inner.innerHTML = renderMarkdown(streamText);
    scrollToBottom();
  }

  function endStream(finalContent) {
    hideThinking();
    if (streamBubble) {
      streamBubble.classList.remove("streaming");
      if (finalContent) {
        var inner = streamBubble.querySelector(".rendered");
        inner.innerHTML = renderMarkdown(finalContent);
      }
      streamBubble = null;
      streamText = "";
      scrollToBottom();
    }
  }

  // ── Time formatting ──

  function formatTime(epochSecs) {
    if (!epochSecs) return "";
    var d = new Date(epochSecs * 1000);
    var now = new Date();
    var diffMs = now - d;
    var diffDays = Math.floor(diffMs / 86400000);

    if (diffDays === 0) {
      // Today — show time
      return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    } else if (diffDays === 1) {
      return "Yesterday";
    } else if (diffDays < 7) {
      return d.toLocaleDateString([], { weekday: "short" });
    } else {
      return d.toLocaleDateString([], { month: "short", day: "numeric" });
    }
  }

  // ── Chat Switcher ──

  var menuOpen = false;

  function toggleMenu() {
    menuOpen = !menuOpen;
    chatMenu.classList.toggle("hidden", !menuOpen);
    if (menuOpen) {
      refreshChatList();
    }
  }

  function closeMenu() {
    menuOpen = false;
    chatMenu.classList.add("hidden");
  }

  chatsBtn.addEventListener("click", function (e) {
    e.stopPropagation();
    toggleMenu();
  });

  // Close menu when clicking outside
  document.addEventListener("click", function (e) {
    if (menuOpen && !chatMenu.contains(e.target) && e.target !== chatsBtn) {
      closeMenu();
    }
  });

  function refreshChatList() {
    var chats = getKnownChats();
    chatListEl.innerHTML = "";

    if (chats.length === 0) {
      var empty = document.createElement("div");
      empty.className = "chat-menu-item";
      empty.style.color = "var(--text-dim)";
      empty.style.textAlign = "center";
      empty.style.cursor = "default";
      empty.textContent = "No previous chats";
      chatListEl.appendChild(empty);
      return;
    }

    // Fetch server-side metadata to enrich previews
    var ids = chats.map(function (c) { return c.id; }).join(",");
    fetch("/chats?ids=" + encodeURIComponent(ids), { headers: authHeaders() })
      .then(function (r) {
        if (r.status === 401) {
          if (promptForToken()) refreshChatList();
          return null;
        }
        return r.json();
      })
      .then(function (data) {
        if (!data) return;
        var serverMap = {};
        (data.chats || []).forEach(function (c) { serverMap[c.id] = c; });

        // Merge server data into local chats
        chats.forEach(function (c) {
          var s = serverMap[c.id];
          if (s) {
            if (s.name) c.name = s.name;
            c.preview = s.preview || c.preview;
            c.lastTs = s.last_ts || c.lastTs;
            c.count = s.count;
          }
        });
        // Re-sort after merge
        chats.sort(function (a, b) { return (b.lastTs || 0) - (a.lastTs || 0); });
        saveKnownChats(chats);

        renderChatItems(chats);
      })
      .catch(function () {
        // Offline — render from local data
        renderChatItems(chats);
      });
  }

  function renderChatItems(chats) {
    chatListEl.innerHTML = "";
    updateHeaderTitle();
    chats.forEach(function (chat) {
      var row = document.createElement("div");
      row.className = "chat-menu-row";

      var btn = document.createElement("button");
      btn.className = "chat-menu-item";
      if (chat.id === chatId) btn.classList.add("active");

      var timeSpan = document.createElement("span");
      timeSpan.className = "chat-time";
      timeSpan.textContent = formatTime(chat.lastTs);
      btn.appendChild(timeSpan);

      var title = document.createElement("span");
      title.className = "chat-title";
      title.textContent = chat.name || chat.preview || "(no messages)";
      btn.appendChild(title);

      // Show preview as subtitle when a custom name exists
      if (chat.name) {
        var preview = document.createElement("span");
        preview.className = "chat-preview";
        preview.textContent = chat.preview || "";
        btn.appendChild(preview);
      }

      btn.addEventListener("click", function () {
        closeMenu();
        switchToChat(chat.id);
      });

      btn.addEventListener("dblclick", function (e) {
        e.stopPropagation();
        var newName = prompt("Rename conversation:", chat.name || chat.preview || "");
        if (newName !== null && newName.trim()) {
          chat.name = newName.trim();
          saveKnownChats(chats);
          // Tell server so other devices see it too
          if (ws && ws.readyState === WebSocket.OPEN) {
            // Send rename for this chat — need to be connected to it or use REST
            // For simplicity, send via current ws if it's the same chat
            if (chat.id === chatId) {
              ws.send(JSON.stringify({ type: "rename", name: newName.trim() }));
            }
          }
          refreshChatList();
        }
      });

      var delBtn = document.createElement("button");
      delBtn.className = "chat-delete-btn";
      delBtn.title = "Remove conversation";
      delBtn.textContent = "\u00d7"; // × multiplication sign
      delBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        if (confirm("Remove this conversation from the list?")) {
          removeChat(chat.id);
          refreshChatList();
        }
      });

      row.appendChild(delBtn);
      row.appendChild(btn);
      chatListEl.appendChild(row);
    });
  }

  function switchToChat(newId) {
    if (newId === chatId) return; // already on this chat

    // Save current state
    if (chatId) {
      upsertChat(chatId, getFirstUserMessage(), lastSeenTs);
    }

    // Switch
    chatId = newId;
    localStorage.setItem("nanobot_chat_id", chatId);
    setHash(chatId);

    // Load the lastSeenTs for this chat from localStorage
    var chatTs = getKnownChats().find(function (c) { return c.id === newId; });
    lastSeenTs = (chatTs && chatTs.lastTs) ? chatTs.lastTs : 0;
    // We'll use 0 to get full history from server
    lastSeenTs = 0;
    localStorage.setItem("nanobot_last_seen", "0");

    // Clear screen and reconnect
    messagesEl.innerHTML = "";
    streamBubble = null;
    streamText = "";
    if (ws) ws.close();
    connect();
  }

  function getFirstUserMessage() {
    var msgs = messagesEl.querySelectorAll(".msg.user");
    if (msgs.length > 0) {
      return msgs[0].textContent.substring(0, 80);
    }
    return null;
  }

  // ── Auto-resize textarea ──

  inputEl.addEventListener("input", function () {
    this.style.height = "auto";
    this.style.height = Math.min(this.scrollHeight, 150) + "px";
  });

  // Submit on Enter (Shift+Enter for newline)
  inputEl.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      formEl.dispatchEvent(new Event("submit"));
    }
  });

  // ── Send Message ──

  formEl.addEventListener("submit", function (e) {
    e.preventDefault();
    var text = inputEl.value.trim();
    if (!text || !connected) return;

    addMessage("user", text);
    ws.send(JSON.stringify({ type: "message", content: text }));
    // Track that we've seen up to now (our own message)
    lastSeenTs = Date.now() / 1000;
    localStorage.setItem("nanobot_last_seen", String(lastSeenTs));
    // Update chat preview with first user message
    upsertChat(chatId, getFirstUserMessage(), lastSeenTs);
    inputEl.value = "";
    inputEl.style.height = "auto";
    showThinking();
  });

  // ── New Chat ──

  newBtn.addEventListener("click", function () {
    closeMenu();
    // Save current chat
    if (chatId) {
      upsertChat(chatId, getFirstUserMessage(), lastSeenTs);
    }

    messagesEl.innerHTML = "";
    // Generate new client id for a fresh session
    chatId = crypto.randomUUID ? crypto.randomUUID().replace(/-/g, "").slice(0, 12) : Math.random().toString(36).slice(2, 14);
    localStorage.setItem("nanobot_chat_id", chatId);
    setHash(chatId);
    lastSeenTs = 0;
    localStorage.setItem("nanobot_last_seen", "0");
    // Track the new chat
    upsertChat(chatId, "(new chat)", 0);
    headerTitle.textContent = "Nanobot";
    // Reconnect with new id
    if (ws) ws.close();
    connect();
  });

  // ── WebSocket ──

  var reconnectDelay = 1000;
  var maxReconnectDelay = 30000;
  var pingInterval = null;

  function connect() {
    // Close any existing connection without triggering auto-reconnect —
    // the old ws's onclose will see ws !== thisWs and bail out.
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      ws.close();
    }

    setStatus("connecting");

    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    var url = proto + "//" + location.host + "/ws";
    url += "?client_id=" + encodeURIComponent(deviceId);
    if (chatId) url += "&chat_id=" + encodeURIComponent(chatId);
    if (authToken) url += "&token=" + encodeURIComponent(authToken);

    var thisWs = new WebSocket(url);
    ws = thisWs;

    thisWs.onopen = function () {
      reconnectDelay = 1000;
    };

    thisWs.onmessage = function (ev) {
      var data;
      try { data = JSON.parse(ev.data); } catch (_) { return; }

      switch (data.type) {
        case "connected":
          didConnect = true;
          chatId = data.chat_id || data.client_id;
          localStorage.setItem("nanobot_chat_id", chatId);
          setHash(chatId);
          setStatus("connected");
          // Make sure this chat is tracked
          upsertChat(chatId, null, lastSeenTs);
          updateHeaderTitle();
          // Start keepalive
          clearInterval(pingInterval);
          pingInterval = setInterval(function () {
            if (thisWs.readyState === WebSocket.OPEN) {
              thisWs.send(JSON.stringify({ type: "ping" }));
            }
          }, 25000);
          // Request history sync — always, so page refresh restores the conversation
          thisWs.send(JSON.stringify({ type: "sync", last_seen: lastSeenTs }));
          break;

        case "sync":
          // Replay missed messages
          if (data.messages && data.messages.length > 0) {
            syncing = true;
            data.messages.forEach(function (m) {
              if (m.type === "user_message") {
                addMessage("user", m.content || "");
              } else if (m.type === "message") {
                addMessage("bot", m.content || "");
              }
              if (m.ts) {
                lastSeenTs = Math.max(lastSeenTs, m.ts);
                localStorage.setItem("nanobot_last_seen", String(lastSeenTs));
              }
            });
            syncing = false;
            scrollToBottom();
            // Update chat preview after sync
            upsertChat(chatId, getFirstUserMessage(), lastSeenTs);
          }
          break;

        case "user_message":
          // Another device sent a message on this chat
          addMessage("user", data.content || "");
          if (data.ts) {
            lastSeenTs = Math.max(lastSeenTs, data.ts);
            localStorage.setItem("nanobot_last_seen", String(lastSeenTs));
          }
          showThinking();
          break;

        case "message":
          hideThinking();
          endStream();  // finalize any in-progress stream
          addMessage("bot", data.content || "");
          if (data.ts) {
            lastSeenTs = Math.max(lastSeenTs, data.ts);
            localStorage.setItem("nanobot_last_seen", String(lastSeenTs));
            upsertChat(chatId, getFirstUserMessage(), lastSeenTs);
          }
          break;

        case "stream_delta":
          appendStream(data.delta || "");
          break;

        case "stream_end":
          endStream(data.content || null);
          if (data.ts) {
            lastSeenTs = Math.max(lastSeenTs, data.ts);
            localStorage.setItem("nanobot_last_seen", String(lastSeenTs));
            upsertChat(chatId, getFirstUserMessage(), lastSeenTs);
          }
          break;

        case "chat_renamed":
          // Server (or another device) renamed this chat
          if (data.name) {
            var knownChats = getKnownChats();
            var c = knownChats.find(function (x) { return x.id === chatId; });
            if (c) {
              c.name = data.name;
              saveKnownChats(knownChats);
            }
            updateHeaderTitle();
          }
          break;

        case "pong":
          break;

        case "error":
          hideThinking();
          addMessage("bot", "[Error] " + (data.error || "Unknown error"));
          break;
      }
    };

    var didConnect = false;

    thisWs.onclose = function (ev) {
      // If a newer connect() already replaced us, don't touch state or reconnect
      if (ws !== thisWs) return;

      setStatus("disconnected");
      clearInterval(pingInterval);
      streamBubble = null;
      streamText = "";

      // If we never got "connected" and the close code suggests auth failure,
      // prompt for a token instead of silently retrying forever.
      if (!didConnect && (ev.code === 1008 || ev.code === 1006)) {
        if (promptForToken()) {
          connect();
          return;
        }
      }

      // Auto-reconnect with backoff
      setTimeout(function () {
        if (ws !== thisWs) return; // another connect() happened while we waited
        reconnectDelay = Math.min(reconnectDelay * 2, maxReconnectDelay);
        connect();
      }, reconnectDelay);
    };

    thisWs.onerror = function () {
      // onclose will fire after this
    };
  }

  // ── Handle URL hash changes (back/forward, manual edit) ──
  window.addEventListener("hashchange", function () {
    var newId = getChatIdFromHash();
    if (newId && newId !== chatId) {
      switchToChat(newId);
    }
  });

  // ── Boot ──
  // Set the hash on initial load if we have a client ID
  if (chatId) setHash(chatId);
  connect();
})();
