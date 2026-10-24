import type { AppBridge } from "@modelcontextprotocol/ext-apps/app-bridge";
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import type { WebUIMutationTransport } from "@/lib/api";
import type { UIMessage } from "@/lib/types";

type ToolResult = Awaited<ReturnType<NonNullable<AppBridge["oncalltool"]>>>;
interface AppPayload {
  html: string;
  arguments: Record<string, unknown>;
  result: ToolResult;
}
interface AppHost {
  transport: WebUIMutationTransport;
  sessionKey: string;
}
const AppHostContext = createContext<AppHost | null>(null);

export function McpAppHostProvider({ host, children }: { host: AppHost | null; children: ReactNode }) {
  return <AppHostContext.Provider value={host}>{children}</AppHostContext.Provider>;
}

export function McpAppAttachments({ messages }: { messages: UIMessage[] }) {
  const host = useContext(AppHostContext);
  if (!host) return null;
  const apps = new Map<string, { title: string }>();
  for (const message of messages) {
    for (const event of message.toolEvents ?? []) {
      for (const raw of event.embeds ?? []) {
        if (!raw || typeof raw !== "object") continue;
        const embed = raw as Record<string, unknown>;
        if (embed.type !== "mcp_app" || typeof embed.app_id !== "string" || !/^[a-f0-9]{32}$/.test(embed.app_id)) continue;
        apps.set(embed.app_id, { title: String(embed.server_name ?? "MCP") });
      }
    }
  }
  return <>{[...apps].map(([id, app]) => <McpAppCard key={`${host.sessionKey}:${id}`} host={host} appId={id} title={app.title} />)}</>;
}

export function sandboxedMcpHtml(html: string): string {
  // A meta policy can only add restrictions; a later document policy cannot relax it.
  const policy = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'";
  return `<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="${policy}"><meta name="referrer" content="no-referrer"></head><body>${html}</body></html>`;
}

interface Approval {
  name: string;
  arguments: Record<string, unknown>;
  resolve: (approved: boolean) => void;
}

