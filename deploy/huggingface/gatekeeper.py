#!/usr/bin/env python3
"""
Gatekeeper v5.0 (DLQ Replay) — HTTP proxy + WS interceptor + squad relay.
Deployed on ws_port, serves WebUI and routes squad traffic.
"""

import datetime
import json
import os
import re
import sys
import time
import asyncio
from uuid import uuid4
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from authlib.integrations.starlette_client import OAuth
import websockets

# ═══════════════════════════════════════════════════════════════
# Logging
# ═══════════════════════════════════════════════════════════════

def log(msg):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[GATEKEEPER] [{timestamp}] {msg}")
    sys.stdout.flush()

# ═══════════════════════════════════════════════════════════════
# Squad Config (memory-parsed, zero disk I/O)
# ═══════════════════════════════════════════════════════════════

AGENT_NAMES: list[str] = []
SQUAD_ROSTER: dict[str, dict] = {}
INSTANCE_WORKSPACES: dict[str, str] = {}
PEER_ENV_MAP: dict[str, str] = {}  # NANOBOT_PEER_NEO → env var value

def refresh_roster():
    """Parse NANOBOT_PEER_* env vars to build agent roster."""
    global AGENT_NAMES, SQUAD_ROSTER, INSTANCE_WORKSPACES, PEER_ENV_MAP
    AGENT_NAMES.clear()
    SQUAD_ROSTER.clear()
    INSTANCE_WORKSPACES.clear()
    PEER_ENV_MAP.clear()

    for key, val in os.environ.items():
        if not key.startswith("NANOBOT_PEER_"):
            continue
        PEER_ENV_MAP[key] = val
        agent_name = key[len("NANOBOT_PEER_"):].lower()
        try:
            info = json.loads(val)
            if isinstance(info, dict) and "id" in info:
                AGENT_NAMES.append(agent_name)
                SQUAD_ROSTER[agent_name] = {
                    "id": info["id"],
                    "gateway_port": info.get("gateway_port", 0),
                    "ws_port": info.get("ws_port", 0),
                }
                INSTANCE_WORKSPACES[agent_name] = f"/data/instances/{agent_name}"
        except (json.JSONDecodeError, TypeError):
            log(f"⚠️ 跳过无效 NANOBOT_PEER_*: {key}")

    AGENT_NAMES.sort()
    log(f"📋 编制加载: {len(AGENT_NAMES)} agents → {AGENT_NAMES}")

refresh_roster()

# ═══════════════════════════════════════════════════════════════
# WebUI Target & Per-agent HTTP Proxy Clients
# ═══════════════════════════════════════════════════════════════

WEBUI_AGENT = os.environ.get("WEBUI_AGENT", "").strip().lower()
if not WEBUI_AGENT or WEBUI_AGENT not in SQUAD_ROSTER:
    WEBUI_AGENT = AGENT_NAMES[0] if AGENT_NAMES else "neo"
    log(f"📡 WEBUI_AGENT 未指定或无效，回退到: {WEBUI_AGENT}")

def get_agent_for_user(username: str) -> str:
    """返回该 HF 用户对应的 agent name；未匹配或 Commander → WEBUI_AGENT"""
    if not username or username == "Unknown":
        return WEBUI_AGENT
    whitelist = [n.strip() for n in os.environ.get("COMMANDER_WHITELIST", "").split(",") if n.strip()]
    if username in whitelist:
        return WEBUI_AGENT
    # USER_AGENT_MAP flat format: {"username": "NANOBOT_PEER_neo"}
    try:
        user_map = json.loads(os.environ.get("USER_AGENT_MAP", "{}"))
    except json.JSONDecodeError:
        user_map = {}
    peer_key = user_map.get(username, "")
    if peer_key and peer_key.startswith("NANOBOT_PEER_"):
        agent_name = peer_key[len("NANOBOT_PEER_"):].lower()
        if agent_name in SQUAD_ROSTER:
            return agent_name
    return WEBUI_AGENT

