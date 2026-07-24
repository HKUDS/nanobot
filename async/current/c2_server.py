"""
LUMINA C2 v2.5.0 — FastAPI Backend
Async Executive Solutions | Wildwulfie Studios

This is Friday.

New in v2.5.0:
- Multi-agent orchestration — COORDINATOR, RESEARCHER, WRITER,
  ANALYST, MONITOR, EXECUTOR working in concert
- /friday/* routes — Boss talks, Friday handles everything
- Parallel agent execution where tasks allow
- Full plan tracing — see exactly which agents did what
- Agentic loop — agents chain results into final output
- Web 4.0 executor agent — browser automation planning
- All v1.x capabilities retained and enhanced
"""

import asyncio, json, os, subprocess, time
from datetime import datetime, timedelta
from typing import Optional, AsyncGenerator

import psutil, uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel
import hashlib

from secrets_client import secrets
from nvidia_client import nvidia, NimModel, TaskType
from bitnet_client import bitnet, should_use_local
from task_manager import task_manager, TaskPriority
from memory_manager import memory
from trigger_engine import triggers, Alert, AlertCategory, AlertLevel
from perplexica_client import perplexica as perplexity  # self-hosted
from obsidian_client import obsidian
from situational_awareness import awareness
from orchestrator import friday, AgentRole

# ── STARTUP ───────────────────────────────────────
secrets.load_all()

SECRET_KEY    = secrets.get("C2_SECRET_KEY",        os.environ.get("C2_SECRET_KEY",        "CHANGE-THIS"))
ALGORITHM     = "HS256"
NANOBOT_PORT  = 18789
C2_PORT       = 18790

import nvidia_client as _nvc
_nvc.NVIDIA_API_KEY   = secrets.get("NVIDIA_API_KEY",       os.environ.get("NVIDIA_API_KEY",       ""))
nvidia.client.api_key = _nvc.NVIDIA_API_KEY

# Perplexica is self-hosted and does not require an API key.
# Keep compatibility with optional client methods if they exist.
if hasattr(perplexity, "set_key"):
    perplexity.set_key(
        secrets.get("PERPLEXITY_API_KEY", os.environ.get("PERPLEXITY_API_KEY", ""))
    )
obsidian.set_credentials(
    rest_url   = secrets.get("OBSIDIAN_REST_URL",   os.environ.get("OBSIDIAN_REST_URL",   "http://localhost:27123")),
    api_key    = secrets.get("OBSIDIAN_API_KEY",    os.environ.get("OBSIDIAN_API_KEY",    "")),
    vault_path = secrets.get("OBSIDIAN_VAULT_PATH", os.environ.get("OBSIDIAN_VAULT_PATH", "")),
)

