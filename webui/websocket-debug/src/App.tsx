import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { JsonLogBody } from "./JsonLogBody";
import { summarizeServerPayload, tryParseServerPayload } from "./protocol";

type ConnectionStatus = "idle" | "connecting" | "open" | "closed" | "error";

type LogDirection = "in" | "out" | "system";

type LogFilter = "all" | LogDirection;

type LogEntry = {
  id: string;
  at: number;
  direction: LogDirection;
  raw: string;
  summary?: string;
};

function createLogId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function formatTime(timestampMs: number): string {
  return new Date(timestampMs).toLocaleTimeString("en-US", {
    hour12: false,
    fractionalSecondDigits: 3,
  });
}

function buildQuery(params: Record<string, string>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value.trim()) {
      search.set(key, value);
    }
  }
  const queryString = search.toString();
  return queryString ? `?${queryString}` : "";
}

export function App() {
  const [useDevProxy, setUseDevProxy] = useState(true);
  const [directWsUrl, setDirectWsUrl] = useState("ws://127.0.0.1:8765/");
  const [clientId, setClientId] = useState("webui-debug");
  const [token, setToken] = useState("");
  const [sendPayload, setSendPayload] = useState("Hello, nanobot");
  const [sendAsJson, setSendAsJson] = useState(false);

  const [tokenIssuePath, setTokenIssuePath] = useState("/auth/token");
  const [tokenIssueSecret, setTokenIssueSecret] = useState("");

  const [status, setStatus] = useState<ConnectionStatus>("idle");
  const [lastError, setLastError] = useState<string | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [logFilter, setLogFilter] = useState<LogFilter>("all");
  const [logSearch, setLogSearch] = useState("");
  const [readyInfo, setReadyInfo] = useState<{ chatId: string; clientId: string } | null>(
    null,
  );
  const [streamChunks, setStreamChunks] = useState<Record<string, string>>({});

  const socketRef = useRef<WebSocket | null>(null);
  const logScrollEndRef = useRef<HTMLDivElement | null>(null);

  const resolvedWsUrl = useMemo(() => {
    if (!useDevProxy) {
      return directWsUrl.trim();
    }
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const query = buildQuery({
      client_id: clientId,
      token,
    });
    return `${protocol}//${window.location.host}/nanobot-dev${query}`;
  }, [useDevProxy, directWsUrl, clientId, token]);

  const appendLog = useCallback((direction: LogDirection, raw: string, summary?: string) => {
    setLogs((previous) => [
      ...previous,
      {
        id: createLogId(),
        at: Date.now(),
        direction,
        raw,
        summary,
      },
    ]);
  }, []);

  const filteredLogs = useMemo(() => {
    const needle = logSearch.trim().toLowerCase();
    return logs.filter((entry) => {
      if (logFilter !== "all" && entry.direction !== logFilter) {
        return false;
      }
      if (!needle) {
        return true;
      }
      const inRaw = entry.raw.toLowerCase().includes(needle);
      const inSummary = entry.summary?.toLowerCase().includes(needle) ?? false;
      return inRaw || inSummary;
    });
  }, [logs, logFilter, logSearch]);

  useEffect(() => {
    logScrollEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [logs.length]);

  const disconnect = useCallback(() => {
    const socket = socketRef.current;
    if (socket) {
      socketRef.current = null;
      socket.close();
    }
    setStatus("closed");
    appendLog("system", "[local] Disconnected");
  }, [appendLog]);

  const handleInboundFrame = useCallback(
    (rawText: string) => {
      const parsed = tryParseServerPayload(rawText);
      const summary = parsed ? summarizeServerPayload(parsed) : undefined;
      appendLog("in", rawText, summary);

      if (!parsed) {
        return;
      }

      if (parsed.event === "ready") {
        setReadyInfo({ chatId: parsed.chat_id, clientId: parsed.client_id });
        setStreamChunks({});
        return;
      }

      if (parsed.event === "delta") {
        const streamKey = String(parsed.stream_id ?? "__default__");
        setStreamChunks((previous) => ({
          ...previous,
          [streamKey]: (previous[streamKey] ?? "") + parsed.text,
        }));
        return;
      }

      if (parsed.event === "stream_end") {
        const streamKey = String(parsed.stream_id ?? "__default__");
        setStreamChunks((previous) => {
          const finishedText = previous[streamKey];
          if (finishedText !== undefined) {
            const streamLabel = streamKey === "__default__" ? "(default)" : streamKey;
            queueMicrotask(() => {
              appendLog(
                "system",
                `[stream_end] stream_id=${streamLabel} accumulated_len=${finishedText.length}`,
              );
            });
          }
          const next = { ...previous };
          delete next[streamKey];
          return next;
        });
        return;
      }

      if (parsed.event === "message") {
        setStreamChunks({});
      }
    },
    [appendLog],
  );

  const connect = useCallback(() => {
    disconnect();
    setLastError(null);
    setReadyInfo(null);
    setStreamChunks({});
    setStatus("connecting");

    let url = resolvedWsUrl;
    if (!useDevProxy) {
      const query = buildQuery({ client_id: clientId, token });
      try {
        const parsedUrl = new URL(directWsUrl);
        parsedUrl.search = query.slice(1);
        url = parsedUrl.toString();
      } catch {
        setLastError("Invalid WebSocket URL");
        setStatus("error");
        appendLog("system", "[error] Failed to parse WebSocket URL");
        return;
      }
    }

    appendLog("system", `[connect] ${url}`);

    let socket: WebSocket;
    try {
      socket = new WebSocket(url);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setLastError(message);
      setStatus("error");
      appendLog("system", `[error] ${message}`);
      return;
    }

    socketRef.current = socket;

    socket.onopen = () => {
      setStatus("open");
      appendLog("system", "[open] WebSocket connection established");
    };

    socket.onmessage = (event) => {
      if (typeof event.data === "string") {
        handleInboundFrame(event.data);
        return;
      }
      appendLog(
        "system",
        `[recv] Non-text frame (${String(event.data?.constructor?.name ?? "unknown")})`,
      );
    };

    socket.onerror = () => {
      setLastError("WebSocket error (see browser console for details)");
      appendLog("system", "[error] WebSocket error event");
    };

    socket.onclose = (event) => {
      socketRef.current = null;
      setStatus((previous) => (previous === "connecting" ? "error" : "closed"));
      appendLog(
        "system",
        `[close] code=${event.code} reason=${event.reason || "(empty)"} wasClean=${event.wasClean}`,
      );
    };
  }, [
    appendLog,
    clientId,
    directWsUrl,
    disconnect,
    handleInboundFrame,
    resolvedWsUrl,
    token,
    useDevProxy,
  ]);

  useEffect(() => {
    return () => {
      const socket = socketRef.current;
      if (socket) {
        socket.close();
      }
    };
  }, []);

  const sendOutbound = useCallback(() => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      appendLog("system", "[send failed] Not connected");
      return;
    }

    let body: string;
    if (sendAsJson) {
      body = sendPayload.trim();
      try {
        JSON.parse(body);
      } catch {
        appendLog("system", "[send failed] Invalid JSON in send payload");
        return;
      }
    } else {
      body = sendPayload;
    }

    socket.send(body);
    appendLog("out", body);
  }, [appendLog, sendAsJson, sendPayload]);

  const clearLogs = useCallback(() => {
    setLogs([]);
  }, []);

  const fetchIssuedToken = useCallback(async () => {
    const path = tokenIssuePath.trim() || "/";
    const normalizedPath = path.startsWith("/") ? path : `/${path}`;

    let httpUrl: string;
    if (useDevProxy) {
      httpUrl = `${window.location.origin}/nanobot-dev${normalizedPath}`;
    } else {
      try {
        const wsBase = new URL(directWsUrl);
        const origin = `${wsBase.protocol === "wss:" ? "https:" : "http:"}//${wsBase.host}`;
        httpUrl = `${origin}${normalizedPath}`;
      } catch {
        appendLog("system", "[token fetch failed] Enter a valid direct WebSocket URL first");
        return;
      }
    }

    appendLog("system", `[HTTP GET] ${httpUrl}`);

    const headers: HeadersInit = {};
    const secret = tokenIssueSecret.trim();
    if (secret) {
      headers["X-Nanobot-Auth"] = secret;
    }

    try {
      const response = await fetch(httpUrl, { headers });
      const responseText = await response.text();
      if (!response.ok) {
        appendLog("system", `[token fetch failed] HTTP ${response.status}: ${responseText}`);
        return;
      }
      let parsed: unknown;
      try {
        parsed = JSON.parse(responseText) as unknown;
      } catch {
        appendLog("system", `[token fetch failed] Response is not JSON: ${responseText}`);
        return;
      }
      if (!parsed || typeof parsed !== "object" || !("token" in parsed)) {
        appendLog("system", `[token fetch failed] Missing token field: ${responseText}`);
        return;
      }
      const issued = (parsed as { token: unknown }).token;
      if (typeof issued !== "string" || !issued) {
        appendLog("system", "[token fetch failed] token must be a non-empty string");
        return;
      }
      setToken(issued);
      appendLog("system", "[token fetch ok] Token field updated");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      appendLog("system", `[token fetch failed] ${message}`);
    }
  }, [appendLog, directWsUrl, tokenIssuePath, tokenIssueSecret, useDevProxy]);

  const statusLabel = useMemo(() => {
    switch (status) {
      case "idle":
        return "Not connected";
      case "connecting":
        return "Connecting";
      case "open":
        return "Connected";
      case "closed":
        return "Closed";
      case "error":
        return "Error";
      default:
        return status;
    }
  }, [status]);

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Nanobot WebSocket debug</h1>
        <p className="app-header-desc">
          Same protocol as <code style={{ color: "var(--accent)" }}>nanobot/channels/websocket.py</code>: first frame{" "}
          <code>ready</code>; downstream <code>message</code> / <code>delta</code> / <code>stream_end</code>; upstream
          plain text or JSON with <code>content</code> / <code>text</code> / <code>message</code>.
        </p>
      </header>

      <div className="layout-main">
        <div className="layout-left">
          <section className={`panel panel--connection panel--status-${status}`}>
            <h2>Connection</h2>
            <div className="connection-form">
              <div className="connection-block connection-block--proxy">
                <label className="connection-proxy">
                  <input
                    type="checkbox"
                    checked={useDevProxy}
                    onChange={(event) => setUseDevProxy(event.target.checked)}
                  />
                  <span className="connection-proxy__body">
                    <span className="connection-proxy__title">Use Vite dev proxy</span>
                    <span className="connection-proxy__detail">
                      Path <code className="connection-inline-code">/nanobot-dev</code>
                      <span className="connection-proxy__env"> · target from </span>
                      <code className="connection-inline-code">VITE_NANOBOT_PROXY_TARGET</code>
                    </span>
                  </span>
                </label>
              </div>

              {!useDevProxy ? (
                <div className="connection-block">
                  <label className="connection-field__label" htmlFor="connection-ws-url">
                    WebSocket URL
                  </label>
                  <input
                    id="connection-ws-url"
                    className="connection-input"
                    value={directWsUrl}
                    onChange={(event) => setDirectWsUrl(event.target.value)}
                    placeholder="ws://127.0.0.1:8765/"
                    spellCheck={false}
                    autoComplete="off"
                  />
                </div>
              ) : (
                <div className="connection-block">
                  <div className="connection-field__label" id="connection-resolved-label">
                    Resolved WebSocket URL
                  </div>
                  <div
                    className="connection-url-box"
                    role="status"
                    aria-labelledby="connection-resolved-label"
                  >
                    <code className="connection-url-box__code">{resolvedWsUrl}</code>
                  </div>
                </div>
              )}

              <div
                className="connection-block connection-block--stack"
                role="group"
                aria-label="WebSocket query parameters"
              >
                <div className="connection-field">
                  <label className="connection-field__label" htmlFor="connection-client-id">
                    client_id
                  </label>
                  <input
                    id="connection-client-id"
                    className="connection-input"
                    value={clientId}
                    onChange={(event) => setClientId(event.target.value)}
                    spellCheck={false}
                    autoComplete="off"
                  />
                </div>
                <div className="connection-field">
                  <label className="connection-field__label" htmlFor="connection-token">
                    token<span className="connection-field__optional"> (optional)</span>
                  </label>
                  <input
                    id="connection-token"
                    className="connection-input"
                    value={token}
                    onChange={(event) => setToken(event.target.value)}
                    spellCheck={false}
                    autoComplete="off"
                  />
                </div>
              </div>

              <div
                className="connection-block connection-block--stack connection-block--issue"
                role="group"
                aria-label="HTTP token issuance"
              >
                <p className="connection-block__caption">Fetch token (HTTP GET)</p>
                <div className="connection-field">
                  <label className="connection-field__label" htmlFor="connection-issue-path">
                    Path
                  </label>
                  <input
                    id="connection-issue-path"
                    className="connection-input connection-input--mono"
                    value={tokenIssuePath}
                    onChange={(event) => setTokenIssuePath(event.target.value)}
                    placeholder="/auth/token"
                    spellCheck={false}
                    autoComplete="off"
                  />
                </div>
                <div className="connection-field">
                  <label className="connection-field__label" htmlFor="connection-secret">
                    X-Nanobot-Auth
                    <span className="connection-field__optional"> (optional)</span>
                  </label>
                  <input
                    id="connection-secret"
                    className="connection-input"
                    value={tokenIssueSecret}
                    onChange={(event) => setTokenIssueSecret(event.target.value)}
                    type="password"
                    autoComplete="off"
                  />
                </div>
              </div>

              <div className="connection-block connection-block--actions">
                <div className="connection-actions" role="group" aria-labelledby="connection-actions-heading">
                  <p className="connection-actions__title" id="connection-actions-heading">
                    Actions
                  </p>

                  <div className="connection-actions__ws" role="group" aria-label="WebSocket">
                    <button
                      type="button"
                      className="primary connection-actions__btn-ws"
                      onClick={connect}
                      disabled={status === "connecting"}
                    >
                      Connect
                    </button>
                    <button type="button" className="danger connection-actions__btn-ws" onClick={disconnect}>
                      Disconnect
                    </button>
                  </div>

                  <div className="connection-actions__http" role="group" aria-label="HTTP fetch token">
                    <button
                      type="button"
                      className="connection-btn-secondary connection-actions__btn-http"
                      onClick={fetchIssuedToken}
                    >
                      Fetch token
                    </button>
                  </div>

                  <div className="connection-actions__status" aria-live="polite" aria-relevant="text">
                    <div className="connection-actions__status-line">
                      <span className="connection-actions__status-label">Status</span>
                      <span className={`status-pill ${status}`}>{statusLabel}</span>
                    </div>
                    {lastError ? (
                      <p className="connection-error" role="alert">
                        {lastError}
                      </p>
                    ) : null}
                  </div>
                </div>
              </div>
            </div>
          </section>

          {readyInfo && (
            <section className="panel">
              <h2>Session</h2>
              <p className="session-inline">
                <span>
                  <strong>chat_id</strong> <code>{readyInfo.chatId}</code>
                </span>
                <span>
                  <strong>client_id</strong> <code>{readyInfo.clientId}</code>
                </span>
              </p>
            </section>
          )}

          <section className="panel">
            <h2>Send</h2>
            <div className="form-horizontal">
              <div className="field-row">
                <span className="field-row__label field-row__label--narrow">Mode</span>
                <div className="field-row__control">
                  <label className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={sendAsJson}
                      onChange={(event) => setSendAsJson(event.target.checked)}
                    />
                    Send as JSON (valid JSON; server reads content / text / message)
                  </label>
                </div>
              </div>
              <div className="field-row field-row--top">
                <span className="field-row__label">{sendAsJson ? "JSON" : "Text"}</span>
                <div className="field-row__control field-row__control--fill">
                  <textarea
                    value={sendPayload}
                    onChange={(event) => setSendPayload(event.target.value)}
                    spellCheck={false}
                  />
                </div>
                <div className="field-row__send">
                  <button type="button" className="primary" onClick={sendOutbound} disabled={status !== "open"}>
                    Send
                  </button>
                </div>
              </div>
            </div>
          </section>
        </div>

        <div className="layout-right">
          <section className="panel panel--stream">
            <h2>Streaming delta</h2>
            <div className="stream-grid">
              {Object.keys(streamChunks).length === 0 ? (
                <p className="stream-placeholder" role="status">
                  After you connect and receive downstream <code>delta</code> events, streamed text appears here.
                </p>
              ) : (
                Object.entries(streamChunks).map(([streamKey, text]) => (
                  <div key={streamKey} className="stream-panel">
                    <h3>{streamKey === "__default__" ? "Default stream" : `stream_id=${streamKey}`}</h3>
                    <div className="stream-text">{text}</div>
                  </div>
                ))
              )}
            </div>
          </section>
          <section className="panel panel--stretch">
            <div className="panel-toolbar">
              <h2>Message log</h2>
              <span className="log-toolbar-meta">
                {logs.length}
                {filteredLogs.length !== logs.length ? ` / showing ${filteredLogs.length}` : ""} entries
              </span>
            </div>
            <div className="log-toolbar-row">
              <div className="log-filter" role="group" aria-label="Log direction filter">
                {(
                  [
                    { key: "all" as const, label: "All" },
                    { key: "in" as const, label: "In" },
                    { key: "out" as const, label: "Out" },
                    { key: "system" as const, label: "System" },
                  ] as const
                ).map(({ key, label }) => (
                  <button
                    key={key}
                    type="button"
                    className={`chip ${logFilter === key ? "chip--active" : ""}`}
                    onClick={() => setLogFilter(key)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <input
                type="search"
                className="log-search"
                placeholder="Search raw text or summary…"
                value={logSearch}
                onChange={(event) => setLogSearch(event.target.value)}
                aria-label="Search logs"
              />
              <button type="button" className="toolbar-btn" onClick={clearLogs}>
                Clear
              </button>
            </div>
            <div className="log-list-wrap">
              <ul className="log-list" aria-live="polite" aria-relevant="additions">
                {filteredLogs.length === 0 && (
                  <li className="log-empty">
                    {logs.length === 0
                      ? "Messages will appear here after you connect."
                      : "No logs match the current filters."}
                  </li>
                )}
                {filteredLogs.map((entry) => (
                  <li key={entry.id} className="log-item">
                    <div className="log-meta">
                      <span className="log-time">{formatTime(entry.at)}</span>
                      <span className={`badge ${entry.direction}`}>
                        {entry.direction === "in"
                          ? "← in"
                          : entry.direction === "out"
                            ? "→ out"
                            : "sys"}
                      </span>
                      {entry.summary && <span className="log-meta__summary">{entry.summary}</span>}
                    </div>
                    <div className="log-body">
                      <JsonLogBody raw={entry.raw} />
                    </div>
                  </li>
                ))}
              </ul>
              <div ref={logScrollEndRef} className="log-scroll-anchor" aria-hidden />
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