# Per-agent HTTP clients for dynamic user → agent HTTP proxying
_http_clients = {}
for _name, _info in SQUAD_ROSTER.items():
    _http_clients[_name] = httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{_info['ws_port']}",
        timeout=120.0
    )
_default_client = _http_clients.get(WEBUI_AGENT)
log(f"🌐 HTTP proxy pool: {list(_http_clients.keys())}  (default={WEBUI_AGENT})")

# ═══════════════════════════════════════════════════════════════
# OAuth (Hugging Face)
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# OAuth (Hugging Face)
# ═══════════════════════════════════════════════════════════════

from starlette.config import Config as StarletteConfig

starlette_config = StarletteConfig(environ=os.environ)
oauth = OAuth(starlette_config)
_oauth_cid = os.environ.get("OAUTH_CLIENT_ID", "MISSING")
log(f"🔑 OAuth CLIENT_ID prefix: {_oauth_cid[:4]}... (len={len(_oauth_cid)})")
oauth.register(
    name="huggingface",
    client_id=_oauth_cid,
    client_secret=os.environ.get("OAUTH_CLIENT_SECRET"),
    server_metadata_url="https://huggingface.co/.well-known/openid-configuration",
    client_kwargs={"scope": "openid profile"},
)

# ═══════════════════════════════════════════════════════════════
# Auth helpers
# ═══════════════════════════════════════════════════════════════

def check_commander_privilege(session_user):
    if not session_user: return False
    whitelist = [n.strip() for n in os.environ.get("COMMANDER_WHITELIST", "").split(",") if n.strip()]
    current_username = "Unknown"
    if isinstance(session_user, dict):
        current_username = session_user.get("preferred_username") or session_user.get("username") or session_user.get("name") or "Unknown"
    elif isinstance(session_user, str):
        current_username = session_user
    return current_username in whitelist

class ForceAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        public_paths = ["/login", "/auth", "/health", "/logout", "/webui/bootstrap"]
        if path.startswith("/api/squad"):
            return await call_next(request)
        is_public = any(path == p for p in public_paths) or path.startswith("/assets") or path.startswith("/brand")
        if not is_public and not request.session.get("user"):
            login_url = str(request.url_for("login")).replace("http://", "https://")
            return RedirectResponse(url=login_url)
        return await call_next(request)

# ═══════════════════════════════════════════════════════════════
# Legion Monitor (agent alive/dead tracking)
# ═══════════════════════════════════════════════════════════════

legion_status: dict[str, str] = {}  # agent → "online"|"offline"
_legion_offline_since: dict[str, float] = {}  # agent → timestamp

# Startup grace period — allow agents time to boot before monitoring
GRACE_SECONDS = 60
_gatekeeper_boot_time = time.time()

async def legion_monitor():
    """Periodically health-check each agent's gateway_port."""
    await asyncio.sleep(GRACE_SECONDS)
    while True:
        for name in AGENT_NAMES:
            info = SQUAD_ROSTER.get(name)
            if not info:
                continue
            gw_port = info.get("gateway_port")
            if not gw_port:
                continue
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    resp = await client.get(f"http://127.0.0.1:{gw_port}/health")
                if resp.status_code == 200:
                    if legion_status.get(name) == "offline":
                        offline_sec = time.time() - _legion_offline_since.get(name, 0)
                        log(f"✅ [{name}] 恢复上线 (离线 {offline_sec:.0f}s)")
                    legion_status[name] = "online"
                    _legion_offline_since.pop(name, None)
                else:
                    _mark_offline(name, f"HTTP {resp.status_code}")
            except Exception as e:
                _mark_offline(name, str(e))
        await asyncio.sleep(10)

def _mark_offline(name: str, reason: str):
    if legion_status.get(name) != "offline":
        legion_status[name] = "offline"
        _legion_offline_since[name] = time.time()
        log(f"🔴 [{name}] 掉线 → {reason}")

# ═══════════════════════════════════════════════════════════════
# Log Bridge (capture gateway logs → gatekeeper stdout)
# ═══════════════════════════════════════════════════════════════

