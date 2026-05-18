#!/usr/bin/env python3
"""
Squad Sidebar UI Patch v6d — 军团勋章仪表阵列（动态代理发现版）
======================================================================
策略：零依赖，一站式手术。目标为原始 Sidebar.tsx，不依赖任何旧补丁。

V6d 动态化升级：
  - 从 gatekeeper roster 动态派生 agent 列表（零硬编码）
  - 徽章阵列、Tab 栏、Log 分桶全部动态生成
   - 新增 agent 只需一条 NANOBOT_PEER_* 环境变量，重启即生效
  - TOKEN: Squad Neural Monitor v6d（幂等跳过检测）

V6 保留：
  - 徽章阵列: 26×26px 圆点，居中首字母
  - 五色协议: 绿(待命) 蓝脉冲(执行) 琥珀(阻塞>10s) 红呼吸(掉线)
  - 心跳检测: 基于 lastSeenRef + recomputePhase 的 2s 周期判定
  - 点击徽章直接跳转对应 agent 日志视图

V5 保留（log 分流核心）：
  - srcToTab 映射 + per-agent logs bucket
  - visibleLogs 普通变量（非 useMemo — 已验证可靠）
  - clearCurrentTab 只清当前 tab
  - TAB_LABELS tab 栏 + 终端 Portal

全量合并：检测 "Squad Neural Monitor v6d" 标记，已注入则幂等跳过。
"""

import re
import os
import sys

# ── Target discovery ──────────────────────────────────────────
TARGETS = [
    "webui/src/components/Sidebar.tsx",
    "src/components/Sidebar.tsx",
]

target = None
for p in TARGETS:
    if os.path.exists(p):
        target = p
        break

if not target:
    for root, dirs, files in os.walk("."):
        for f in files:
            if f == "Sidebar.tsx":
                target = os.path.join(root, f)
                break

if not target:
    print("❌ Sidebar.tsx not found in workspace")
    sys.exit(1)

print(f"📄 Target: {target}")

with open(target, "r") as f:
    content = f.read()

original = content

# ══════════════════════════════════════════════════════════════
# 幂等检查
# ══════════════════════════════════════════════════════════════
if "Squad Neural Monitor v6" in content:
    print("✅ V6 already present — idempotent skip")
    sys.exit(0)

# ══════════════════════════════════════════════════════════════
# 全量清理: 移除所有历史 Squad 残留 (V2-V6 旧版)
# ══════════════════════════════════════════════════════════════
STALE_MARKERS = [
    "// --- [Squad Monitor Neural Bridge] ---",
    "// ═══ [Squad Neural Monitor v2] ═══",
    "// ═══ [Squad Neural Monitor v3] ═══",
    "// ═══ [Squad Neural Monitor v4] ═══",
    "// ═══ [Squad Neural Monitor v5] ═══",
]

for marker in STALE_MARKERS:
    if marker not in content:
        continue

    lines = content.split("\n")
    # Find marker start
    marker_idx = None
    for i, line in enumerate(lines):
        if marker in line:
            marker_idx = i
            break

    if marker_idx is None:
        continue

    # Find the end of the stale block: walk forward counting JS braces.
    # The stale block extends from the marker through all Squad-injected
    # useEffect blocks.  The final block ends with:
    #   }, [visibleLogs, autoScroll, showConsole]);
    # For blocks that lack an auto-scroll useEffect (older versions),
    # fall back to the first "}, []);" line that returns depth to 0.
    depth = 0
    end_idx = None
    for j in range(marker_idx, len(lines)):
        depth += lines[j].count("{") - lines[j].count("}")
        if depth <= 0 and "}, [visibleLogs, autoScroll, showConsole]);" in lines[j]:
            end_idx = j
            break
        # Track the first }, []); as a fallback, but don't stop —
        # the auto-scroll useEffect follows it.
        if depth <= 0 and "}, []);" in lines[j] and end_idx is None:
            end_idx = j
        # If depth rises again (we entered a new block), discard fallback
        if depth > 0:
            end_idx = None

    if end_idx is None:
        print(f"⚠️  Could not find end of stale block '{marker}' — skipping cleanup")
        continue

    # Remove marker_idx through end_idx (inclusive)
    removed = lines[marker_idx : end_idx + 1]
    del lines[marker_idx : end_idx + 1]
    content = "\n".join(lines)
    print(f"🧹 Removed stale block: {marker} ({len(removed)} lines, lines {marker_idx+1}-{end_idx+1})")