export function McpAppCard({ host, appId, title }: { host: AppHost; appId: string; title: string }) {
  const { t } = useTranslation();
  const [payload, setPayload] = useState<AppPayload | null>(null);
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState("");
  const [approval, setApproval] = useState<Approval | null>(null);
  const [height, setHeight] = useState(280);
  const frame = useRef<HTMLIFrameElement>(null);
  const approvalRef = useRef<Approval | null>(null);
  const mounted = useRef(true);
  const generation = useRef(0);
  const { transport: hostTransport, sessionKey } = host;

  useEffect(() => {
    mounted.current = true;
    generation.current += 1;
    setPayload(null);
    setApproval(null);
    setError("");
    setOpening(false);
    return () => { mounted.current = false; };
  }, [appId, hostTransport, sessionKey]);

  useEffect(() => {
    if (!payload || !frame.current?.contentWindow) return undefined;
    let active = true;
    let requestPending = false;
    let bridge: AppBridge | undefined;
    const start = async () => {
      const { AppBridge, PostMessageTransport } = await import("@modelcontextprotocol/ext-apps/app-bridge");
      if (!active || !frame.current?.contentWindow) return;
      const connection = new AppBridge(null, { name: "nanobot", version: "1" }, { serverTools: {} });
      bridge = connection;
      connection.oncalltool = async (params, extra) => {
        if (!active || requestPending) throw new Error("An app action is already awaiting approval");
        requestPending = true;
        try {
          const signal = extra.mcpReq.signal;
          const prepared = await hostTransport.requestMutation<{ approval_id: string; name: string; arguments: Record<string, unknown> }>(
            "mcp_apps.prepare", { app_id: appId, session_key: sessionKey, name: params.name, arguments: params.arguments ?? {} },
          );
          if (!active || signal.aborted) throw new Error("The app request was cancelled");
          let cancelApproval = () => {};
          const approved = await new Promise<boolean>((resolve) => {
            const item = { name: prepared.name, arguments: prepared.arguments, resolve };
            cancelApproval = () => resolve(false);
            signal.addEventListener("abort", cancelApproval, { once: true });
            approvalRef.current = item;
            setApproval(item);
          });
          signal.removeEventListener("abort", cancelApproval);
          approvalRef.current = null;
          if (active) setApproval(null);
          if (!active || signal.aborted) throw new Error("The app request was cancelled");
          return await hostTransport.requestMutation<ToolResult>("mcp_apps.confirm", {
            app_id: appId, session_key: sessionKey, approval_id: prepared.approval_id, approved,
          }, 120_000);
        } finally {
          requestPending = false;
        }
      };
      connection.oninitialized = () => {
        void connection.sendToolInput({ arguments: payload.arguments });
        void connection.sendToolResult({ ...payload.result, content: payload.result.content ?? [] });
      };
      connection.onsizechange = ({ height: requested }) => {
        if (active && typeof requested === "number" && Number.isFinite(requested)) setHeight(Math.max(180, Math.min(900, requested)));
      };
      connection.onerror = () => { if (active) setError(t("mcpApp.failed")); };
      const transport = new PostMessageTransport(frame.current.contentWindow, frame.current.contentWindow);
      await connection.connect(transport);
      if (active && frame.current) frame.current.srcdoc = sandboxedMcpHtml(payload.html);
    };
    void start().catch(() => { if (active) setError(t("mcpApp.failed")); });
    return () => {
      active = false;
      approvalRef.current?.resolve(false);
      approvalRef.current = null;
      void bridge?.close();
    };
  }, [appId, hostTransport, sessionKey, payload, t]);

  const open = async () => {
    const requestedGeneration = generation.current;
    setOpening(true);
    setError("");
    try {
      const next = await host.transport.requestMutation<AppPayload>("mcp_apps.open", { app_id: appId, session_key: host.sessionKey });
      if (mounted.current && generation.current === requestedGeneration) setPayload(next);
    } catch {
      if (mounted.current && generation.current === requestedGeneration) setError(t("mcpApp.unavailable"));
    } finally {
      if (mounted.current && generation.current === requestedGeneration) setOpening(false);
    }
  };

  return <section className="my-2 overflow-hidden rounded-xl border border-border bg-card" aria-label={t("mcpApp.label", { title })}>
    <div className="flex items-center justify-between gap-3 border-b border-border/60 px-4 py-3">
      <div className="min-w-0"><div className="truncate text-sm font-medium">{title}</div><div className="text-xs text-muted-foreground">{t("mcpApp.subtitle")}</div></div>
      {payload
        ? <Button size="sm" variant="ghost" onClick={() => { setPayload(null); setApproval(null); }}>{t("mcpApp.close")}</Button>
        : <Button size="sm" variant="outline" disabled={opening} onClick={() => void open()}>{t(opening ? "mcpApp.loading" : "mcpApp.open")}</Button>}
    </div>
    {error ? <p role="alert" className="px-4 py-3 text-sm text-destructive">{error}</p> : null}
    {approval ? <div className="border-b border-border bg-muted/50 p-4" role="group" aria-label={t("mcpApp.approval")}>
      <p className="mb-2 text-sm font-medium">{t("mcpApp.approval")}: {approval.name}</p>
      <pre className="mb-3 max-h-40 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(approval.arguments, null, 2)}</pre>
      <div className="flex gap-2"><Button size="sm" variant="outline" onClick={() => approval.resolve(false)}>{t("mcpApp.reject")}</Button><Button size="sm" onClick={() => approval.resolve(true)}>{t("mcpApp.approve")}</Button></div>
    </div> : null}
    {payload ? <iframe ref={frame} title={t("mcpApp.label", { title })} sandbox="allow-scripts" referrerPolicy="no-referrer" className="block w-full bg-white" style={{ height }} /> : null}
  </section>;
}