async def log_bridge():
    """Read agent gateway logs and forward to gatekeeper stdout."""
    await asyncio.sleep(GRACE_SECONDS)
    while True:
        for name in AGENT_NAMES:
            path = f"/data/instances/{name}/logs/gateway.log"
            try:
                with open(path) as f:
                    f.seek(0, 2)
            except FileNotFoundError:
                pass
        await asyncio.sleep(30)

# ═══════════════════════════════════════════════════════════════
# Dead Letter Queue (DLQ) Replay
# ═══════════════════════════════════════════════════════════════

DLQ_DIR = os.environ.get("DLQ_DIR", "/data/dlq")
os.makedirs(DLQ_DIR, exist_ok=True)

async def dlq_replay():
    """Periodically retry failed cross-agent messages."""
    await asyncio.sleep(GRACE_SECONDS + 30)
    while True:
        try:
            entries = sorted(
                [f for f in os.listdir(DLQ_DIR) if f.endswith(".dlq")],
                key=lambda f: os.path.getmtime(os.path.join(DLQ_DIR, f))
            )
            for fn in entries[:5]:
                fpath = os.path.join(DLQ_DIR, fn)
                try:
                    with open(fpath) as f:
                        msg = json.load(f)
                    target = msg.get("target")
                    if target and legion_status.get(target) == "online":
                        # Re-send logic would go here
                        os.remove(fpath)
                        log(f"📬 [DLQ] replayed {fn} → {target}")
                except (json.JSONDecodeError, OSError):
                    # Stale/broken DLQ entry, remove
                    try: os.remove(fpath)
                    except OSError: pass
        except Exception:
            pass
        await asyncio.sleep(60)

# ═══════════════════════════════════════════════════════════════
# FastAPI App
# ═══════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    log(f"🛡️ Gatekeeper v5.0 (DLQ Replay) online — {len(AGENT_NAMES)} agents.")
    asyncio.create_task(legion_monitor())
    asyncio.create_task(log_bridge())
    asyncio.create_task(dlq_replay())
    yield

app = FastAPI(lifespan=lifespan)
app.add_middleware(ForceAuthMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET", "nanobot_commander_secret_123"),
    https_only=True,
    same_site="none"
)

@app.middleware("http")
async def force_https_middleware(request: Request, call_next):
    request.scope["scheme"] = "https"
    return await call_next(request)

# ═══════════════════════════════════════════════════════════════
# OAuth Routes
# ═══════════════════════════════════════════════════════════════

@app.get("/login")
async def login(request: Request):
    request.session.clear()
    redirect_uri = str(request.url_for('auth')).replace("http://", "https://")
    return await oauth.huggingface.authorize_redirect(request, redirect_uri)

@app.get("/auth")
async def auth(request: Request):
    try:
        token = await oauth.huggingface.authorize_access_token(request)
        user_info = token.get('userinfo')
        if user_info:
            request.session['user'] = dict(user_info)
            return RedirectResponse(url="/")
    except Exception:
        pass
    return RedirectResponse(url="/login")

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/")

@app.get("/health")
async def health():
    return {"status": "ok", "role": "gatekeeper", "agents": len(AGENT_NAMES)}

# ═══════════════════════════════════════════════════════════════
# Squad Relay Endpoint
# ═══════════════════════════════════════════════════════════════

RELAY_TOKEN = os.environ.get("SQUAD_RELAY_TOKEN", "").strip()
RELAY_TIMEOUT = int(os.environ.get("RELAY_TIMEOUT", "60"))