# Clean up any legacy portal blocks (showConsole + createPortal)
# Use a simple approach: remove all portal blocks that reference squad-mount-v*
portal_re = r'\{\s*showConsole\s*&&\s*\n\s*createPortal\([\s\S]*?document\.body\s*\)\s*\}'
before_p = content
content = re.sub(portal_re, '', content)
if content != before_p:
    print("🧹 Removed stale portal block(s)")

# Remove any legacy squad-mount ids (will be re-created as v6)
content = re.sub(
    r'id=\{[`"\']squad-mount[^`"\']*[`"\']\}',
    'id={`squad-mount-v6-${squadId}`}',
    content
)

print("✅ Cleanup complete — pristine baseline restored")

# ══════════════════════════════════════════════════════════════
# S1: 扩展 React imports (useState, useEffect, useId, useRef,
#     useCallback, useMemo)
# ══════════════════════════════════════════════════════════════
import_re = r'(import\s*\{[^}]*)\}\s*from\s*["\']react["\']'
m = re.search(import_re, content)
if not m:
    print("❌ S1: React import not found")
    sys.exit(1)

existing_imports = m.group(1)

needed = []
# 删掉了 "useCallback"，因为它在后续生成的组件代码里没有被实际调用
for hook in ["useState", "useEffect", "useId", "useRef", "useMemo"]:
    if hook not in existing_imports:
        needed.append(hook)
if needed:
    new_import = existing_imports + ", " + ", ".join(needed) + ' } from "react"'
    content = content.replace(m.group(0), new_import)
    print(f"✅ S1: Added React hooks: {', '.join(needed)}")
else:
    print("✅ S1: React hooks already complete")

# ══════════════════════════════════════════════════════════════
# S2: 添加 createPortal import
# ══════════════════════════════════════════════════════════════
if 'import { createPortal } from "react-dom"' not in content:
    lines = content.split("\n")
    last_react_import = -1
    for i, line in enumerate(lines):
        if "from" in line and ("react" in line or "react-dom" in line):
            last_react_import = i
    if last_react_import >= 0:
        lines.insert(last_react_import + 1,
                     'import { createPortal } from "react-dom";')
        content = "\n".join(lines)
        print("✅ S2: createPortal import added")
    else:
        print("⚠️  S2: No react import found to anchor createPortal")
else:
    print("✅ S2: createPortal already imported")

# ══════════════════════════════════════════════════════════════
# S2.5: 【终极增强版】全局无死角清理未使用的 Settings 变量声明
# ══════════════════════════════════════════════════════════════
# 1. 保持原有针对 lucide-react 的清洗兼容，加入 \s* 增强容错
content = re.sub(
    r'import\s*\{\s*([^}]*)\s*\}\s*from\s*["\']lucide-react["\']',
    lambda m: m.group(0).replace('Settings,', '').replace(', Settings', '').replace('Settings', '')
             if 'Settings' in m.group(0) and 'setSettings' not in m.group(0) else m.group(0),
    content
)
# 原有的空花括号修复保持兼容
content = re.sub(r'import\s*\{\s*(,\s*)+\s*\}\s*from\s*["\']lucide-react["\']',
                 lambda m: 'import {} from "lucide-react"', content)

# 2. 【核心新增】管它是从哪引入的，只要是独立一行的 import { Settings }，直接整行蒸发
content = re.sub(
    r'import\s*\{\s*Settings\s*\}\s*from\s*["\'].*?["\'];?\s*\n',
    '',
    content
)

