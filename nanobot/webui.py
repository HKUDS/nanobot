"""Web UI setup wizard and control plane for nanobot."""

from __future__ import annotations

import json
import secrets
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from nanobot.config.loader import get_config_path, load_config, save_config
from nanobot.config.schema import Config
from nanobot.utils.helpers import sync_workspace_templates


@dataclass
class GatewayManager:
    """Manage a gateway subprocess and keep a bounded log buffer."""

    process: subprocess.Popen[str] | None = None
    log_lines: deque[str] = field(default_factory=lambda: deque(maxlen=600))
    lock: threading.Lock = field(default_factory=threading.Lock)
    gateway_port: int = 18790
    started_at: float | None = None

    def status(self) -> dict[str, Any]:
        with self.lock:
            running = self.process is not None and self.process.poll() is None
            return {
                "running": running,
                "pid": self.process.pid if running and self.process else None,
                "gatewayPort": self.gateway_port,
                "startedAt": self.started_at,
            }

    def logs(self) -> list[str]:
        with self.lock:
            return list(self.log_lines)

    def _append_log(self, line: str) -> None:
        with self.lock:
            self.log_lines.append(line.rstrip("\n"))

    def _drain_logs(self, proc: subprocess.Popen[str]) -> None:
        if proc.stdout is None:
            return

        try:
            for line in proc.stdout:
                self._append_log(line)
        except Exception as exc:
            self._append_log(f"[webui] log stream error: {exc}")

        rc = proc.wait()
        self._append_log(f"[webui] gateway exited with code {rc}")

        with self.lock:
            if self.process is proc:
                self.process = None
                self.started_at = None

    def start(self, port: int, verbose: bool = False) -> dict[str, Any]:
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                return self.status()

            self.gateway_port = int(port)
            cmd = [
                sys.executable,
                "-m",
                "nanobot.cli.commands",
                "gateway",
                "--port",
                str(self.gateway_port),
            ]
            if verbose:
                cmd.append("--verbose")

            self._append_log("[webui] starting gateway...")
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            self.process = proc
            self.started_at = time.time()

            t = threading.Thread(target=self._drain_logs, args=(proc,), daemon=True)
            t.start()

        return self.status()

    def stop(self, timeout_s: float = 10.0) -> dict[str, Any]:
        with self.lock:
            proc = self.process

        if proc is None or proc.poll() is not None:
            with self.lock:
                self.process = None
                self.started_at = None
            return self.status()

        self._append_log("[webui] stopping gateway...")
        proc.terminate()

        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            self._append_log("[webui] gateway did not stop in time, killing process")
            proc.kill()
            proc.wait(timeout=5)

        with self.lock:
            if self.process is proc:
                self.process = None
                self.started_at = None

        return self.status()


def _parse_csv_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _load_or_default_config() -> Config:
    path = get_config_path()
    if path.exists():
        return load_config(path)
    return Config()


def _run_onboard() -> dict[str, Any]:
    path = get_config_path()
    existed = path.exists()

    cfg = load_config(path) if existed else Config()
    save_config(cfg, path)

    workspace = cfg.workspace_path
    workspace.mkdir(parents=True, exist_ok=True)
    sync_workspace_templates(workspace)

    return {
        "configPath": str(path),
        "workspace": str(workspace),
        "created": not existed,
    }