@app.post("/api/squad/relay")
async def squad_relay(request: Request):
    """
    POST /api/squad/relay
    Header: X-Squad-Token: <SQUAD_RELAY_TOKEN>
    Body:   {"sender":"neo","target":"trinity","message":"ping","correlation_id":"sq-..."}

    Auth-free (no OAuth session required) — secured by shared token.
    Permission: reuses gatekeeper's COMMANDER_WHITELIST + USER_AGENT_MAP.
    """
    # ── Auth ──
    auth_header = request.headers.get("X-Squad-Token", "")
    if not RELAY_TOKEN or auth_header != RELAY_TOKEN:
        return JSONResponse(
            {"status": "unauthorized", "error": "invalid or missing X-Squad-Token"},
            status_code=401)

    # ── Parse ──
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "bad_request", "error": "invalid JSON"}, status_code=400)

    sender = (body.get("sender") or "").strip()
    target = (body.get("target") or "").strip().lower()
    message = body.get("message") or ""
    correlation_id = body.get("correlation_id", f"sq-relay-{uuid4().hex[:8]}")

    if not sender or not target or not message:
        return JSONResponse(
            {"status": "bad_request", "error": "missing sender/target/message"}, status_code=400)

    # ── Roster & liveness ──
    if target not in SQUAD_ROSTER:
        return JSONResponse(
            {"status": "roster_miss", "error": f"'{target}' not in squad", "correlation_id": correlation_id}, status_code=404)
    if legion_status.get(target) != "online":
        return JSONResponse(
            {"status": "agent_offline", "error": f"'{target}' is offline", "correlation_id": correlation_id}, status_code=503)

    # ── Permission (same logic as squad_bridge v6.1) ──
    whitelist = [w.strip().lower() for w in
                  os.environ.get("COMMANDER_WHITELIST", "").split(",") if w.strip()]
    user_map: dict = {}
    try:
        user_map = json.loads(os.environ.get("USER_AGENT_MAP", "{}"))
    except json.JSONDecodeError:
        pass

    # Reverse lookup: agent alias → HF username
    # USER_AGENT_MAP format: {"username": "NANOBOT_PEER_NEO", ...}  (flat, values are strings)
    agent_to_user: dict[str, str] = {}
    for uname, peer_key in user_map.items():
        if isinstance(peer_key, str) and peer_key.upper().startswith("NANOBOT_PEER_"):
            agent_name = peer_key[len("NANOBOT_PEER_"):].lower()
            agent_to_user[agent_name] = uname.lower()

    effective_user = sender.lower()
    if effective_user in agent_to_user:
        effective_user = agent_to_user[effective_user]

    is_commander = effective_user in whitelist

    if not is_commander:
        allowed: list[str] = []
        if effective_user in user_map:
            peer_key = user_map[effective_user]
            if isinstance(peer_key, str) and peer_key.upper().startswith("NANOBOT_PEER_"):
                allowed.append(peer_key[len("NANOBOT_PEER_"):].lower())
        if target not in allowed:
            return JSONResponse({
                "status": "permission_denied",
                "error": f"'{sender}' (user:{effective_user}) not authorized for '{target}'",
                "correlation_id": correlation_id,
            }, status_code=403)

    # ── Relay via WebSocket ──
    target_info = SQUAD_ROSTER[target]
    nanobot_token = os.environ.get("NANOBOT_TOKEN", "").strip()
    ws_url = f"ws://127.0.0.1:{target_info['ws_port']}/"
    if nanobot_token:
        ws_url += f"?token={nanobot_token}"

    try:
        log(f"📨 [Relay] {sender}→{target} connect {ws_url}")
        ws = await asyncio.wait_for(
            websockets.connect(ws_url, close_timeout=5),
            timeout=15
        )
        async with ws:
            # Step 1: wait for server ready greeting
            greeting_raw = await asyncio.wait_for(ws.recv(), timeout=10)
            greeting = json.loads(greeting_raw)
            if greeting.get("event") != "ready":
                log(f"❌ [Relay] unexpected greeting: {greeting}")
                return JSONResponse({
                    "status": "protocol_error",
                    "error": f"expected 'ready' event, got {greeting.get('event')}",
                    "correlation_id": correlation_id,
                }, status_code=502)

            # Step 2: send message payload
            payload = json.dumps({
                "type": "message",
                "chat_id": target_info["id"],
                "content": f"[{sender.upper()}]: {message}",
            })
            await ws.send(payload)
            log(f"📨 [Relay] {sender}→{target} sent ({len(payload)}B)")

            # Step 3: collect response
            responses: list[str] = []
            try:
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=RELAY_TIMEOUT)
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        log(f"📨 [Relay] non-JSON frame ({len(raw)}B)")
                        continue

                    event = data.get("event", "")

                    if event == "error":
                        detail = data.get("detail", "unknown")
                        log(f"❌ [Relay] framework error: {detail}")
                        return JSONResponse({
                            "status": "framework_error",
                            "error": detail,
                            "correlation_id": correlation_id,
                        }, status_code=502)

                    if event == "heartbeat":
                        continue

                    if event == "turn_end":
                        reply = "\n".join(responses) if responses else "(empty)"
                        log(f"✅ [Relay] {sender}→{target} ok ({len(reply)} chars)")
                        return JSONResponse({
                            "status": "delivered",
                            "target_response": reply,
                            "target": target,
                            "correlation_id": correlation_id,
                        })

                    if event == "delta":
                        text = data.get("text", "")
                        if text:
                            responses.append(text)
                        continue

                    if event == "stream_end":
                        continue

                    # Non-streaming fallback: check 'content' field
                    content = data.get("content")
                    if content and content.strip():
                        responses.append(content)

            except asyncio.TimeoutError:
                if responses:
                    reply = "\n".join(responses)
                    log(f"⏱️ [Relay] timeout with partial ({len(reply)} chars)")
                    return JSONResponse({
                        "status": "partial",
                        "target_response": reply,
                        "target": target,
                        "correlation_id": correlation_id,
                    })
                log(f"⏱️ [Relay] timeout ({RELAY_TIMEOUT}s)")
                return JSONResponse({
                    "status": "timeout",
                    "error": f"no response from agent within {RELAY_TIMEOUT}s",
                    "correlation_id": correlation_id,
                }, status_code=504)

    except asyncio.TimeoutError:
        log(f"❌ [Relay] connect timeout (15s)")
        return JSONResponse({
            "status": "connection_error",
            "error": "WebSocket connection timed out",
            "correlation_id": correlation_id,
        }, status_code=502)
    except Exception as e:
        log(f"❌ [Relay] {sender}→{target} error: {type(e).__name__}: {e}")
        return JSONResponse({
            "status": "connection_error",
            "error": f"{type(e).__name__}: {e}",
            "correlation_id": correlation_id,
        }, status_code=502)