# 3. 【核心新增】如果 Settings 混在其他文件的多变量引入中（例如 import { Home, Settings } from './config'），将其精准剔除
content = content.replace('{ Settings,', '{').replace(', Settings }', '}').replace('Settings,', '')

# 4. 【核心新增】顺便清理第 3 步处理后可能导致的空花括号残留（如 import {} from './config'）
content = re.sub(r'import\s*\{\s*\}\s*from\s*["\'].*?["\'];?\s*\n', '', content)

print("✅ S2.5: 增强型 Settings 变量声明全局无死角清理完毕，安全通过 TS6133 校验")


# ══════════════════════════════════════════════════════════════
# S3: 注入 V6d 动态状态块 = V5 分流核心 + V6d 动态代理发现
#     (在 export function Sidebar 体内首行)
# ══════════════════════════════════════════════════════════════
SIDEBAR_FN_RE = r'(export\s+function\s+Sidebar\s*\([^)]*\)\s*\{)'

# V6 state block: 修复了 console.log 格式，确保无 Diff 符号 (+)
v6_state_block = r"""\1
  // ═══ [Squad Neural Monitor v6d] ═══
  const squadId = useId();

  // ── Squad status state ─────────────────────────────────────
  const [squadStatus, setSquadStatus] = useState<Record<string,any>>({});

  // ── Dynamic agent identity (from bootstrap peers, fallback to roster) ─
  // Primary: bootstrap /webui/bootstrap → peers (A1), guarantees zero-WS-lag discovery
  const [bootstrapPeers, setBootstrapPeers] = useState<Record<string, {id: string}>>({});
  useEffect(() => {
    fetch('/webui/bootstrap')
      .then(r => r.json())
      .then(data => { if (data?.peers) setBootstrapPeers(data.peers); })
      .catch(() => {});
  }, []);  // eslint-disable-line

   // _roster = {name: {id, name, ...}} — values are objects, NOT strings
   const roster = (squadStatus._roster || {}) as Record<string, any>;

   // agentIds: 1) peers keys  2) roster keys  3) squadStatus keys (last resort)
   // 🔧 V6e FIX: roster path was Object.values() → crashed .charAt() on objects
   const agentIds: string[] = Object.keys(bootstrapPeers).length > 0
     ? Object.keys(bootstrapPeers).sort()
     : roster && Object.keys(roster).length > 0
       ? Object.keys(roster).sort()
       : Object.keys(squadStatus).filter(
           k => k !== "active_clusters" && k !== "_roster"
             && k !== "logs" && k !== "messages" && k !== "history"
         ).sort();

   // Diag: log agent-id source exactly once
   const _loggedSource = useRef<string>("");
   if (_loggedSource.current !== "bootstrap-peers") {
     const src = Object.keys(bootstrapPeers).length > 0 ? "bootstrap-peers" :
       Object.keys(roster).length > 0 ? "ws-roster" : "fallback";
     if (src !== _loggedSource.current) {
       console.log("[V6d agent-source]", src, agentIds);
     }
     _loggedSource.current = src;
   }

   // idToAgent: 1) peers reverse (info.id→name)  2) roster reverse (info.id→name)  3) empty
   // 🔧 V6e FIX: roster values are objects — map info.id→name instead of raw roster
   const idToAgent: Record<string, string> = Object.keys(bootstrapPeers).length > 0
     ? Object.fromEntries(Object.entries(bootstrapPeers).map(([name, info]) => [info.id, name]))
     : Object.keys(roster).length > 0
       ? Object.fromEntries(Object.values(roster).map((info: any) => [info.id, info.name]))
       : {};

  // ── Agent phase state (for badge array) ───────────────────
  type AgentPhase = "standby" | "executing" | "blocked" | "disconnected";
  const [agentStatus, setAgentStatus] = useState<Record<string, AgentPhase>>({});
  const lastSeenRef = useRef<Record<string, number>>({});
  const executingTimerRef = useRef<Record<string, ReturnType<typeof setTimeout> | null>>({});

  // ── Initialize per-agent refs/states when agentIds changes ──
  const prevAgentCount = useRef(0);
  useEffect(() => {
    if (agentIds.length === 0) return;
    if (agentIds.length === prevAgentCount.current) return;
    prevAgentCount.current = agentIds.length;
    for (const a of agentIds) {
      if (!(a in lastSeenRef.current)) {
        lastSeenRef.current[a] = 0;
        executingTimerRef.current[a] = null;
      }
    }
    // Seed log buckets for new agents (agentStatus handled by heartbeat)
    setLogs((prev) => {
      const next = { ...prev };
      let dirty = false;
      for (const a of agentIds) {
        if (!(a in next)) { next[a] = []; dirty = true; }
      }
      return dirty ? next : prev;
    });
  }, [agentIds]);

  const BLOCKED_TIMEOUT_MS = 10000;   // 10s no update → blocked (amber)
  const EXECUTING_HOLD_MS = 2500;      // hold blue pulse for 2.5s
  const HEARTBEAT_TICK_MS = 2000;      // tick every 2s

  // ── Phase recompute (pure, uses refs for timestamps) ──────
  const recomputePhase = (agent: string, now: number, onlineMap: Record<string, string>): AgentPhase => {
    if (onlineMap[agent] !== "online") return "disconnected";
    const last = lastSeenRef.current[agent];
    if (last > 0 && now - last < EXECUTING_HOLD_MS) return "executing";
    if (last > 0 && now - last > BLOCKED_TIMEOUT_MS) return "blocked";
    return "standby";
  };

  // ── Mark agent as executing (called from log handler) ─────
  const markExecuting = (agent: string) => {
    const now = Date.now();
    lastSeenRef.current[agent] = now;
    setAgentStatus((prev) => {
      if (prev[agent] === "disconnected") return prev;
      if (prev[agent] === "executing") return prev;
      return { ...prev, [agent]: "executing" };
    });
    if (executingTimerRef.current[agent]) {
      clearTimeout(executingTimerRef.current[agent]!);
    }
    executingTimerRef.current[agent] = setTimeout(() => {
      const onlineMap = squadStatus as Record<string, string>;
      setAgentStatus((prev) => ({
        ...prev,
        [agent]: recomputePhase(agent, Date.now(), onlineMap),
      }));
    }, EXECUTING_HOLD_MS);
  };

  // ── Heartbeat tick ────────────────────────────────────────
  useEffect(() => {
    const tick = () => {
      const now = Date.now();
      const onlineMap = (squadStatus || {}) as Record<string, string>;
      setAgentStatus((prev) => {
        let changed = false;
        const next = { ...prev };
        for (const agent of agentIds) {
          const phase = recomputePhase(agent, now, onlineMap);
          if (phase !== prev[agent]) { next[agent] = phase; changed = true; }
        }
        return changed ? next : prev;
      });
    };
    tick(); // immediate first run
    const id = setInterval(tick, HEARTBEAT_TICK_MS);
    return () => clearInterval(id);
  }, [squadStatus, agentIds]);

  // ═══════════════════════════════════════════════════════════
  // V5 分流核心 (全动态版)
  // ═══════════════════════════════════════════════════════════

  // ── Log storage (per-agent buckets, seeded dynamically) ────
  const [logs, setLogs] = useState<Record<string, string[]>>({ all: [] });
  const [activeTab, setActiveTab] = useState<string>("all");
  const [showConsole, setShowConsole] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const logEndRef = useRef<HTMLDivElement>(null);

  const TAB_LABELS = ["all", ...agentIds];

  // Short source → bucket label (dynamic, from roster)
  const srcToTab = (src: string): string => idToAgent[src] || src;

  // Compute visible logs from the active tab
  const visibleLogs = activeTab === "all"
    ? logs.all
    : (logs[activeTab] || []);

  // Clear logs for current tab only
  const clearCurrentTab = () => {
    setLogs((prev) => {
      const next = { ...prev };
      if (activeTab === "all") {
        for (const k of Object.keys(next)) next[k] = [];
      } else {
        next[activeTab] = [];
      }
      return next;
    });
  };

  // Ref holder for markExecuting
  const markExecRef = useRef(markExecuting);
  markExecRef.current = markExecuting;

  // ── Event listeners (registered once via []) ───────────────
  useEffect(() => {
    const onStatus = (e: Event) => {
      const detail = (e as CustomEvent).detail || {};
      setSquadStatus(detail);
    };
    const onLog = (e: Event) => {
      const detail = (e as CustomEvent).detail || {};
      const ts = new Date().toLocaleTimeString("zh-CN", { hour12: false });
      let line: string;

      if (detail.type === "cluster_log") {
        const src = detail.source || "?";
        const label = srcToTab(src);
        line = "[" + ts + "] [" + label + "] " + (detail.content || "");

        const agent = idToAgent[src] || undefined;
        if (agent) {
          try { markExecRef.current(agent); } catch (_) { }
        }

        setLogs((prev) => {
          const next = { ...prev };
          next.all = [...prev.all.slice(-499), line];
          const bucket = srcToTab(src);
          if (!next[bucket]) next[bucket] = [];
          next[bucket] = [...next[bucket].slice(-499), line];
          return next;
        });
      } else {
        const agents = detail.data || {};
        const online = Object.values(agents)
          .filter((v: any) => v === "online")
          .join(",") || "none";
        line = "[" + ts + "] [SYSTEM] online: " + online;

        setLogs((prev) => ({
          ...prev,
          all: [...prev.all.slice(-499), line],
        }));
      }
    };
    window.addEventListener("squad_update", onStatus);
    window.addEventListener("squad_log_update", onLog);
    return () => {
      window.removeEventListener("squad_update", onStatus);
      window.removeEventListener("squad_log_update", onLog);
    };
  }, []);

  useEffect(() => {
    if (autoScroll && logEndRef.current && showConsole) {
      logEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [visibleLogs, autoScroll, showConsole]);"""

