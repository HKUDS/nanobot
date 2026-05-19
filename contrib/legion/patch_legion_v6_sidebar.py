#!/usr/bin/env python3
"""Patch: Legion V6 — agent badges + terminal portal for v0.2.0 Sidebar.

Targets (pre-compile, before hatch_build runs npm):
  - /app/webui/src/components/Sidebar.tsx → LegionRoster badges + LegionTerminal portal

Dual-target NOT required: WebUI .tsx patches are compiled into dist/,
only the /app/webui/src/ copy matters before the Vite build step.

Injections:
  1. Expanded react imports (createPortal, useCallback, useEffect, useRef)
  2. useClient import
  3. LegionRoster component (agent status badges)
  4. LegionTerminal component (log portal via createPortal)
  5. In Sidebar: showConsole/logs/activeTab state + event capture useEffect
  6. <LegionRoster onToggle /> between logo and search
  7. <LegionTerminal /> before </nav>
"""
from pathlib import Path

PATCH_LABEL = "legion-v6-sidebar"

SIDEBAR = Path("/app/webui/src/components/Sidebar.tsx")


# ── LegionRoster component (plain string -> single braces in output) ──
LEGION_ROSTER = """
/* ── LegionRoster: agent status badges ── */
const STATUS_COLORS: Record<string, string> = {
  online: "bg-emerald-500",
  offline: "bg-red-500",
  executing: "bg-blue-500 animate-pulse",
  blocked: "bg-amber-500",
  disconnected: "bg-red-500 animate-pulse",
};
const STATUS_LABELS: Record<string, string> = {
  online: "在线",
  offline: "离线",
  executing: "执行中",
  blocked: "阻塞",
  disconnected: "断连",
};
type AgentStatus = "online" | "offline" | "executing" | "blocked" | "disconnected";

function LegionRoster(props: {
  peers: Record<string, { id: string; name?: string }>;
  status: Record<string, string>;
  onToggleConsole?: () => void;
}) {
  const agents = Object.keys(props.peers).sort();
  const t = (s: string) => STATUS_LABELS[s] || s;
  return (
    <div
      className="flex flex-wrap items-center gap-x-2 gap-y-1 px-3 py-2 border-b border-border/40 bg-muted/10 cursor-pointer hover:bg-muted/20 transition-colors select-none"
      onClick={props.onToggleConsole}
      title="点击切换军团指挥中心"
    >
      <span className="text-[11px] text-muted-foreground/60 tracking-wider font-semibold">
        军团
      </span>
      {agents.map((key) => {
        const peer = props.peers[key] || { id: key };
        const st: AgentStatus =
          props.status[key] === "online"
            ? "online"
            : props.status[key] === "executing"
              ? "executing"
              : props.status[key] === "blocked"
                ? "blocked"
                : "offline";
        const color = STATUS_COLORS[st] || STATUS_COLORS.offline;
        return (
          <span
            key={key}
            className="flex items-center gap-1 text-[11px] font-semibold text-foreground/80"
            title={`${peer.name || key}: ${t(st)}`}
          >
            <span
              className={`inline-block h-[14px] w-[14px] rounded-full ${color} ring-1 ring-border/30`}
            />
            {peer.name || key}
          </span>
        );
      })}
    </div>
  );
}
"""

# ── LegionTerminal component (f-string — double braces become single in output) ──
LEGION_TERMINAL = f"""
/* ── LegionTerminal: log portal ── */
function LegionTerminal(props: {{
  show: boolean;
  logs: Record<string, string[]>;
  activeTab: string;
  setActiveTab: (t: string) => void;
  tabs: string[];
  onClose: () => void;
}}) {{
  if (!props.show) return null;
  const visibleLogs = props.logs[props.activeTab] || [];
  const TAB_LABELS: Record<string, string> = {{ all: "全部" }};
  const {{ tabs }} = props;
  return createPortal(
    <div className="fixed bottom-4 left-[288px] w-[540px] h-[460px]
                    bg-background border border-border rounded-lg
                    shadow-2xl z-[100] flex flex-col text-sm"
         style={{{{ fontFamily: "var(--font-mono, monospace)" }}}}>
      {{/* header */}}
      <div className="flex items-center justify-between px-3 py-2
                      border-b border-border bg-muted/50 rounded-t-lg shrink-0">
        <div className="flex items-center gap-2">
          <span className="inline-flex h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
          <span className="text-xs font-semibold text-foreground/80 tracking-wide">
            军团指挥中心
          </span>
          <span className="text-[10px] text-muted-foreground/60">
            {{props.logs.all?.length || 0}} 条记录
          </span>
        </div>
        <button
          onClick={{props.onClose}}
          className="text-muted-foreground/60 hover:text-foreground px-1.5 py-0.5 rounded text-sm leading-none"
          title="关闭">✕</button>
      </div>
      {{/* tab bar */}}
      <div className="flex items-center gap-1 px-2 py-1.5 border-b border-border/30 bg-muted/10 shrink-0">
        {{tabs.map((tab: string) => {{
          const isActive = props.activeTab === tab;
          const count = (props.logs[tab] || []).length;
          const label = TAB_LABELS[tab] || tab;
          return (
            <button key={{tab}}
              onClick={{() => props.setActiveTab(tab)}}
              className={{`px-2.5 py-1 text-[11px] font-semibold rounded transition-colors
                ${{isActive
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground/70 hover:text-foreground hover:bg-accent/30"}}`}}
            >
              {{label}}
              {{count > 0 && (
                <span className="ml-1 text-[9px] opacity-70">{{count}}</span>
              )}}
            </button>
          );
        }})}}
      </div>
      {{/* log body */}}
      <div className="flex-1 overflow-y-auto p-2 text-xs bg-background">
        {{visibleLogs.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-muted-foreground/25 gap-2">
            <span className="text-2xl">⚔️</span>
            <span className="text-[11px]">
              {{props.activeTab === "all" ? "等待军团信号…" : `${{TAB_LABELS[props.activeTab] || props.activeTab}} 暂无日志`}}
            </span>
          </div>
        ) : (
          visibleLogs.map((log: string, i: number) => (
            <div key={{i}} className="py-0.5 border-b border-border/10 last:border-0 break-all hover:bg-accent/5 transition-colors font-mono text-[11px] leading-relaxed text-muted-foreground/80">
              {{log}}
            </div>
          ))
        )}}
      </div>
    </div>,
    document.body
  );
}}
"""