# ═══════════════════════════════════════════════════════════════
# WebSocket Proxy (for WebUI)
# ═══════════════════════════════════════════════════════════════

@app.websocket("/{path:path}")
async def ws_proxy(path: str, client_ws: WebSocket):
    """Relay WebUI WebSocket connections to target agent's ws_port."""
    await client_ws.accept()

    # ── Session & identity ──────────────────────────────────
    session_user = client_ws.scope.get("session", {}).get("user")
    whitelist = [n.strip() for n in os.environ.get("COMMANDER_WHITELIST", "").split(",") if n.strip()]
    real_name = "Guest"
    if isinstance(session_user, dict):
        real_name = session_user.get("preferred_username") or session_user.get("username") or session_user.get("name") or "Unknown"
    is_commander = bool(real_name in whitelist)
    uname = real_name if is_commander else f"{real_name}_Observer"

    # ── Squad roster injection (V4/V6 interceptor expects these) ──
    await client_ws.send_text(json.dumps({
        "event": "auth_status", "type": "auth_status",
        "role": "commander" if is_commander else "observer",
    }))
    for event_type in ("legion_update", "cluster_update"):
        await client_ws.send_text(json.dumps({
            "event": event_type, "type": event_type,
            "data": legion_status,
            "roster": {
                a: {"id": info["id"], "name": a,
                    "gateway_port": info.get("gateway_port"),
                    "ws_port": info.get("ws_port")}
                for a, info in SQUAD_ROSTER.items()
            },
            "logs": [], "messages": [], "history": [],
        }))

    # ── Route to agent ──────────────────────────────────────
    target_agent = get_agent_for_user(real_name)
    target_info = SQUAD_ROSTER.get(target_agent, SQUAD_ROSTER.get(WEBUI_AGENT, {}))
    ws_url = f"ws://127.0.0.1:{target_info['ws_port']}/{path}?user={uname}"
    log(f"🔀 WS 路由: {real_name} → {target_agent} (port {target_info.get('ws_port','?')} path /{path})")

    try:
        agent_ws = await asyncio.wait_for(
            websockets.connect(ws_url, close_timeout=5), timeout=15
        )
        try:
            async def client_to_agent():
                try:
                    while True:
                        data = await client_ws.receive_text()
                        await agent_ws.send(data)
                except (WebSocketDisconnect, Exception):
                    pass

            async def agent_to_client():
                try:
                    while True:
                        data = await agent_ws.recv()
                        if isinstance(data, bytes):
                            data = data.decode("utf-8", errors="replace")
                        await client_ws.send_text(data)
                except (websockets.exceptions.ConnectionClosed, Exception):
                    pass

            await asyncio.gather(client_to_agent(), agent_to_client())
        finally:
            try:
                await agent_ws.close()
            except Exception:
                pass
    except asyncio.TimeoutError:
        log(f"🔌 [WS Proxy] {uname}→{target_agent} connect timeout")
        try:
            await client_ws.close(code=4003, reason="agent connect timeout")
        except Exception:
            pass
    except Exception as e:
        log(f"🔌 [WS Proxy] {uname}→{target_agent} error: {e}")
        try:
            await client_ws.close()
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════════
# Bootstrap / WebUI
# ═══════════════════════════════════════════════════════════════