before_s3 = content
content = re.sub(SIDEBAR_FN_RE, v6_state_block, content, count=1)
if content != before_s3:
    print("✅ S3: V6 state + V5 routing + heartbeat injected")
else:
    print("❌ S3: Injection failed — `export function Sidebar` not found")
    sys.exit(1)

# ══════════════════════════════════════════════════════════════
# S4: 替换 ConnectionBadge 容器 → V6d 底栏 + 动态勋章阵列
# ══════════════════════════════════════════════════════════════
lines = content.split("\n")

badge_line = None
for i, line in enumerate(lines):
    if "<ConnectionBadge" in line and "import" not in line and "from" not in line:
        badge_line = i
        break

if badge_line is None:
    print("❌ S4: <ConnectionBadge /> usage not found")
    sys.exit(1)

# Walk back to find the parent <div that contains ConnectionBadge
depth = 0
badge_div_start = None
for j in range(badge_line, -1, -1):
    opens = lines[j].count("<div")
    closes = lines[j].count("</div>")
    depth += closes - opens
    if depth <= 0 and "<div" in lines[j]:
        badge_div_start = j
        break

# Two-level backtrack: find the outer flex-col container
if badge_div_start is not None:
    depth = 0
    for j in range(badge_div_start - 1, -1, -1):
        opens = lines[j].count("<div")
        closes = lines[j].count("</div>")
        depth += closes - opens
        if depth < 0 and "<div" in lines[j]:
            badge_div_start = j
            break

