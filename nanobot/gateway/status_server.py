"""HTTP status server per il gateway nanobot.

Espone:
  GET  /health      — health check (no auth)
  GET  /login       — pagina di login
  POST /login       — verifica credenziali, imposta cookie di sessione
  POST /logout      — cancella la sessione
  GET  /api/status  — JSON stato completo (richiede sessione)
  GET  /dashboard   — HTML dashboard (richiede sessione)
  GET  /            — redirect a /dashboard

Credenziali configurate via env var (nessuna registrazione):
  NANOBOT_DASHBOARD_EMAIL    — email dell'unico utente
  NANOBOT_DASHBOARD_PASSWORD — password in chiaro (viene hashata in memoria)

Sessioni: token casuali 32-byte in un dizionario in-memory, TTL 12 ore.

NOTE: F821 is ignored for this file because the HTML/CSS template strings
contain '--' which ruff misparses as CSS variable references (--bg, etc.).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web
from loguru import logger

# ──────────────────────────────────────────────────────────────────────────────
# Sessioni in-memory
# ──────────────────────────────────────────────────────────────────────────────

_SESSION_TTL = 12 * 3600  # 12 ore
_sessions: dict[str, float] = {}  # token → expiry timestamp
_COOKIE = "nb_session"


def _new_session() -> str:
    token = secrets.token_hex(32)
    _sessions[token] = time.time() + _SESSION_TTL
    return token


def _valid_session(token: str | None) -> bool:
    if not token:
        return False
    exp = _sessions.get(token)
    if exp is None:
        return False
    if time.time() > exp:
        _sessions.pop(token, None)
        return False
    return True


def _revoke_session(token: str | None) -> None:
    if token:
        _sessions.pop(token, None)


def _get_session_token(request: web.Request) -> str | None:
    return request.cookies.get(_COOKIE)


def _is_authenticated(request: web.Request) -> bool:
    return _valid_session(_get_session_token(request))


def _check_credentials(request: web.Request, email: str, password: str) -> bool:
    expected_email: str = request.app["auth_email"]
    expected_hash: bytes = request.app["auth_password_hash"]
    candidate_hash = hashlib.sha256(password.encode()).digest()
    email_ok = hmac.compare_digest(email.lower().strip(), expected_email)
    pass_ok = hmac.compare_digest(candidate_hash, expected_hash)
    return email_ok and pass_ok


# ──────────────────────────────────────────────────────────────────────────────
# Log capture
# ──────────────────────────────────────────────────────────────────────────────

_RECENT_LOG_LINES: list[dict] = []
_MAX_LOG_BUFFER = 100


class _LogSink:
    def write(self, message):
        record = message.record
        lvl = record["level"].name
        if lvl in ("ERROR", "WARNING", "CRITICAL"):
            _RECENT_LOG_LINES.append({
                "time": record["time"].strftime("%H:%M:%S"),
                "level": lvl,
                "module": record["name"],
                "message": record["message"],
            })
            if len(_RECENT_LOG_LINES) > _MAX_LOG_BUFFER:
                _RECENT_LOG_LINES.pop(0)


def install_log_sink():
    logger.add(_LogSink(), format="{message}", level="WARNING")


# ──────────────────────────────────────────────────────────────────────────────
# Helpers dati
# ──────────────────────────────────────────────────────────────────────────────

def _ms_to_iso(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _ms_to_relative(ms: int | None) -> str:
    if ms is None:
        return "—"
    now = time.time() * 1000
    diff = ms - now
    abs_diff = abs(diff)
    if abs_diff < 60_000:
        label = f"{int(abs_diff/1000)}s"
    elif abs_diff < 3_600_000:
        label = f"{int(abs_diff/60_000)}m"
    elif abs_diff < 86_400_000:
        label = f"{int(abs_diff/3_600_000)}h"
    else:
        label = f"{int(abs_diff/86_400_000)}d"
    return f"tra {label}" if diff > 0 else f"{label} fa"


def _read_sessions(workspace: Path) -> list[dict]:
    sessions_dir = workspace / "sessions"
    if not sessions_dir.exists():
        return []
    result = []
    for p in sorted(sessions_dir.glob("*.jsonl")):
        try:
            lines = p.read_text(encoding="utf-8").strip().splitlines()
            size_kb = round(p.stat().st_size / 1024, 1)
            last_ts = None
            for line in reversed(lines):
                try:
                    obj = json.loads(line)
                    ts = obj.get("timestamp") or obj.get("ts") or obj.get("created_at")
                    if ts:
                        last_ts = str(ts)
                        break
                except Exception:
                    continue
            result.append({
                "name": p.stem,
                "messages": len(lines),
                "last_activity": last_ts or "—",
                "size_kb": size_kb,
            })
        except Exception:
            pass
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Route handlers
# ──────────────────────────────────────────────────────────────────────────────

async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "nanobot-gateway"})


async def handle_login_get(request: web.Request) -> web.Response:
    if _is_authenticated(request):
        raise web.HTTPFound("/dashboard")
    error = request.rel_url.query.get("error", "")
    return web.Response(text=_build_login_html(error), content_type="text/html", charset="utf-8")


async def handle_login_post(request: web.Request) -> web.Response:
    try:
        data = await request.post()
        email = str(data.get("email", ""))
        password = str(data.get("password", ""))
    except Exception:
        raise web.HTTPFound("/login?error=bad_request")

    if not _check_credentials(request, email, password):
        logger.warning("Dashboard: login fallito per email={}", email[:40])
        raise web.HTTPFound("/login?error=invalid")

    token = _new_session()
    logger.info("Dashboard: login riuscito per {}", email[:40])
    response = web.HTTPFound("/dashboard")
    response.set_cookie(
        _COOKIE, token,
        max_age=_SESSION_TTL,
        httponly=True,
        samesite="Lax",
        secure=True,
    )
    return response


async def handle_logout(request: web.Request) -> web.Response:
    token = _get_session_token(request)
    _revoke_session(token)
    response = web.HTTPFound("/login")
    response.del_cookie(_COOKIE)
    return response


async def handle_dashboard(request: web.Request) -> web.Response:
    if not _is_authenticated(request):
        raise web.HTTPFound("/login")
    return web.Response(text=_build_dashboard_html(), content_type="text/html", charset="utf-8")


async def handle_status(request: web.Request) -> web.Response:
    if not _is_authenticated(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    cron_service = request.app["cron_service"]
    workspace: Path = request.app["workspace"]

    raw_jobs = cron_service.list_jobs(include_disabled=True)
    jobs = []
    for j in raw_jobs:
        history = j.state.run_history[-5:]
        jobs.append({
            "id": j.id,
            "name": j.name,
            "enabled": j.enabled,
            "kind": j.schedule.kind,
            "expr": j.schedule.expr or j.schedule.every_ms or j.schedule.at_ms,
            "tz": j.schedule.tz,
            "next_run_iso": _ms_to_iso(j.state.next_run_at_ms),
            "next_run_rel": _ms_to_relative(j.state.next_run_at_ms),
            "last_run_iso": _ms_to_iso(j.state.last_run_at_ms),
            "last_run_rel": _ms_to_relative(j.state.last_run_at_ms),
            "last_status": j.state.last_status,
            "last_error": j.state.last_error,
            "run_count": len(j.state.run_history),
            "error_count": sum(1 for r in j.state.run_history if r.status == "error"),
            "history": [
                {
                    "run_at": _ms_to_iso(r.run_at_ms),
                    "status": r.status,
                    "duration_ms": r.duration_ms,
                    "error": r.error,
                }
                for r in history
            ],
        })

    agent_sessions = _read_sessions(workspace)
    errors = list(_RECENT_LOG_LINES[-30:])

    data = {
        "timestamp": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "api": {"ok": True, "status": "running"},
        "jobs": jobs,
        "sessions": agent_sessions,
        "recent_errors": errors,
        "summary": {
            "total_jobs": len(jobs),
            "enabled_jobs": sum(1 for j in jobs if j["enabled"]),
            "total_errors": sum(j["error_count"] for j in jobs),
            "jobs_with_errors": sum(1 for j in jobs if j["last_status"] == "error"),
            "total_sessions": len(agent_sessions),
            "total_messages": sum(s["messages"] for s in agent_sessions),
        },
    }
    return web.json_response(data)


async def handle_root(request: web.Request) -> web.Response:
    raise web.HTTPFound("/dashboard")


# ──────────────────────────────────────────────────────────────────────────────
# App factory
# ──────────────────────────────────────────────────────────────────────────────

def create_status_app(
    cron_service,
    workspace: Path,
    auth_email: str,
    auth_password: str,
    dashboard_token: str | None = None,  # ignorato, tenuto per compatibilità
) -> web.Application:
    app = web.Application()
    app["cron_service"] = cron_service
    app["workspace"] = workspace
    app["auth_email"] = auth_email.lower().strip()
    app["auth_password_hash"] = hashlib.sha256(auth_password.encode()).digest()

    app.router.add_get("/health", handle_health)
    app.router.add_get("/login", handle_login_get)
    app.router.add_post("/login", handle_login_post)
    app.router.add_post("/logout", handle_logout)
    app.router.add_get("/api/status", handle_status)
    app.router.add_get("/dashboard", handle_dashboard)
    app.router.add_get("/", handle_root)
    return app


# ──────────────────────────────────────────────────────────────────────────────
# HTML — Login
# ──────────────────────────────────────────────────────────────────────────────

def _build_login_html(error: str = "") -> str:
    error_html = ""
    if error == "invalid":
        error_html = '<p class="err-msg">Email o password non corretti.</p>'
    elif error:
        error_html = '<p class="err-msg">Errore di accesso. Riprova.</p>'

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nanobot — Accesso</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Geist+Mono:wght@400;500;600;700&family=Outfit:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root{--bg:#09090b;--surface:#18181b;--surface-alt:#27272a;--border:#3f3f46;--text:#fafafa;--muted:#71717a;--accent:#3b82f6;--red:#ef4444}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--text);font-family:'Outfit',system-ui,sans-serif;
        display:flex;align-items:center;justify-content:center;min-height:100dvh;-webkit-font-smoothing:antialiased}}
  .box{{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:40px 36px;width:360px;
        box-shadow:0 25px 50px -12px rgba(0,0,0,.5)}}
  .logo{{font-size:18px;font-weight:700;margin-bottom:6px;display:flex;align-items:center;gap:10px;letter-spacing:-.02em}}
  .logo svg{{width:22px;height:22px}}
  .sub{{color:var(--muted);font-size:13px;margin-bottom:32px}}
  label{{display:block;font-size:12px;font-weight:500;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px}}
  input{{width:100%;background:var(--bg);border:1px solid var(--border);border-radius:8px;
         color:var(--text);font-family:inherit;font-size:14px;padding:12px 14px;
         margin-bottom:20px;outline:none;transition:border-color 200ms}}
  input:focus{{border-color:var(--accent)}}
  input::placeholder{{color:#52525b}}
  button{{width:100%;background:var(--accent);border:none;border-radius:8px;color:#fff;
          cursor:pointer;font-family:inherit;font-size:14px;font-weight:600;
          padding:13px;margin-top:4px;transition:all 200ms}}
  button:hover{{background:#2563eb;transform:translateY(-1px);box-shadow:0 4px 12px rgba(59,130,246,.4)}}
  button:active{{transform:translateY(0)}}
  button:focus-visible{{outline:2px solid var(--accent);outline-offset:2px}}
  .err-msg{{color:var(--red);font-size:13px;margin-bottom:18px;
            background:rgba(239,68,68,.1);border-radius:8px;padding:12px 14px;
            display:flex;align-items:center;gap:8px}}
  .err-msg svg{{width:16px;height:16px;flex-shrink:0}}
  .footer{{margin-top:24px;text-align:center;color:var(--muted);font-size:12px}}
</style>
</head>
<body>
<div class="box">
  <div class="logo">
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
    Nanobot
  </div>
  <div class="sub">Dashboard di controllo</div>
  {error_html}
  <form method="post" action="/login">
    <label for="email">Email</label>
    <input type="email" id="email" name="email" autocomplete="email" placeholder="nome@esempio.com" required autofocus>
    <label for="password">Password</label>
    <input type="password" id="password" name="password" autocomplete="current-password" placeholder="••••••••" required>
    <button type="submit">Accedi</button>
  </form>
  <div class="footer">Nanobot Gateway v2</div>
</div>
</body>
</html>"""