def _apply_wizard_payload(payload: dict[str, Any]) -> Config:
    cfg = _load_or_default_config()

    provider = str(payload.get("provider") or cfg.agents.defaults.provider).strip().replace("-", "_")
    model = str(payload.get("model") or cfg.agents.defaults.model).strip()
    api_key = str(payload.get("api_key") or "").strip()
    api_base = str(payload.get("api_base") or "").strip()
    brave_key = str(payload.get("brave_api_key") or "").strip()

    if provider:
        cfg.agents.defaults.provider = provider
    if model:
        cfg.agents.defaults.model = model

    selected_provider = getattr(cfg.providers, provider, None)
    if selected_provider is not None:
        if api_key:
            selected_provider.api_key = api_key
        if api_base:
            selected_provider.api_base = api_base

    if "restrict_to_workspace" in payload:
        cfg.tools.restrict_to_workspace = bool(payload.get("restrict_to_workspace"))

    if brave_key:
        cfg.tools.web.search.api_key = brave_key

    channels = payload.get("channels") if isinstance(payload.get("channels"), dict) else {}

    telegram = channels.get("telegram") if isinstance(channels, dict) else None
    if isinstance(telegram, dict):
        if "enabled" in telegram:
            cfg.channels.telegram.enabled = bool(telegram.get("enabled"))
        token = str(telegram.get("token") or "").strip()
        if token:
            cfg.channels.telegram.token = token
        if "allow_from" in telegram:
            cfg.channels.telegram.allow_from = _parse_csv_list(telegram.get("allow_from"))

    discord = channels.get("discord") if isinstance(channels, dict) else None
    if isinstance(discord, dict):
        if "enabled" in discord:
            cfg.channels.discord.enabled = bool(discord.get("enabled"))
        token = str(discord.get("token") or "").strip()
        if token:
            cfg.channels.discord.token = token
        if "allow_from" in discord:
            cfg.channels.discord.allow_from = _parse_csv_list(discord.get("allow_from"))

    slack = channels.get("slack") if isinstance(channels, dict) else None
    if isinstance(slack, dict):
        if "enabled" in slack:
            cfg.channels.slack.enabled = bool(slack.get("enabled"))
        bot_token = str(slack.get("bot_token") or "").strip()
        app_token = str(slack.get("app_token") or "").strip()
        if bot_token:
            cfg.channels.slack.bot_token = bot_token
        if app_token:
            cfg.channels.slack.app_token = app_token
        if "allow_from" in slack:
            cfg.channels.slack.allow_from = _parse_csv_list(slack.get("allow_from"))

    save_config(cfg)
    sync_workspace_templates(cfg.workspace_path)
    return cfg


def _extract_token(handler: BaseHTTPRequestHandler) -> str:
    parsed = urlparse(handler.path)
    query = parse_qs(parsed.query)
    if "token" in query and query["token"]:
        return query["token"][0]
    return handler.headers.get("X-Nanobot-Token", "")