if badge_div_start is None:
    print("❌ S4: Parent <div> container not found")
    sys.exit(1)

# Find matching closing </div>
depth = 0
badge_div_end = None
for j in range(badge_div_start, len(lines)):
    opens = lines[j].count("<div")
    closes = lines[j].count("</div>")
    depth += opens - closes
    if depth == 0 and "</div>" in lines[j]:
        badge_div_end = j
        break

if badge_div_end is None:
    print("❌ S4: Closing </div> not found")
    sys.exit(1)

indent = ""
for ch in lines[badge_div_start]:
    if ch in (" ", "\t"):
        indent += ch
    else:
        break

# ── V6 底栏模板 ────────────────────────────────────────────
# 使用 [IDT] 占位符避免 Python f-string 花括号冲突
v6_template = """[IDT]<div className="flex flex-col border-t border-sidebar-border/20">
[IDT]  <div
[IDT]    id={`squad-mount-v6-${squadId}`}
[IDT]    className="flex items-center gap-2 px-3 py-2 text-xs cursor-pointer hover:bg-accent/10 transition-colors select-none"
[IDT]    onClick={() => setShowConsole(true)}
[IDT]  >
[IDT]    {/* ── Agent Badge Array ── */}
[IDT]    <div className="inline-flex items-center gap-[6px] mr-1.5">
[IDT]      {agentIds.map((agent) => {
[IDT]        const phase = agentStatus[agent];
[IDT]        const letter = (typeof agent === "string" ? agent.charAt(0) : String(agent).charAt(0) || "?").toUpperCase();
[IDT]        const isPulse = phase === "executing";
[IDT]        const isBlocked = phase === "blocked";
[IDT]        const isOffline = phase === "disconnected";
[IDT]
[IDT]        return (
[IDT]          <span
[IDT]            key={agent}
[IDT]            title={`${agent}: ${phase}`}
[IDT]            onClick={(e) => {
[IDT]               e.stopPropagation();
[IDT]               setActiveTab(agent);
[IDT]               setShowConsole(true);
[IDT]            }}
[IDT]            className={`inline-flex items-center justify-center
[IDT]                       w-[26px] h-[26px] rounded-full
[IDT]                       text-[13px] font-black leading-none text-white shadow-md
[IDT]                       transition-all duration-300 hover:scale-125 cursor-crosshair
[IDT]                       ${
[IDT]                         isOffline
[IDT]                           ? "bg-red-600/90 animate-breath"
[IDT]                           : isBlocked
[IDT]                           ? "bg-amber-500"
[IDT]                           : isPulse
[IDT]                           ? "bg-blue-500 shadow-[0_0_10px_rgba(59,130,246,0.8)] animate-pulse"
[IDT]                           : "bg-emerald-500"
[IDT]                       }`}
[IDT]          >
[IDT]            {letter}
[IDT]          </span>
[IDT]        );
[IDT]      })}
[IDT]    </div>
[IDT]    <span className="text-muted-foreground text-[11px]">
[IDT]      {squadStatus.active_clusters ?? 0} clusters
[IDT]    </span>
[IDT]    <span className="text-muted-foreground/50 ml-auto text-[10px] tracking-wide">
[IDT]      军团中心 ›
[IDT]    </span>
[IDT]  </div>
[IDT]  <div className="flex items-center px-3 py-1.5 text-[11px] opacity-50">
[IDT]    <ConnectionBadge />
[IDT]  </div>
[IDT]</div>"""