# ──────────────────────────────────────────────────────────────────────────────
# HTML — Dashboard
# ──────────────────────────────────────────────────────────────────────────────

def _build_dashboard_html() -> str:
    return """<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nanobot — Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Geist+Mono:wght@400;500;600;700&family=Outfit:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root{
    --bg:#09090b;--surface:#18181b;--surface-alt:#27272a;--border:#3f3f46;
    --text:#fafafa;--muted:#a1a1aa;--dim:#52525b;
    --green:#22c55e;--green-dim:rgba(34,197,94,.12);
    --yellow:#eab308;--yellow-dim:rgba(234,179,8,.12);
    --red:#ef4444;--red-dim:rgba(239,68,68,.12);
    --accent:#3b82f6;--accent-dim:rgba(59,130,246,.12);
    --radius:10px;--radius-sm:6px;--transition:200ms cubic-bezier(.4,0,.2,1);
  }
  *{box-sizing:border-box;margin:0;padding:0}
  html{scroll-behavior:smooth}
  body{
    background:var(--bg);color:var(--text);
    font-family:'Outfit',system-ui,sans-serif;
    font-size:14px;line-height:1.5;
    -webkit-font-smoothing:antialiased;
    min-height:100dvh;
  }
  /* ── Header ── */
  header{
    background:var(--surface);
    border-bottom:1px solid var(--border);
    padding:14px 28px;
    display:flex;align-items:center;gap:14px;
    position:sticky;top:0;z-index:10;
    backdrop-filter:blur(12px);
  }
  .live-dot{
    width:8px;height:8px;border-radius:50%;
    background:var(--green);
    box-shadow:0 0 0 0 var(--green);
    animation:ping 2s cubic-bezier(0,0,.2,1) infinite;
    flex-shrink:0;
  }
  .live-dot.dead{background:var(--red);animation:none;box-shadow:none}
  @keyframes ping{
    0%{box-shadow:0 0 0 0 rgba(34,197,94,.5)}
    70%{box-shadow:0 0 0 6px rgba(34,197,94,0)}
    100%{box-shadow:0 0 0 0 rgba(34,197,94,0)}
  }
  header h1{
    font-size:15px;font-weight:600;letter-spacing:-.02em;
    display:flex;align-items:center;gap:8px;
  }
  .header-right{margin-left:auto;display:flex;align-items:center;gap:12px}
  .ts{color:var(--muted);font-size:12px;font-family:'Geist Mono',monospace}
  .btn-ghost{
    color:var(--muted);font-size:12px;font-weight:500;
    text-decoration:none;border:1px solid var(--border);
    border-radius:var(--radius-sm);padding:5px 12px;
    background:transparent;cursor:pointer;
    transition:var(--transition);
  }
  .btn-ghost:hover{color:var(--text);border-color:var(--muted);background:var(--surface-alt)}
  .btn-ghost:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
  /* ── Main layout ── */
  main{padding:24px 28px;max-width:1400px;margin:0 auto;display:grid;gap:20px}
  /* ── Summary cards ── */
  .summary-row{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}
  @media(max-width:900px){.summary-row{grid-template-columns:repeat(3,1fr)}}
  @media(max-width:600px){.summary-row{grid-template-columns:repeat(2,1fr)}}
  .card{
    background:var(--surface);
    border:1px solid var(--border);
    border-radius:var(--radius);
    padding:18px 20px;
    transition:var(--transition);
    position:relative;overflow:hidden;
  }
  .card::before{
    content:'';position:absolute;inset:0;
    background:linear-gradient(135deg,rgba(255,255,255,.02) 0%,transparent 60%);
    pointer-events:none;
  }
  .card:hover{border-color:var(--dim);transform:translateY(-1px)}
  .card-title{
    color:var(--muted);font-size:11px;font-weight:500;
    text-transform:uppercase;letter-spacing:.06em;
    margin-bottom:10px;
  }
  .card-value{
    font-size:30px;font-weight:700;letter-spacing:-.03em;
    font-family:'Geist Mono',monospace;line-height:1;
  }
  .card-sub{color:var(--dim);font-size:11px;margin-top:4px;font-family:'Geist Mono',monospace}
  .card.ok .card-value{color:var(--green)}
  .card.err .card-value{color:var(--red)}
  .card.warn .card-value{color:var(--yellow)}
  /* ── Section panels ── */
  .section{
    background:var(--surface);
    border:1px solid var(--border);
    border-radius:var(--radius);
    overflow:hidden;
  }
  .section-header{
    padding:14px 20px;
    border-bottom:1px solid var(--border);
    font-weight:600;font-size:13px;
    display:flex;align-items:center;gap:8px;
    background:var(--bg);
  }
  .section-header svg{width:16px;height:16px;opacity:.6}
  .grid-2col{display:grid;grid-template-columns:1fr 1fr;gap:20px}
  @media(max-width:800px){.grid-2col{grid-template-columns:1fr}}
  /* ── Tables ── */
  table{width:100%;border-collapse:collapse}
  th{
    padding:10px 20px;text-align:left;
    color:var(--muted);font-size:11px;font-weight:500;
    text-transform:uppercase;letter-spacing:.06em;
    border-bottom:1px solid var(--border);
    background:var(--bg);white-space:nowrap;
  }
  td{
    padding:12px 20px;border-bottom:1px solid var(--border);
    vertical-align:top;transition:var(--transition);
  }
  tr:last-child td{border-bottom:none}
  tbody tr:hover td{background:rgba(255,255,255,.02)}
  /* ── Badges ── */
  .badge{
    display:inline-flex;align-items:center;gap:4px;
    padding:3px 9px;border-radius:20px;
    font-size:11px;font-weight:600;letter-spacing:.02em;
  }
  .b-ok{background:var(--green-dim);color:var(--green)}
  .b-err{background:var(--red-dim);color:var(--red)}
  .b-idle{background:rgba(161,161,170,.1);color:var(--muted)}
  .b-off{background:rgba(161,161,170,.1);color:var(--dim)}
  /* ── History dots ── */
  .hdot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:2px;flex-shrink:0}
  .h-ok{background:var(--green)}.h-err{background:var(--red)}.h-skip{background:var(--dim)}
  .history-cell{display:flex;align-items:center;flex-wrap:wrap;gap:2px}
  .run-count{color:var(--dim);font-size:10px;margin-left:6px;font-family:'Geist Mono',monospace}
  /* ── Error log ── */
  .err-line{
    font-size:12px;padding:10px 20px;
    border-bottom:1px solid rgba(63,63,70,.5);
    word-break:break-all;display:flex;align-items:flex-start;gap:10px;
    transition:var(--transition);
  }
  .err-line:last-child{border-bottom:none}
  .err-line:hover{background:rgba(255,255,255,.02)}
  .err-line.WARNING{color:var(--yellow)}
  .err-line.ERROR,.err-line.CRITICAL{color:var(--red)}
  .err-time{color:var(--dim);font-size:11px;font-family:'Geist Mono',monospace;flex-shrink:0;min-width:60px}
  .err-src{color:var(--accent);font-size:11px;font-family:'Geist Mono',monospace;flex-shrink:0}
  .err-msg{flex:1;color:var(--text);opacity:.85}
  /* ── Job row extras ── */
  .job-error{color:var(--red);font-size:10px;margin-top:4px;font-family:'Geist Mono',monospace;
             display:block;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .job-schedule{color:var(--muted);font-size:12px;font-family:'Geist Mono',monospace}
  .job-time{font-size:11px;color:var(--muted);font-family:'Geist Mono',monospace}
  .job-time-main{font-size:12px}
  .job-name{font-weight:600;font-size:13px}
  .badge-wrap{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
  /* ── Empty states ── */
  .empty{
    padding:32px 20px;color:var(--dim);text-align:center;font-size:12px;
    display:flex;flex-direction:column;align-items:center;gap:8px;
  }
  .empty svg{width:32px;height:32px;opacity:.3}
  .empty-ok{color:var(--green);font-size:13px;font-weight:500}
  /* ── Loading state ── */
  #loading-bar{
    position:fixed;top:0;left:0;height:2px;width:0%;
    background:var(--accent);z-index:100;
    transition:width 150ms ease-out;
  }
  #loading-bar.active{width:60%;transition:width 800ms ease-out}
  /* ── Focus ── */
  :focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:4px}
  /* ── Scrollbar ── */
  ::-webkit-scrollbar{width:6px;height:6px}
  ::-webkit-scrollbar-track{background:transparent}
  ::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
  ::-webkit-scrollbar-thumb:hover{background:var(--dim)}
</style>
</head>
<body>
<div id="loading-bar"></div>
<header>
  <div class="live-dot" id="live-dot"></div>
  <h1>
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
    Nanobot Gateway
  </h1>
  <div class="header-right">
    <span class="ts" id="last-update">—</span>
    <form method="post" action="/logout" style="margin:0">
      <button type="submit" class="btn-ghost">Esci</button>
    </form>
  </div>
</header>
<main>
  <div class="summary-row" id="summary-row"></div>
  <div class="section">
    <div class="section-header">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
      Cron Jobs
    </div>
    <div id="jobs-body"></div>
  </div>
  <div class="grid-2col">
    <div class="section">
      <div class="section-header">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        Sessioni
      </div>
      <div id="sessions-body"></div>
    </div>
    <div class="section">
      <div class="section-header">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
        Log Errori
      </div>
      <div id="errors-body"></div>
    </div>
  </div>
</main>
<script>
const loadingBar=document.getElementById('loading-bar');
function showLoading(){loadingBar.classList.add('active')}
function hideLoading(){loadingBar.classList.remove('active');loadingBar.style.width='100%';setTimeout(()=>loadingBar.style.width='0%',200)}

function badge(s){
  if(!s)return'<span class="badge b-idle">mai eseguito</span>';
  if(s==='ok')return'<span class="badge b-ok">✓ ok</span>';
  if(s==='error')return'<span class="badge b-err">✗ errore</span>';
  return'<span class="badge b-idle">'+s+'</span>';
}
function hdots(h){
  return(h||[]).map(r=>{
    const c=r.status==='ok'?'h-ok':r.status==='error'?'h-err':'h-skip';
    return'<span class="hdot '+c+'" title="'+(r.run_at||'')+(r.error?' — '+r.error:'')+'"></span>';
  }).join('');
}
function render(d){
  hideLoading();
  document.getElementById('live-dot').className='live-dot'+(d.api.ok?'':' dead');
  document.getElementById('last-update').textContent=d.timestamp;
  const s=d.summary;
  document.getElementById('summary-row').innerHTML=[
    {l:'Jobs attivi',v:s.enabled_jobs+'/'+s.total_jobs,c:'ok',sub:'abilitati'},
    {l:'Errori',v:s.total_errors,c:s.total_errors>0?'err':'ok',sub:s.total_errors>0?'da risolvere':'nessuno'},
    {l:'Sessioni',v:s.total_sessions,c:'ok',sub:'attive'},
    {l:'Messaggi',v:s.total_messages,c:'ok',sub:'totale'},
    {l:'Warnings',v:d.recent_errors.length,c:d.recent_errors.length>0?'warn':'ok',sub:d.recent_errors.length>0?'log recenti':'nessuno'},
  ].map(c=>'<div class="card '+c.c+'"><div class="card-title">'+c.l+'</div><div class="card-value">'+c.v+'</div><div class="card-sub">'+c.sub+'</div></div>').join('');

  const jb=document.getElementById('jobs-body');
  if(!d.jobs.length){jb.innerHTML='<div class="empty"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>Nessun job schedulato</div>';}
  else{
    jb.innerHTML='<table><thead><tr><th>Nome</th><th>Stato</th><th>Schedule</th><th>Prossima</th><th>Ultima</th><th>Storia</th></tr></thead><tbody>'+
    d.jobs.map(j=>{
      const dis=j.enabled?'':'<span class="badge b-off" style="margin-left:6px">off</span>';
      const sch=j.kind==='cron'?(j.expr+(j.tz?' '+j.tz:''))
               :j.kind==='every'?'ogni '+Math.round(j.expr/60000)+'m'
               :j.kind==='at'?'una volta':j.kind||'—';
      const err=j.last_error?'<span class="job-error" title="'+j.last_error.replace(/"/g,'&quot;')+'">'+j.last_error.substring(0,60)+'</span>':'';
      return'<tr>'+
        '<td><div class="job-name">'+j.name+'</div>'+dis+'</td>'+
        '<td><div class="badge-wrap">'+badge(j.last_status)+err+'</div></td>'+
        '<td><span class="job-schedule">'+sch+'</span></td>'+
        '<td><div class="job-time-main">'+(j.next_run_rel||'—')+'</div><div class="job-time">'+(j.next_run_iso||'')+'</div></td>'+
        '<td><div class="job-time-main">'+(j.last_run_rel||'—')+'</div><div class="job-time">'+(j.last_run_iso||'')+'</div></td>'+
        '<td><div class="history-cell">'+hdots(j.history)+(j.run_count?'<span class="run-count">'+j.run_count+'</span>':'')+'</div></td>'+
      '</tr>';
    }).join('')+'</tbody></table>';
  }

  const sb=document.getElementById('sessions-body');
  if(!d.sessions.length){sb.innerHTML='<div class="empty"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>Nessuna sessione</div>';}
  else{
    sb.innerHTML='<table><thead><tr><th>Sessione</th><th>Msg</th><th>Ultima attività</th></tr></thead><tbody>'+
    d.sessions.map(s=>'<tr><td>'+s.name+'</td><td>'+s.messages+'</td><td style="color:var(--muted);font-size:11px;font-family:\'Geist Mono\',monospace">'+s.last_activity+'</td></tr>').join('')+'</tbody></table>';
  }

  const eb=document.getElementById('errors-body');
  if(!d.recent_errors.length){eb.innerHTML='<div class="empty"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><polyline points="20 6 9 17 4 12"/></svg><span class="empty-ok">✓ Nessun errore recente</span></div>';}
  else{
    eb.innerHTML=d.recent_errors.slice().reverse().slice(0,25).map(e=>
      '<div class="err-line '+e.level+'"><span class="err-time">'+e.time+'</span><span class="err-src">'+e.module+'</span><span class="err-msg">'+e.message.substring(0,140)+'</span></div>'
    ).join('');
  }
}
async function refresh(){
  showLoading();
  const r=await fetch('/api/status');
  if(r.status===401){window.location='/login';return;}
  if(r.ok){const d=await r.json();render(d);}
  else{document.getElementById('live-dot').className='live-dot dead';hideLoading();}
}
showLoading();refresh();setInterval(refresh,5000);
</script>
</body>
</html>"""