# NOTE: /webui/bootstrap is deliberately NOT overridden here.
# The catch-all HTTP proxy forwards it to the target agent's ws_port,
# which returns { token, ws_path, ... } needed for WebSocket auth.
# Squad roster is injected via legion_update events at WS connect time.

@app.get("/")
async def index(request: Request):
    """Serve nanobot WebUI landing page — proxy to agent ws_port for real index.html."""
    session_user = request.session.get("user")
    uname = "Unknown"
    if isinstance(session_user, dict):
        uname = session_user.get("preferred_username") or session_user.get("username") or "Unknown"
    target_agent = get_agent_for_user(uname)
    client = _http_clients.get(target_agent, _default_client)
    if not client:
        return HTMLResponse("<h1>Staging: no agent available</h1>", status_code=503)
    try:
        resp = await client.get("/")
        return HTMLResponse(
            content=resp.text,
            status_code=resp.status_code,
            headers=dict(resp.headers),
        )
    except Exception as e:
        log(f"❌ [GET /] proxy to {target_agent} failed: {e}")
        return HTMLResponse(f"<h1>Agent {target_agent} unreachable</h1>", status_code=502)

# ═══════════════════════════════════════════════════════════════
# Catch-all HTTP proxy — forward unmatched paths to agent ws_port
# ═══════════════════════════════════════════════════════════════

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy(request: Request, path: str = ""):
    """Proxy all unmatched HTTP traffic to the appropriate agent's ws_port."""
    from fastapi.responses import StreamingResponse, Response

    session_user = request.session.get("user")
    uname = "Unknown"
    if isinstance(session_user, dict):
        uname = session_user.get("preferred_username") or session_user.get("username") or session_user.get("name") or "Unknown"

    target_agent = get_agent_for_user(uname)
    client = _http_clients.get(target_agent, _default_client)
    if not client:
        return Response(content="No agent available", status_code=503)

    try:
        url = httpx.URL(path=f"/{path}" if path else "/", query=request.url.query.encode("utf-8"))
        headers = {k: v for k, v in request.headers.items() if k.lower() not in ["host", "content-length"]}
        rp_req = client.build_request(request.method, url, headers=headers, content=await request.body())
        rp_resp = await client.send(rp_req, stream=True)
        return StreamingResponse(rp_resp.aiter_raw(), status_code=rp_resp.status_code, headers=dict(rp_resp.headers))
    except Exception as e:
        return Response(content="System Warming Up...", status_code=503)

# ═══════════════════════════════════════════════════════════════
# Entrypoint
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("GATEKEEPER_PORT", "7860"))
    uvicorn.run(app, host="0.0.0.0", port=port)