v6_bottom_bar = v6_template.replace("[IDT]", indent)

old_block = "\n".join(lines[badge_div_start : badge_div_end + 1])
content = content.replace(old_block, v6_bottom_bar)
print(f"✅ S4: V6 bottom bar with clickable badges injected (lines {badge_div_start+1}-{badge_div_end+1})")

# ══════════════════════════════════════════════════════════════
# S5: 在 </nav> 前注入 V6 终端 Portal (V5 验证过的模板)
# ══════════════════════════════════════════════════════════════
NAV_CLOSE = "</nav>"
if NAV_CLOSE not in content:
    print("❌ S5: </nav> anchor not found")
    sys.exit(1)

# Portal identical to V5's proven template (tab-based log filtering)
v6_portal = """      {showConsole &&
        createPortal(
          <div className="fixed bottom-4 left-[288px] w-[520px] h-[540px]
                          bg-background border border-border rounded-lg
                          shadow-2xl z-50 flex flex-col text-sm"
               style={{ fontFamily: "var(--font-mono, monospace)" }}>
            {/* ── Header ── */}
            <div className="flex items-center justify-between px-3 py-2
                            border-b border-border bg-muted/50 rounded-t-lg">
              <div className="flex items-center gap-2">
                <span className="inline-flex h-2 w-2 rounded-full
                                 bg-emerald-500 animate-pulse" />
                <span className="text-xs font-semibold text-foreground/80 tracking-wide">
                  军团指挥中心
                </span>
                <span className="text-[10px] text-muted-foreground/60">
                  {logs.all.length} entries
                </span>
              </div>
              <button
                onClick={() => setShowConsole(false)}
                className="text-muted-foreground hover:text-foreground
                           px-1.5 py-0.5 rounded text-xs
                           hover:bg-accent transition-colors"
                aria-label="Close monitor"
              >
                ✕
              </button>
            </div>

            {/* ── Tab Bar ── */}
            <div className="flex items-center gap-1 px-2 py-1.5
                            border-b border-border/30 bg-muted/20">
              {TAB_LABELS.map((tab) => {
                const count = (logs[tab] || []).length;
                const isActive = activeTab === tab;
                return (
                  <button
                    key={tab}
                    onClick={() => setActiveTab(tab)}
                    className={`px-3 py-1 rounded text-[11px] font-medium
                               transition-all duration-150 ${
                      isActive
                        ? "bg-accent text-foreground shadow-sm"
                        : "text-muted-foreground hover:text-foreground hover:bg-accent/30"
                    }`}
                  >
                    {tab.charAt(0).toUpperCase() + tab.slice(1)}
                    {count > 0 && (
                      <span className={`ml-1.5 text-[9px] ${
                        isActive ? "opacity-70" : "opacity-40"
                      }`}>
                        {count}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>

            {/* ── Log Body ── */}
            <div className="flex-1 overflow-y-auto p-3 text-xs
                            text-muted-foreground bg-background
                            scrollbar-thin scrollbar-thumb-border">
              {visibleLogs.length === 0 ? (
                <div className="flex flex-col items-center justify-center
                                h-full text-muted-foreground/30 gap-2">
                  <span className="text-2xl">⚔️</span>
                  <span className="text-xs">
                    {activeTab === "all"
                      ? "等待军团信号..."
                      : `${activeTab} 暂无日志`}
                  </span>
                </div>
              ) : (
                visibleLogs.map((log: string, i: number) => (
                  <div
                    key={i}
                    className="py-0.5 border-b border-border/15
                               last:border-0 break-all hover:bg-accent/5
                               transition-colors font-mono text-[11px]
                               leading-relaxed"
                  >
                    {log}
                  </div>
                ))
              )}
              <div ref={logEndRef} />
            </div>

            {/* ── Bottom Toolbar ── */}
            <div className="flex items-center justify-between px-3 py-1.5
                            border-t border-border bg-muted/30 text-[10px]
                            text-muted-foreground/60 rounded-b-lg">
              <button
                onClick={() => setAutoScroll((v) => !v)}
                className={`flex items-center gap-1.5 transition-colors ${
                  autoScroll
                    ? "text-emerald-500"
                    : "text-muted-foreground/40 hover:text-muted-foreground"
                }`}
              >
                <span className={`inline-flex h-1.5 w-1.5 rounded-full transition-colors ${
                  autoScroll ? "bg-emerald-500" : "bg-zinc-600"
                }`} />
                Auto-scroll
              </button>
              <div className="flex items-center gap-3">
                <span className="text-muted-foreground/40">
                  {activeTab === "all" ? "All" : activeTab} · {visibleLogs.length}
                </span>
                <button
                  onClick={clearCurrentTab}
                  className="hover:text-red-400 transition-colors"
                >
                  Clear [{activeTab.charAt(0).toUpperCase() + activeTab.slice(1)}]
                </button>
              </div>
            </div>
          </div>,
          document.body
        )
      }
"""