# ── State + event capture (injected into Sidebar body) (plain string) ──
SIDEBAR_STATE = """
  /* ── Legion: console state ── */
  const { client } = useClient();
  const [showConsole, setShowConsole] = useState(false);
  const [allLogs, setAllLogs] = useState<string[]>([]);
  const [agentLogs, setAgentLogs] = useState<Record<string, string[]>>({});
  const [activeTab, setActiveTab] = useState("all");
  const [legionPeers, setLegionPeers] = useState<Record<string, { id: string; name?: string }>>({});
  const [legionStatus, setLegionStatus] = useState<Record<string, string>>({});

  /* derive logs + tabs dynamically */
  const agentIds = Object.keys(legionPeers).sort();
  const allTabs = ["all", ...agentIds];
  const logs: Record<string, string[]> = { all: allLogs, ...agentLogs };

  /* ── helper: push line to a named bin ── */
  function _pushLog(bin: string, line: string, max: number) {
    setAllLogs(prev => [...prev, line].slice(-500));
    if (bin !== "all") {
      setAgentLogs(prev => {
        const cur = prev[bin] || [];
        return { ...prev, [bin]: [...cur, line].slice(-max) };
      });
    }
  }

  /* ── Legion: event capture ── */
  useEffect(() => {
    return client.onAnyEvent((ev: any) => {
      const ts = new Date().toLocaleTimeString();
      const evType = (ev as any).event || (ev as any).type || "?";

      /* ── Handle legion roster/status updates ── */
      if ((evType === "legion_update" || evType === "cluster_update") && (ev as any).roster) {
        const roster = (ev as any).roster as Record<string, { id: string; name?: string }>;
        const data = (ev as any).data as Record<string, string> | undefined;
        setLegionPeers(prev => {
          const next = { ...prev };
          for (const [k, v] of Object.entries(roster)) {
            if (!next[k]) next[k] = v;
          }
          return next;
        });
        if (data) setLegionStatus(data);

        /* Per-agent status lines */
        if (data) {
          for (const [agent, status] of Object.entries(data)) {
            _pushLog(agent, `[${ts}] 状态  ${agent} = ${status}`, 150);
          }
        }
        return;  /* legion_update done — no generic line needed */
      }

      /* build detail line */
      let detail = "";
      if (typeof (ev as any).text === "string") {
        detail = (ev as any).text.slice(0, 120);
      } else if (typeof (ev as any).content === "string") {
        detail = (ev as any).content.slice(0, 120);
      } else {
        try { detail = JSON.stringify(ev).slice(0, 160); } catch (_) { detail = "?"; }
      }

      const line = `[${ts}] ${evType}  ${detail}`;

      /* route: squad relay events carry sender/target */
      const sender = (ev as any).sender as string | undefined;
      const tgt = (ev as any).target as string | undefined;

      _pushLog("all", line, 500);
      if (sender) _pushLog(sender, line, 150);
      if (tgt && tgt !== sender) _pushLog(tgt, line, 150);
    });
  }, [client]);
"""

# ── Terminal render portal (injected before </nav>) (plain string) ──
TERMINAL_RENDER = """
      {/* ── Legion: terminal portal ── */}
      <LegionTerminal
        show={showConsole}
        logs={logs}
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        tabs={allTabs}
        onClose={() => setShowConsole(false)}
      />
"""