def _make_handler(manager: GatewayManager, access_token: str | None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "NanobotWebUI/1.0"

        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def _ok(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _text(self, content: str, status: int = HTTPStatus.OK) -> None:
            raw = content.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                return {}
            data = self.rfile.read(length)
            if not data:
                return {}
            try:
                payload = json.loads(data.decode("utf-8"))
            except Exception as exc:
                raise ValueError(f"Invalid JSON body: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
            return payload

        def _is_authorized(self) -> bool:
            if not access_token:
                return True
            return _extract_token(self) == access_token

        def _auth_guard(self) -> bool:
            if self._is_authorized():
                return True
            self._ok({"ok": False, "error": "Unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return False

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path

            if path == "/" or path == "/index.html":
                self._text(_html_page())
                return

            if path == "/api/health":
                self._ok({"ok": True, "status": "healthy"})
                return

            if path == "/api/status":
                if not self._auth_guard():
                    return
                cfg = _load_or_default_config()
                cfg_path = get_config_path()
                self._ok(
                    {
                        "ok": True,
                        "configPath": str(cfg_path),
                        "configExists": cfg_path.exists(),
                        "workspace": str(cfg.workspace_path),
                        "workspaceExists": cfg.workspace_path.exists(),
                        "gateway": manager.status(),
                        "authEnabled": bool(access_token),
                    }
                )
                return

            if path == "/api/config":
                if not self._auth_guard():
                    return
                cfg = _load_or_default_config()
                self._ok(
                    {
                        "ok": True,
                        "config": cfg.model_dump(by_alias=True),
                        "configPath": str(get_config_path()),
                    }
                )
                return

            if path == "/api/gateway/logs":
                if not self._auth_guard():
                    return
                self._ok({"ok": True, "lines": manager.logs()})
                return

            self._ok({"ok": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path

            if path.startswith("/api/") and not self._auth_guard():
                return

            try:
                payload = self._read_json()
            except ValueError as exc:
                self._ok({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return

            if path == "/api/onboard":
                info = _run_onboard()
                self._ok({"ok": True, **info})
                return

            if path == "/api/wizard":
                try:
                    cfg = _apply_wizard_payload(payload)
                except Exception as exc:
                    self._ok(
                        {"ok": False, "error": f"Failed to apply wizard data: {exc}"},
                        HTTPStatus.BAD_REQUEST,
                    )
                    return

                self._ok(
                    {
                        "ok": True,
                        "message": "Wizard settings saved",
                        "config": cfg.model_dump(by_alias=True),
                    }
                )
                return

            if path == "/api/config":
                incoming = payload.get("config", payload)
                try:
                    cfg = Config.model_validate(incoming)
                    save_config(cfg)
                    sync_workspace_templates(cfg.workspace_path)
                except Exception as exc:
                    self._ok(
                        {"ok": False, "error": f"Config validation failed: {exc}"},
                        HTTPStatus.BAD_REQUEST,
                    )
                    return

                self._ok({"ok": True, "message": "Config saved"})
                return

            if path == "/api/gateway/start":
                port = int(payload.get("port") or 18790)
                verbose = bool(payload.get("verbose"))
                status = manager.start(port=port, verbose=verbose)
                self._ok({"ok": True, "gateway": status})
                return

            if path == "/api/gateway/stop":
                status = manager.stop()
                self._ok({"ok": True, "gateway": status})
                return

            self._ok({"ok": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)

    return Handler


def run_webui(
    host: str,
    port: int,
    with_gateway: bool,
    gateway_port: int,
    gateway_verbose: bool,
    auth_enabled: bool,
    access_token: str | None,
) -> None:
    """Run the nanobot setup web UI server."""

    if auth_enabled:
        token = access_token or secrets.token_urlsafe(18)
    else:
        token = None

    manager = GatewayManager(gateway_port=gateway_port)
    if with_gateway:
        try:
            manager.start(port=gateway_port, verbose=gateway_verbose)
        except Exception as exc:
            manager._append_log(f"[webui] failed to start gateway: {exc}")

    handler = _make_handler(manager, token)
    server = ThreadingHTTPServer((host, port), handler)

    print(f"nanobot webui listening on http://{host}:{port}")
    if token:
        print("nanobot webui auth is enabled")
        print(f"nanobot webui token: {token}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        manager.stop()
        server.server_close()


def _html_page() -> str:
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>nanobot control plane</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');
    :root { --ink:#102a43; --paper:#f6fbff; --teal:#0a9396; --gold:#ee9b00; --danger:#b42318; --line:#d9e2ec; --card:rgba(255,255,255,.94); }
    * { box-sizing:border-box; }
    body { margin:0; font-family:'Space Grotesk','Segoe UI',sans-serif; color:var(--ink); background:radial-gradient(circle at 10% 15%, rgba(10,147,150,.22), transparent 40%),radial-gradient(circle at 90% 20%, rgba(238,155,0,.2), transparent 32%),#f3f9ff; min-height:100vh; }
    header,main { max-width:1180px; margin:0 auto; padding:18px 20px; }
    h1 { margin:0; font-size:2rem; }
    .sub { color:#486581; margin:6px 0 0; }
    .auth { display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; align-items:center; }
    .grid { display:grid; grid-template-columns:repeat(12,minmax(0,1fr)); gap:14px; }
    .card { background:var(--card); border:1px solid var(--line); border-radius:14px; box-shadow:0 8px 22px rgba(16,42,67,.08); padding:14px; }
    .s7 { grid-column:span 7; } .s5 { grid-column:span 5; } .s12 { grid-column:span 12; }
    .row { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:10px; }
    label { font-size:.8rem; text-transform:uppercase; letter-spacing:.06em; color:#486581; display:block; margin-bottom:4px; }
    input,select,textarea { width:100%; border:1px solid #bcccdc; border-radius:10px; padding:10px; font:inherit; color:var(--ink); background:#fff; }
    textarea { min-height:300px; resize:vertical; font-family:'IBM Plex Mono',ui-monospace,monospace; font-size:.86rem; line-height:1.45; }
    .checks { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:10px; }
    .check { display:flex; gap:8px; align-items:center; border:1px solid var(--line); border-radius:10px; padding:8px; background:#fff; }
    .check input { width:auto; margin:0; }
    .actions { display:flex; flex-wrap:wrap; gap:8px; margin-top:8px; }
    button { border:0; border-radius:10px; padding:10px 14px; color:#fff; background:var(--teal); font-weight:600; cursor:pointer; }
    button.alt { background:#1f3a5f; } button.warn { background:var(--danger); }
    .status { margin-top:8px; color:#334e68; font-size:.92rem; }
    .pill { border:1px solid #bcccdc; background:#fff; border-radius:999px; padding:4px 10px; font-size:.78rem; font-weight:600; display:inline-flex; gap:6px; align-items:center; }
    .dot { width:8px; height:8px; border-radius:999px; background:#7b8794; }
    .dot.ok { background:#2f855a; box-shadow:0 0 0 5px rgba(47,133,90,.18); }
    pre { margin:8px 0 0; max-height:360px; min-height:220px; overflow:auto; border-radius:10px; border:1px solid #243b53; padding:10px; background:#102a43; color:#f4f8ff; font-family:'IBM Plex Mono',ui-monospace,monospace; font-size:.82rem; line-height:1.4; }
    @media (max-width:980px){ .s7,.s5,.s12{grid-column:span 12;} .row,.checks{grid-template-columns:1fr;} }
  </style>
</head>
<body>
  <header>
    <h1>nanobot control plane</h1>
    <p class="sub">Setup wizard, full config editor, and gateway controls in one page.</p>
    <div class="auth">
      <input id="tokenInput" type="password" placeholder="Web UI token" style="max-width:300px" />
      <button onclick="saveToken()">Use token</button>
      <span class="pill"><span id="gatewayDot" class="dot"></span><span id="gatewayText">gateway unknown</span></span>
    </div>
    <div id="topStatus" class="status"></div>
  </header>

  <main class="grid">
    <section class="card s7">
      <h2>Setup wizard</h2>
      <div class="row">
        <div>
          <label>Provider</label>
          <select id="provider">
            <option value="openrouter">OpenRouter</option>
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic</option>
            <option value="deepseek">DeepSeek</option>
            <option value="groq">Groq</option>
            <option value="custom">Custom</option>
          </select>
        </div>
        <div>
          <label>Model</label>
          <input id="model" placeholder="anthropic/claude-opus-4-5" />
        </div>
      </div>
      <div class="row">
        <div><label>Provider API key</label><input id="apiKey" type="password" /></div>
        <div><label>Provider API base (optional)</label><input id="apiBase" placeholder="https://api.example.com/v1" /></div>
      </div>
      <div class="row">
        <div><label>Brave Search key (optional)</label><input id="braveKey" type="password" /></div>
        <div><label>Gateway internal port</label><input id="gatewayPort" type="number" value="18790" min="1" max="65535" /></div>
      </div>
      <div class="checks">
        <label class="check"><input id="restrictWorkspace" type="checkbox" /> Restrict tools to workspace</label>
        <label class="check"><input id="telegramEnabled" type="checkbox" /> Enable Telegram</label>
        <label class="check"><input id="discordEnabled" type="checkbox" /> Enable Discord</label>
        <label class="check"><input id="slackEnabled" type="checkbox" /> Enable Slack</label>
      </div>
      <div class="row">
        <div><label>Telegram token</label><input id="telegramToken" type="password" /></div>
        <div><label>Telegram allowFrom (csv)</label><input id="telegramAllowFrom" /></div>
      </div>
      <div class="row">
        <div><label>Discord token</label><input id="discordToken" type="password" /></div>
        <div><label>Discord allowFrom (csv)</label><input id="discordAllowFrom" /></div>
      </div>
      <div class="row">
        <div><label>Slack bot token</label><input id="slackBotToken" type="password" /></div>
        <div><label>Slack app token</label><input id="slackAppToken" type="password" /></div>
      </div>
      <div class="actions">
        <button onclick="runOnboard()">Initialize files</button>
        <button class="alt" onclick="saveWizard()">Save wizard settings</button>
        <button class="alt" onclick="loadConfig()">Reload from disk</button>
      </div>
      <div id="wizardStatus" class="status"></div>
    </section>

    <section class="card s5">
      <h2>Gateway control</h2>
      <div class="actions">
        <button onclick="startGateway()">Start gateway</button>
        <button class="warn" onclick="stopGateway()">Stop gateway</button>
        <button class="alt" onclick="refreshGatewayLogs()">Refresh logs</button>
      </div>
      <div id="gatewayStatus" class="status"></div>
      <pre id="gatewayLogs">No logs yet.</pre>
    </section>

    <section class="card s12">
      <h2>Full config JSON</h2>
      <textarea id="configEditor" spellcheck="false"></textarea>
      <div class="actions">
        <button class="alt" onclick="loadConfig()">Load JSON</button>
        <button onclick="saveJsonConfig()">Save JSON</button>
      </div>
      <div id="jsonStatus" class="status"></div>
    </section>
  </main>

  <script>
    const tokenKey = 'nanobot_webui_token';
    const q = (id) => document.getElementById(id);
    const getToken = () => localStorage.getItem(tokenKey) || '';

    function saveToken() {
      localStorage.setItem(tokenKey, q('tokenInput').value.trim());
      setTopStatus('Token saved. Refreshing...', false);
      loadConfig(); refreshStatus(); refreshGatewayLogs();
    }

    function api(path, options = {}) {
      const headers = Object.assign({}, options.headers || {}, { 'Content-Type': 'application/json' });
      const t = getToken(); if (t) headers['X-Nanobot-Token'] = t;
      return fetch(path, Object.assign({}, options, { headers }));
    }

    async function parse(resp) {
      let data = {}; try { data = await resp.json(); } catch (_e) { data = {}; }
      if (!resp.ok || data.ok === false) throw new Error(data.error || `HTTP ${resp.status}`);
      return data;
    }

    const setMsg = (id, msg, err=false) => { const el=q(id); el.style.color = err ? '#b42318' : '#334e68'; el.textContent = msg; };
    const setTopStatus = (m,e)=>setMsg('topStatus',m,e);
    const setWizardStatus = (m,e)=>setMsg('wizardStatus',m,e);
    const setGatewayStatus = (m,e)=>setMsg('gatewayStatus',m,e);
    const setJsonStatus = (m,e)=>setMsg('jsonStatus',m,e);
    const setInput = (id,v) => { q(id).value = v == null ? '' : String(v); };
    const setCheck = (id,v) => { q(id).checked = !!v; };
    const csv = (arr) => Array.isArray(arr) ? arr.join(',') : '';

    function gatewayPill(running) {
      q('gatewayDot').className = running ? 'dot ok' : 'dot';
      q('gatewayText').textContent = running ? 'gateway running' : 'gateway stopped';
    }

    async function refreshStatus() {
      try {
        const d = await parse(await api('/api/status'));
        const g = d.gateway || {};
        gatewayPill(!!g.running);
        setTopStatus(`Config: ${d.configPath} | Workspace: ${d.workspace} | Auth: ${d.authEnabled ? 'on' : 'off'}`, false);
        setGatewayStatus(`running=${!!g.running} pid=${g.pid || '-'} port=${g.gatewayPort || '-'}`, false);
      } catch (e) { gatewayPill(false); setTopStatus(e.message, true); }
    }

    function fill(cfg) {
      const defs = (cfg.agents || {}).defaults || {};
      const providers = cfg.providers || {};
      const channels = cfg.channels || {};

      setInput('provider', defs.provider || 'openrouter');
      setInput('model', defs.model || 'anthropic/claude-opus-4-5');
      setInput('braveKey', ((((cfg.tools||{}).web||{}).search||{}).apiKey || ''));
      setCheck('restrictWorkspace', !!((cfg.tools||{}).restrictToWorkspace));

      const pn = (defs.provider || 'openrouter').replace('-', '_');
      const p = providers[pn] || {};
      setInput('apiBase', p.apiBase || '');

      const tg = channels.telegram || {};
      setCheck('telegramEnabled', !!tg.enabled);
      setInput('telegramAllowFrom', csv(tg.allowFrom));

      const dc = channels.discord || {};
      setCheck('discordEnabled', !!dc.enabled);
      setInput('discordAllowFrom', csv(dc.allowFrom));

      const sl = channels.slack || {};
      setCheck('slackEnabled', !!sl.enabled);

      setInput('configEditor', JSON.stringify(cfg, null, 2));
    }

    async function loadConfig() {
      try {
        const d = await parse(await api('/api/config'));
        fill(d.config || {});
        setWizardStatus('Config loaded', false);
        setJsonStatus('Config loaded', false);
      } catch (e) {
        setWizardStatus(e.message, true);
        setJsonStatus(e.message, true);
      }
    }
    async function runOnboard() {
      try {
        const d = await parse(await api('/api/onboard', { method:'POST', body:'{}' }));
        setWizardStatus(`Onboard complete: ${d.created ? 'created' : 'refreshed'} config at ${d.configPath}`, false);
        await loadConfig(); await refreshStatus();
      } catch (e) { setWizardStatus(e.message, true); }
    }

    function wizardPayload() {
      return {
        provider: q('provider').value.trim(),
        model: q('model').value.trim(),
        api_key: q('apiKey').value.trim(),
        api_base: q('apiBase').value.trim(),
        brave_api_key: q('braveKey').value.trim(),
        restrict_to_workspace: q('restrictWorkspace').checked,
        channels: {
          telegram: {
            enabled: q('telegramEnabled').checked,
            token: q('telegramToken').value.trim(),
            allow_from: q('telegramAllowFrom').value.trim(),
          },
          discord: {
            enabled: q('discordEnabled').checked,
            token: q('discordToken').value.trim(),
            allow_from: q('discordAllowFrom').value.trim(),
          },
          slack: {
            enabled: q('slackEnabled').checked,
            bot_token: q('slackBotToken').value.trim(),
            app_token: q('slackAppToken').value.trim(),
          },
        },
      };
    }

    async function saveWizard() {
      try {
        await parse(await api('/api/wizard', { method:'POST', body: JSON.stringify(wizardPayload()) }));
        setWizardStatus('Wizard settings saved', false);
        await loadConfig(); await refreshStatus();
      } catch (e) { setWizardStatus(e.message, true); }
    }

    async function saveJsonConfig() {
      try {
        const parsed = JSON.parse(q('configEditor').value);
        await parse(await api('/api/config', { method:'POST', body: JSON.stringify({ config: parsed }) }));
        setJsonStatus('Config saved', false);
        await refreshStatus();
      } catch (e) { setJsonStatus(e.message, true); }
    }

    async function startGateway() {
      try {
        const port = parseInt(q('gatewayPort').value || '18790', 10);
        await parse(await api('/api/gateway/start', { method:'POST', body: JSON.stringify({ port }) }));
        setGatewayStatus('Gateway start requested', false);
        await refreshStatus(); await refreshGatewayLogs();
      } catch (e) { setGatewayStatus(e.message, true); }
    }

    async function stopGateway() {
      try {
        await parse(await api('/api/gateway/stop', { method:'POST', body:'{}' }));
        setGatewayStatus('Gateway stop requested', false);
        await refreshStatus(); await refreshGatewayLogs();
      } catch (e) { setGatewayStatus(e.message, true); }
    }

    async function refreshGatewayLogs() {
      try {
        const d = await parse(await api('/api/gateway/logs'));
        const lines = d.lines || [];
        q('gatewayLogs').textContent = lines.length ? lines.join('\n') : 'No logs yet.';
      } catch (e) {
        q('gatewayLogs').textContent = e.message;
      }
    }

    async function boot() {
      const t = getToken(); if (t) q('tokenInput').value = t;
      await refreshStatus(); await loadConfig(); await refreshGatewayLogs();
      setInterval(refreshStatus, 3000);
      setInterval(refreshGatewayLogs, 3000);
    }

    window.addEventListener('load', boot);
  </script>
</body>
</html>
"""