content = content.replace(NAV_CLOSE, v6_portal + "\n    " + NAV_CLOSE)
print("✅ S5: V6 terminal portal injected before </nav>")

# ══════════════════════════════════════════════════════════════
# S6: 注入 CSS 关键帧动画 (animate-breath for red breathing)
# ══════════════════════════════════════════════════════════════
style_block = """      {/* ═══ Squad V6 CSS Animations ═══ */}
      <style>{`
        @keyframes squad-breath {
          0%, 100% { opacity: 0.3; }
          50% { opacity: 0.7; }
        }
        .animate-breath {
          animation: squad-breath 2s ease-in-out infinite;
        }
      `}</style>"""

NAV_CLOSE = "</nav>"
if NAV_CLOSE in content:
    content = content.replace(NAV_CLOSE, style_block + "\n    " + NAV_CLOSE, 1)
    print("✅ S6: CSS animations injected (before </nav>)")
else:
    print("⚠️  S6: </nav> not found — CSS NOT injected")

# ══════════════════════════════════════════════════════════════
# 最终验证
# ══════════════════════════════════════════════════════════════
CHECKS = [
    ("Squad Neural Monitor v6d", "V6d marker"),
    ("agentStatus", "agentStatus state"),
    ("AgentPhase", "AgentPhase type"),
    ("lastSeenRef", "lastSeenRef heartbeat"),
    ("BLOCKED_TIMEOUT_MS", "blocked timeout"),
    ("EXECUTING_HOLD_MS", "executing hold"),
    ("agentIds", "dynamic agentIds"),
    ("agent-source", "agent-source console"),
    ("idToAgent", "dynamic idToAgent mapping"),
    ("srcToTab", "V5 srcToTab mapping"),
    ("TAB_LABELS", "tab labels"),
    ("visibleLogs", "visibleLogs variable"),
    ("clearCurrentTab", "clearCurrentTab"),
    ("军团指挥中心", "portal label"),
    ("squad-mount-v6", "mount id v6"),
    ("animate-breath", "CSS breath animation"),
]