def patch_sidebar():
    """Inject LegionRoster + LegionTerminal into Sidebar.tsx."""
    if not SIDEBAR.is_file():
        print(f"  [{PATCH_LABEL}] {SIDEBAR} not found — skip")
        return False

    content = SIDEBAR.read_text()
    ok = True

    # ── Injection 1: expand react imports ──
    anchor_import = 'import { useMemo, useState } from "react";'
    if anchor_import not in content:
        print(f"  [{PATCH_LABEL}] anchor import not found — skip")
        return False

    expanded_import = 'import { useEffect, useMemo, useState } from "react";'
    if expanded_import != anchor_import:
        # Only replace if not already expanded
        if "useEffect" not in content.split("\n")[0]:
            content = content.replace(anchor_import, expanded_import, 1)
            print(f"  [{PATCH_LABEL}] expanded react imports")
        else:
            print(f"  [{PATCH_LABEL}] react imports already expanded")

    # Add createPortal from react-dom (separate import)
    anchor_rd_import = 'import { useTranslation } from "react-i18next";'
    if anchor_rd_import in content and "createPortal" not in content:
        rd_addon = '\nimport { createPortal } from "react-dom";'
        content = content.replace(anchor_rd_import, anchor_rd_import + rd_addon, 1)
        print(f"  [{PATCH_LABEL}] added createPortal import from react-dom")
    elif "createPortal" not in content:
        print(f"  [{PATCH_LABEL}] useTranslation anchor for createPortal not found — skip")

    # ── Injection 2: useClient import ──
    anchor_usec = 'import { useTranslation } from "react-i18next";'
    if anchor_usec in content:
        usec_import = '\nimport { useClient } from "@/providers/ClientProvider";'
        if 'useClient' not in content:
            content = content.replace(anchor_usec, anchor_usec + usec_import, 1)
            print(f"  [{PATCH_LABEL}] added useClient import")
        else:
            print(f"  [{PATCH_LABEL}] useClient import already present")
    else:
        print(f"  [{PATCH_LABEL}] useTranslation anchor not found — skip import")

    # ── Injection 3: LegionRoster component (before Sidebar function) ──
    anchor_side_fn = "export function Sidebar("
    if "function LegionRoster" not in content:
        content = content.replace(anchor_side_fn, LEGION_ROSTER + "\n" + anchor_side_fn, 1)
        print(f"  [{PATCH_LABEL}] added LegionRoster component")
    else:
        print(f"  [{PATCH_LABEL}] LegionRoster already present")

    # ── Injection 4: LegionTerminal component (before Sidebar function) ──
    if "function LegionTerminal" not in content:
        content = content.replace(anchor_side_fn, LEGION_TERMINAL + "\n" + anchor_side_fn, 1)
        print(f"  [{PATCH_LABEL}] added LegionTerminal component")
    else:
        print(f"  [{PATCH_LABEL}] LegionTerminal already present")

    # ── Injection 5: state + event capture (after useState lines, before useMemo) ──
    anchor_state = 'const [query, setQuery] = useState("");'
    if anchor_state in content:
        if "/* ── Legion: console state ── */" not in content:
            content = content.replace(anchor_state, anchor_state + SIDEBAR_STATE, 1)
            print(f"  [{PATCH_LABEL}] added console state + event capture")
        else:
            print(f"  [{PATCH_LABEL}] console state already present")
    else:
        print(f"  [{PATCH_LABEL}] state anchor not found — skip state injection")
        ok = False

    # ── Injection 6: <LegionRoster /> between logo header and search area ──
    if "<LegionRoster " not in content:
        legion_roster_jsx = (
            '      <LegionRoster peers={legionPeers} status={legionStatus} onToggleConsole={() => setShowConsole(v => !v)} />'
        )
        # Primary anchor: this line opens the search block div
        anchor_search_div = '      <div className="space-y-1.5 px-2 pb-2">'
        if anchor_search_div in content:
            content = content.replace(
                anchor_search_div,
                legion_roster_jsx + "\n" + anchor_search_div,
                1
            )
            print(f"  [{PATCH_LABEL}] inserted <LegionRoster /> before search div")
        else:
            print(f"  [{PATCH_LABEL}] search div anchor not found — skip")
            ok = False
    else:
        print(f"  [{PATCH_LABEL}] <LegionRoster /> already in sidebar")

    # ── Injection 7: <LegionTerminal /> before </nav> ──
    anchor_nav_end = "    </nav>"
    if "<LegionTerminal " not in content:
        if anchor_nav_end in content:
            content = content.replace(anchor_nav_end, TERMINAL_RENDER + "\n" + anchor_nav_end, 1)
            print(f"  [{PATCH_LABEL}] inserted <LegionTerminal />")
        else:
            print(f"  [{PATCH_LABEL}] </nav> anchor not found — skip terminal render")
            ok = False
    else:
        print(f"  [{PATCH_LABEL}] <LegionTerminal /> already in sidebar")

    SIDEBAR.write_text(content)

    if ok:
        print(f"✅ [{PATCH_LABEL}] complete")
    else:
        print(f"⚠ [{PATCH_LABEL}] partial — some injections skipped")
    return ok


def main():
    ok = patch_sidebar()
    if not ok:
        print(f"❌ [{PATCH_LABEL}] failed (some targets missing) — check upstream changes")
        exit(1)


if __name__ == "__main__":
    main()