app = FastAPI(title="LUMINA C2 — FRIDAY", version="2.5.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
security = HTTPBearer(auto_error=False)

# ── AGENT ISOLATION ───────────────────────────────
@app.middleware("http")
async def block_agent(request, call_next):
    if SECRET_KEY != "LOCAL_DEV_SECRET_18790":
        host = request.client.host if request.client else ""
        if host in ("127.0.0.1","::1","localhost"):
            return JSONResponse(status_code=403, content={"detail": "AGENT ACCESS DENIED"})
    return await call_next(request)

# ── AUTH ──────────────────────────────────────────
def verify_token(creds: HTTPAuthorizationCredentials = Depends(security)):
    if SECRET_KEY == "LOCAL_DEV_SECRET_18790":
        return {"operator": "admin", "dev": True}
    if not creds:
        raise HTTPException(status_code=401, detail="MISSING TOKEN")
    try:    return jwt.decode(creds.credentials, SECRET_KEY, algorithms=[ALGORITHM])
    except: raise HTTPException(status_code=401, detail="INVALID TOKEN")

def create_token(data: dict, expires_hours: int = 168) -> str:
    exp = datetime.utcnow() + timedelta(hours=expires_hours)
    return jwt.encode({**data, "exp": exp}, SECRET_KEY, algorithm=ALGORITHM)

# ── REQUEST MODELS ────────────────────────────────
class FridayRequest(BaseModel):
    """Boss talks to Friday. Friday handles everything."""
    task:           str
    client_name:    Optional[str]  = None
    client_id:      Optional[str]  = None
    job_title:      Optional[str]  = None
    revenue:        float          = 0.0
    write_obsidian: bool           = True
    priority:       str            = "normal"

class CommandRequest(BaseModel):
    """Legacy direct command — still supported."""
    command:        str
    priority:       str            = "normal"
    model_override: Optional[str]  = None
    task_type:      Optional[str]  = None
    client_id:      Optional[str]  = None
    client_name:    Optional[str]  = None
    job_title:      Optional[str]  = None
    revenue:        float          = 0.0
    use_perplexity: Optional[bool] = None
    write_obsidian: bool           = True

class NvidiaRequest(BaseModel):
    prompt:         str
    task_type:      Optional[str] = None
    model_override: Optional[str] = None
    system:         str           = "You are Lumina, the powerful AI executive assistant for Brent Wilf (Boss)."
    max_tokens:     int           = 2048
    temperature:    float         = 0.7
    stream:         bool          = False

class PerplexityRequest(BaseModel):
    query:  str
    mode:   str            = "fast"
    system: Optional[str]  = None

class McpToggleRequest(BaseModel):
    enabled: bool

class ClientRequest(BaseModel):
    name:     str
    platform: str
    email:    Optional[str] = None
    notes:    Optional[str] = None

class JobUpdateRequest(BaseModel):
    status:          Optional[str]   = None
    revenue:         Optional[float] = None
    client_feedback: Optional[str]   = None
    rating:          Optional[float] = None
    result_summary:  Optional[str]   = None

class PreferenceRequest(BaseModel):
    key:      str
    value:    str
    category: str = "general"

class ContextRequest(BaseModel):
    category:     str
    topic:        str
    summary:      str
    importance:   str           = "normal"
    source:       Optional[str] = None
    expires_days: int           = 30

class ManualAlertRequest(BaseModel):
    category: str
    level:    str
    title:    str
    body:     str
    action:   Optional[str] = None

class ObsidianConfigRequest(BaseModel):
    rest_url:   str
    api_key:    str
    vault_path: str = ""

# ── RATE LIMITER ──────────────────────────────────
class NvidiaRateLimiter:
    def __init__(self, stagger_s=2.5):
        self._lock = asyncio.Lock(); self._last = 0.0; self._stagger = stagger_s
    async def acquire(self):
        async with self._lock:
            wait = max(0.0, (self._last + self._stagger) - time.time())
            if wait > 0: await asyncio.sleep(wait)
            self._last = time.time()

nvidia_limiter = NvidiaRateLimiter()

# ── STATE TRACKER ─────────────────────────────────
class StateTracker:
    def __init__(self): self._h = {}
    def cid(self, ws): return f"{ws.client.host}:{ws.client.port}" if ws.client else "x"
    def changed(self, ws, state):
        h = hashlib.md5(json.dumps(state, sort_keys=True).encode()).hexdigest()
        prev = self._h.get(self.cid(ws))
        if h != prev: self._h[self.cid(ws)] = h; return True
        return False
    def remove(self, ws): self._h.pop(self.cid(ws), None)

tracker     = StateTracker()
active_ws: list[WebSocket] = []

async def push_alert_to_ws(alert: Alert):
    payload = json.dumps({"type":"alert","alert":alert.to_dict(),"unread":triggers.store.unread_count()})
    dead = []
    for ws in active_ws:
        try:    await ws.send_text(payload)
        except: dead.append(ws)
    for ws in dead:
        if ws in active_ws: active_ws.remove(ws)

# ── HELPERS ───────────────────────────────────────
def _nanobot_proc():
    for p in psutil.process_iter(['pid','name','cmdline']):
        try:
            if 'nanobot' in " ".join(p.info['cmdline'] or []).lower(): return p
        except: pass
    return None

def _agent_status():
    p = _nanobot_proc()
    if not p: return "offline"
    try:
        s = p.status()
        return "online" if s in (psutil.STATUS_RUNNING, psutil.STATUS_SLEEPING) else "error"
    except: return "offline"

def _server_stats():
    mem = psutil.virtual_memory(); disk = psutil.disk_usage('/')
    up  = datetime.now() - datetime.fromtimestamp(psutil.boot_time())
    d,r = divmod(int(up.total_seconds()),86400); h,r = divmod(r,3600); m = r//60
    return {"cpu_pct":psutil.cpu_percent(0.5),"ram_pct":mem.percent,
            "disk_pct":disk.percent,"uptime":f"{d}d {h:02d}h {m:02d}m",
            "ram_used_gb":round(mem.used/1e9,1),"ram_total_gb":round(mem.total/1e9,1)}

def _mcp_servers():
    p = os.path.expanduser("~/.nanobot/config.json")
    if not os.path.exists(p): return []
    try:
        cfg = json.load(open(p))
        return [{"name":n,"status":"online","category":_cat(n),"tool_count":0,
                 "last_used":"UNKNOWN","enabled":not s.get("disabled",False)}
                for n,s in cfg.get("mcpServers",{}).items()]
    except: return []

def _cat(n):
    n = n.lower()
    if any(x in n for x in ["coin","crypto","ccxt","dex"]):      return "CRYPTO"
    if any(x in n for x in ["stock","finance","alpha"]):         return "FINANCE"
    if any(x in n for x in ["search","tavily","exa","perplexity"]): return "SEARCH"
    if any(x in n for x in ["browser","playwright"]):            return "BROWSER"
    if any(x in n for x in ["file","filesystem","obsidian"]):    return "FILES"
    if any(x in n for x in ["news","panic"]):                    return "NEWS"
    return "TOOLS"

def _all_logs():
    p = "/var/log/nanobot.log"
    if not os.path.exists(p): return []
    try: return [l.rstrip() for l in open(p).readlines()]
    except: return []

def _logs_since(cursor):
    all_lines = _all_logs()
    return all_lines[cursor:], len(all_lines)

def _active_task():
    active_plans = friday.get_active()
    if active_plans: return f"[FRIDAY] {active_plans[0]['original_task'][:60]}"
    active = task_manager.get_active()
    if active:
        t = active[0]["prompt"]
        return t[:80]+"..." if len(t)>80 else t
    return "IDLE"

def _compressed_status():
    rev = memory.get_revenue_stats()
    return {
        "agent_status":  _agent_status(),
        "active_task":   _active_task(),
        "server":        _server_stats(),
        "task_stats":    task_manager.stats(),
        "friday_stats":  friday.stats(),
        "mcp_count":     len(_mcp_servers()),
        "revenue":       rev,
        "alert_stats":   triggers.store.stats(),
        "timestamp":     datetime.now().strftime("%H:%M:%S"),
        "version":       "2.5.0",
    }

# ── STARTUP TASKS ─────────────────────────────────
@app.on_event("startup")
async def startup():
    triggers.register_ws_callback(push_alert_to_ws)
    asyncio.create_task(triggers.run())
    asyncio.create_task(awareness.run())
    asyncio.create_task(_memory_sync_loop())
    print("[FRIDAY]    Multi-agent orchestrator online")
    print("[TRIGGERS]  Proactive engine started")
    print("[AWARENESS] Situational awareness started")
    print("[MEMORY]    Background sync started")

async def _memory_sync_loop():
    while True:
        await asyncio.sleep(300)
        memory.sync_now()

# ── FRIDAY ROUTES — primary interface ─────────────

@app.post("/friday",              dependencies=[Depends(verify_token)])
async def friday_task(body: FridayRequest):
    """
    Boss talks to Friday. Friday handles everything.
    Multi-agent orchestration — plan, delegate, assemble, deliver.
    """
    job_id = None
    if body.job_title:
        job_id = memory.add_job(
            title=body.job_title, platform="friday",
            prompt=body.task, client_id=body.client_id,
            revenue=body.revenue,
        )

    result = await friday.run(
        task=body.task,
        client_name=body.client_name,
        job_id=job_id,
        write_obsidian=body.write_obsidian,
    )

    if job_id and result.get("status") == "complete":
        memory.update_job(job_id, status="complete",
            result_summary=result.get("result","")[:500],
            model_used=f"friday-{result.get('task_count',1)}-agents")

    memory.sync_if_due()
    return {**result, "job_id": job_id}

@app.get("/friday/active",        dependencies=[Depends(verify_token)])
async def friday_active():
    return {"active": friday.get_active(), "stats": friday.stats()}

@app.get("/friday/history",       dependencies=[Depends(verify_token)])
async def friday_history(limit: int = 20):
    return {"history": friday.get_history(limit), "stats": friday.stats()}

@app.get("/friday/agents",        dependencies=[Depends(verify_token)])
async def friday_agents():
    return {
        "agents": [
            {"role": r.value, "description": d.strip()[:120]}
            for r, d in {
                AgentRole.COORDINATOR: "Routes tasks, delegates to specialists, assembles final output",
                AgentRole.RESEARCHER:  "Deep research via Perplexity + NVIDIA. Real-time + trained knowledge",
                AgentRole.WRITER:      "Polished client-facing reports. Llama 3.3 70B",
                AgentRole.ANALYST:     "Crypto, finance, market data. DeepSeek R1 reasoning",
                AgentRole.MONITOR:     "Live feed watching. Upwork, news, crypto prices",
                AgentRole.EXECUTOR:    "Web 4.0 — browser automation and web action planning",
            }.items()
        ],
        "version": "2.5.0",
    }

# ── CORE ROUTES ───────────────────────────────────

@app.get("/health")
async def health():
    return {"status":"online","version":"2.5.0",
            "friday":"active","alerts":triggers.store.unread_count()}

@app.get("/status", dependencies=[Depends(verify_token)])
async def status():
    srv = _server_stats()
    return {
        "agent_status":  _agent_status(), "active_task": _active_task(),
        "server": srv, "oracle": srv,
        "aws":           {"secrets": secrets.rotate_check()},
        "mcp_servers":   _mcp_servers(), "recent_logs": _all_logs()[-20:],
        "task_stats":    task_manager.stats(),
        "friday_stats":  friday.stats(),
        "revenue":       memory.get_revenue_stats(),
        "memory":        memory.full_stats(),
        "alerts":        triggers.store.stats(),
        "situation":     awareness.get_current_context(),
        "timestamp":     datetime.now().strftime("%H:%M:%S"), "version": "2.5.0",
    }

@app.post("/agent/start", dependencies=[Depends(verify_token)])
async def agent_start():
    if _nanobot_proc(): return {"status":"already_running"}
    try:
        subprocess.Popen(["nanobot","--port",str(NANOBOT_PORT)],
            stdout=open("/var/log/nanobot.log","a"), stderr=subprocess.STDOUT)
        return {"status":"started"}
    except Exception as e: raise HTTPException(500, str(e))

@app.post("/agent/stop",  dependencies=[Depends(verify_token)])
async def agent_stop():
    p = _nanobot_proc()
    if not p: return {"status":"not_running"}
    p.terminate(); return {"status":"stopping"}

@app.post("/agent/kill",  dependencies=[Depends(verify_token)])
async def agent_kill():
    p = _nanobot_proc()
    if not p: return {"status":"not_running"}
    p.kill(); return {"status":"killed"}

@app.post("/agent/command", dependencies=[Depends(verify_token)])
async def agent_command(body: CommandRequest):
    """Legacy direct command — routes through Friday automatically."""
    fr = FridayRequest(
        task=body.command, client_name=body.client_name,
        client_id=body.client_id, job_title=body.job_title,
        revenue=body.revenue, write_obsidian=body.write_obsidian,
        priority=body.priority,
    )
    return await friday_task(fr)

@app.get("/agent/logs",           dependencies=[Depends(verify_token)])
async def agent_logs(lines: int = 100, since: int = 0):
    all_lines = _all_logs()
    if since > 0:
        return {"lines":all_lines[since:][-lines:],"cursor":len(all_lines),"delta":True}
    return {"lines":all_lines[-lines:],"cursor":len(all_lines),"delta":False}

# ── PERPLEXITY ────────────────────────────────────

@app.post("/perplexity/search",   dependencies=[Depends(verify_token)])
async def perplexity_search(body: PerplexityRequest):
    kwargs = {}
    if body.system: kwargs["system"] = body.system
    result = await perplexity.search(body.query, mode=body.mode, **kwargs)
    try:
        await obsidian.write_research_report(topic=body.query,
            content=result["answer"], citations=result.get("citations",[]))
    except: pass
    return result

@app.post("/perplexity/market",   dependencies=[Depends(verify_token)])
async def perplexity_market(query: str):
    result = await perplexity.market_intelligence(query)
    try: await obsidian.write_research_report(topic=query,
        content=result["answer"], citations=result.get("citations",[]), category="market")
    except: pass
    return result

@app.post("/perplexity/crypto",   dependencies=[Depends(verify_token)])
async def perplexity_crypto(token: str):
    result = await perplexity.crypto_research(token)
    try: await obsidian.write_research_report(topic=f"{token} analysis",
        content=result["answer"], citations=result.get("citations",[]), category="crypto")
    except: pass
    return result

# ── OBSIDIAN ──────────────────────────────────────

@app.get("/obsidian/status",      dependencies=[Depends(verify_token)])
async def obsidian_status():
    available = await obsidian.ping()
    return {"available":available,"rest_url":obsidian._rest_url,"vault_path":obsidian._vault_path}

@app.post("/obsidian/config",     dependencies=[Depends(verify_token)])
async def obsidian_config(body: ObsidianConfigRequest):
    obsidian.set_credentials(body.rest_url, body.api_key, body.vault_path)
    available = await obsidian.ping()
    return {"status":"configured","available":available}

@app.post("/obsidian/dashboard",  dependencies=[Depends(verify_token)])
async def update_dashboard():
    rev = memory.get_revenue_stats(); clients = memory.get_all_clients()
    jobs = memory.get_recent_jobs(20)
    active = [j for j in jobs if j.get("status") in ("pending","running")]
    ok = await obsidian.update_dashboard(rev, len(clients), len(active),
                                          triggers.store.unread_count())
    return {"status":"updated" if ok else "failed"}

# ── AWARENESS ─────────────────────────────────────

@app.get("/awareness/context",    dependencies=[Depends(verify_token)])
async def get_awareness():           return {"context": awareness.get_current_context()}
@app.post("/awareness/briefing",  dependencies=[Depends(verify_token)])
async def trigger_briefing():
    await awareness.morning_briefing(); return {"status":"briefing_fired"}
@app.post("/awareness/evening",   dependencies=[Depends(verify_token)])
async def trigger_evening():
    await awareness.evening_summary(); return {"status":"evening_summary_fired"}

# ── ALERTS ────────────────────────────────────────

@app.get("/alerts",               dependencies=[Depends(verify_token)])
async def get_alerts(unread_only: bool = False, limit: int = 50):
    return {"alerts":triggers.store.get_all(unread_only,limit),"stats":triggers.store.stats()}
@app.post("/alerts/{aid}/read",   dependencies=[Depends(verify_token)])
async def mark_read(aid: str):
    triggers.store.mark_read(aid); return {"status":"read","alert_id":aid}
@app.post("/alerts/read-all",     dependencies=[Depends(verify_token)])
async def mark_all_read():
    triggers.store.mark_all_read(); return {"status":"all_read"}
@app.post("/alerts/manual",       dependencies=[Depends(verify_token)])
async def add_alert(body: ManualAlertRequest):
    import uuid
    alert = Alert(id=str(uuid.uuid4())[:8], category=AlertCategory(body.category),
        level=AlertLevel(body.level), title=body.title, body=body.body, action=body.action)
    triggers.store.add(alert)
    return {"status":"created","alert_id":alert.id}

# ── MEMORY ────────────────────────────────────────

@app.get("/memory",               dependencies=[Depends(verify_token)])
async def memory_stats():            return memory.full_stats()
@app.get("/memory/identity",      dependencies=[Depends(verify_token)])
async def get_identity():            return memory.get_identity()
@app.get("/memory/context",       dependencies=[Depends(verify_token)])
async def get_context():             return {"context": memory.get_context_prompt()}
@app.get("/memory/revenue",       dependencies=[Depends(verify_token)])
async def get_revenue():             return memory.get_revenue_stats()
@app.get("/memory/clients",       dependencies=[Depends(verify_token)])
async def get_clients():             return {"clients": memory.get_all_clients()}
@app.post("/memory/clients",      dependencies=[Depends(verify_token)])
async def add_client(body: ClientRequest):
    cid = memory.add_client(body.name, body.platform, body.email, body.notes)
    try: await obsidian.write_client_profile(body.name, body.platform, notes=body.notes or "")
    except: pass
    return {"status":"created","client_id":cid}
@app.get("/memory/clients/{cid}", dependencies=[Depends(verify_token)])
async def get_client(cid: str):
    c = memory.get_client(cid)
    if not c: raise HTTPException(404, "Client not found")
    return c
@app.get("/memory/jobs",          dependencies=[Depends(verify_token)])
async def get_jobs(limit: int = 50):
    return {"jobs":memory.get_recent_jobs(limit),"revenue":memory.get_revenue_stats()}
@app.patch("/memory/jobs/{jid}",  dependencies=[Depends(verify_token)])
async def update_job(jid: str, body: JobUpdateRequest):
    updates = {k:v for k,v in body.dict().items() if v is not None}
    if body.status == "delivered": updates["delivered_at"] = datetime.now().isoformat()
    memory.update_job(jid, **updates); return {"status":"updated","job_id":jid}
@app.get("/memory/preferences",   dependencies=[Depends(verify_token)])
async def get_prefs():               return memory.get_all_preferences()
@app.post("/memory/preferences",  dependencies=[Depends(verify_token)])
async def set_pref(body: PreferenceRequest):
    memory.set_preference(body.key, body.value, body.category)
    return {"status":"updated","key":body.key}
@app.get("/memory/world",         dependencies=[Depends(verify_token)])
async def get_world(category: str = None):
    return {"context": memory.get_context(category)}
@app.post("/memory/world",        dependencies=[Depends(verify_token)])
async def add_world(body: ContextRequest):
    cid = memory.add_context(body.category, body.topic, body.summary,
                             body.importance, body.source, body.expires_days)
    return {"status":"created","context_id":cid}
@app.post("/memory/sync",         dependencies=[Depends(verify_token)])
async def force_sync():
    memory.sync_now(); return {"status":"synced","timestamp":datetime.now().isoformat()}

# ── TASKS ─────────────────────────────────────────

@app.get("/tasks",                dependencies=[Depends(verify_token)])
async def get_tasks(limit: int = 50):
    return {"tasks":task_manager.get_all(limit),"stats":task_manager.stats(),
            "queue":task_manager.get_queue()}
@app.get("/tasks/active",         dependencies=[Depends(verify_token)])
async def active_tasks():            return {"tasks": task_manager.get_active()}
@app.post("/tasks/{tid}/cancel",  dependencies=[Depends(verify_token)])
async def cancel_task(tid: str):
    task_manager.cancel(tid); return {"status":"cancelled","task_id":tid}

# ── NVIDIA ────────────────────────────────────────

@app.get("/nvidia/models",        dependencies=[Depends(verify_token)])
async def nvidia_models():
    return {"models":nvidia.get_model_info(),
            "routing":{t.value:nvidia.route_task(t).name for t in TaskType if t.value!="manual"}}

@app.post("/nvidia/stream",       dependencies=[Depends(verify_token)])
async def nvidia_stream(body: NvidiaRequest):
    tt  = TaskType(body.task_type) if body.task_type else nvidia.detect_task_type(body.prompt)
    mo  = NimModel(body.model_override) if body.model_override else None
    sel = nvidia.route_task(tt, override_model=mo)
    task = task_manager.create(body.prompt, source="operator_stream")
    task_manager.start(task.id, sel.value, tt.value)
    await nvidia_limiter.acquire()
    async def generate() -> AsyncGenerator[str, None]:
        full = []
        try:
            stream = await nvidia.client.chat.completions.create(
                model=sel.value,
                messages=[{"role":"system","content":body.system},
                          {"role":"user","content":body.prompt}],
                max_tokens=body.max_tokens,
                temperature=0.4 if "deepseek" in sel.value else body.temperature,
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    full.append(delta); yield f"data: {json.dumps({'token':delta,'done':False})}\n\n"
            task_manager.complete(task.id, "".join(full))
            yield f"data: {json.dumps({'token':'','done':True,'model':sel.name,'task_id':task.id})}\n\n"
        except Exception as e:
            task_manager.fail(task.id, str(e))
            yield f"data: {json.dumps({'token':'','done':True,'error':str(e)})}\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream",
        headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no","Access-Control-Allow-Origin":"*"})

# ── MCP ───────────────────────────────────────────

@app.get("/mcp/servers",          dependencies=[Depends(verify_token)])
async def list_mcp():                return {"servers": _mcp_servers()}
@app.post("/mcp/servers/{name}/toggle", dependencies=[Depends(verify_token)])
async def toggle_mcp(name: str, body: McpToggleRequest):
    p = os.path.expanduser("~/.nanobot/config.json")
    if not os.path.exists(p): raise HTTPException(404,"Config not found")
    cfg = json.load(open(p))
    if name not in cfg.get("mcpServers",{}): raise HTTPException(404,f"{name} not found")
    if not body.enabled: cfg["mcpServers"][name]["disabled"] = True
    else: cfg["mcpServers"][name].pop("disabled",None)
    json.dump(cfg,open(p,"w"),indent=2)
    return {"status":"updated","name":name,"enabled":body.enabled}
@app.post("/mcp/servers/{name}/restart", dependencies=[Depends(verify_token)])
async def restart_mcp(name: str):    return {"status":"restart_requested","name":name}
@app.post("/auth/rotate",          dependencies=[Depends(verify_token)])
async def rotate():
    return {"token":create_token({"operator":"admin"}),
            "message":"Update C2_SECRET_KEY in AWS Secrets Manager and restart"}

# ── WEBSOCKET ─────────────────────────────────────

@app.websocket("/status/stream")
async def ws_stream(ws: WebSocket, token: str = ""):
    if SECRET_KEY != "LOCAL_DEV_SECRET_18790":
        try: jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        except: await ws.close(code=4001); return
        if ws.client and ws.client.host in ("127.0.0.1","::1"):
            await ws.close(code=4003); return
    await ws.accept(); active_ws.append(ws)
    log_cursor = 0; last_ping = time.time()
    try:
        full = _compressed_status(); new_logs, log_cursor = _logs_since(0)
        await ws.send_json({
            "type":"status","full":True,"data":full,
            "logs":new_logs[-20:],"log_cursor":log_cursor,
            "alerts":triggers.store.get_all(unread_only=True,limit=10),
            "alert_count":triggers.store.unread_count(),
            "situation":awareness.get_current_context(),
            "friday_stats":friday.stats(),
        })
        tracker.changed(ws, full)
        while True:
            await asyncio.sleep(3)
            current = _compressed_status(); changed = tracker.changed(ws, current)
            new_logs, log_cursor = _logs_since(log_cursor)
            if changed or new_logs:
                payload: dict = {"type":"status","full":False}
                if changed:  payload["data"] = current
                if new_logs: payload["logs"] = new_logs; payload["log_cursor"] = log_cursor
                await ws.send_json(payload)
            if time.time() - last_ping > 30:
                await ws.send_json({"type":"ping","ts":datetime.now().strftime("%H:%M:%S")})
                last_ping = time.time()
    except WebSocketDisconnect: pass
    finally:
        tracker.remove(ws)
        if ws in active_ws: active_ws.remove(ws)

# ── MAIN ──────────────────────────────────────────

if __name__ == "__main__":
    print("+----------------------------------------------+")
    print("|  LUMINA C2 v2.5.0 - FRIDAY ONLINE            |")
    print("|  COORDINATOR / RESEARCHER / WRITER           |")
    print("|  ANALYST / MONITOR / EXECUTOR                |")
    print("|  PERPLEXITY + OBSIDIAN + AWARENESS           |")
    print("|  WEB 4.0 - BROWSER MCP ACTIVE                |")
    print("|  OPERATOR: BOSS (BRENT WILF)                 |")
    print("|  MISSION:  $10K/MONTH BY MAY 9TH             |")
    print("+----------------------------------------------+")
    token = create_token({"operator": "admin"})
    print(f"\n[INIT] JWT TOKEN:\n{token}\n")
    uvicorn.run(app, host="0.0.0.0", port=C2_PORT)