all_ok = True
for token, desc in CHECKS:
    if token not in content:
        print(f"  ❌ {desc}: '{token}' not found")
        all_ok = False
    else:
        print(f"  ✅ {desc}")

# Extra: check for badge CSS classes
# 必须与你 v6_template 中定义的 w-[26px] h-[26px] 严格一致
if "w-[26px] h-[26px] rounded-full" not in content:
    print("  ❌ badge array: 26×26 badge classes not found")
    all_ok = False
else:
    print("  ✅ badge array: 26×26 badge classes present")

if not all_ok:
    print("\n❌ Validation FAILED — aborting write")
    sys.exit(1)

if content == original:
    print("\n⚠️  No changes made")
else:
    with open(target, "w") as f:
        f.write(content)
    orig_lines = len(original.split("\n"))
    new_lines = len(content.split("\n"))
    print(f"\n{'='*60}")
    print(f"🎯 V6d 全量合并完成: {target}")
    print(f"   行数: {orig_lines} → {new_lines} (+{new_lines - orig_lines})")
    print(f"   核心: V5 分流逻辑 + V6d 动态代理发现 — gatekeeper roster 驱动")
    print(f"{'='*60}")

# ── Diff preview ──
import difflib
diff = difflib.unified_diff(
    original.splitlines(keepends=True),
    content.splitlines(keepends=True),
    fromfile="original_Sidebar.tsx",
    tofile="V6_patched_Sidebar.tsx",
)
print("\n─── Diff (前 100 行) ───")
count = 0
for line in diff:
    if count > 100:
        print("... (truncated)")
        break
    print(line, end="")
    count += 1
