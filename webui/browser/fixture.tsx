import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { createPortal } from "react-dom";
import { MessageBubble } from "@/components/MessageBubble";
import { AppsCatalogSettings, DEFAULT_CUSTOM_MCP_FORM } from "@/components/settings/system/AppsSettings";
import { ThreadMessages } from "@/components/thread/ThreadMessages";
import { ThreadViewport } from "@/components/thread/ThreadViewport";
import { PaneWorkbench } from "@/components/workbench/PaneWorkbench";
import { usePromptHistory } from "@/hooks/usePromptHistory";
import { ClientProvider } from "@/providers/ClientProvider";
import { NanobotClient } from "@/lib/nanobot-client";
import { fetchWebuiThread } from "@/lib/api";
import { projectThreadEvents } from "@/lib/thread-event-projection";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import { SettingsIcon } from "@/components/icons/product-icons";
import { initializeI18n } from "@/i18n";
import type { McpPresetInfo, UIMessage } from "@/lib/types";
import { SkeletonFixture } from "./skeleton-fixture";
import { installSkeletonPreviewApi, SkeletonAdditionsFixture } from "./skeleton-additions-fixture";
import { NewChatSkeletonFixture } from "./new-chat-skeleton-fixture";
import "../src/globals.css";
import { DiagramFixture } from "./diagram-fixture";
import { TypographyFixture } from "./typography-fixture";
import { HistoryBoundaryFixture } from "./history-boundary-fixture";

const history: UIMessage[] = [
  { id: "question", role: "user", content: "Earlier question", createdAt: 1_700_000_000_000 },
  { id: "answer", role: "assistant", content: "Earlier answer", createdAt: 1_700_000_001_000 },
];
const trace: UIMessage = {
  id: "trace", role: "tool", kind: "trace", content: "Earlier tool call", createdAt: 1_700_000_002_000,
};

function HistoryFixture() {
  const [open, setOpen] = useState(false);
  return <main>
    <button onClick={() => setOpen(!open)}>{open ? "Close history" : "Reopen history"}</button>
    <section aria-label="Persisted history">
      {open && <>
        <ThreadMessages messages={history} isStreaming={false} />
        <MessageBubble message={trace} />
      </>}
    </section>
  </main>;
}

function TallDialogFixture({ placement }: { placement: "center" | "bottom" }) {
  return <main aria-label="Background content" style={{ height: 240, overflowY: "auto" }}>
    <div style={{ minHeight: 1800 }}><Dialog>
      <DialogTrigger asChild><button>Open tall dialog</button></DialogTrigger>
      <DialogContent placement={placement}>
        <DialogTitle>Tall dialog</DialogTitle>
        <DialogDescription>All controls must remain reachable in a short viewport.</DialogDescription>
        {Array.from({ length: 30 }, (_, index) => <label key={index}>
          Field {index + 1}<input aria-label={`Field ${index + 1}`} style={{ display: "block", height: 40 }} />
        </label>)}
        <DialogClose asChild><button>Save tall dialog</button></DialogClose>
      </DialogContent>
    </Dialog></div>
  </main>;
}

const parameters = new URLSearchParams(location.search);
const railClient = new NanobotClient({ url: "ws://127.0.0.1:8765", reconnect: false });
const railHistory: UIMessage[] = Array.from({ length: 5 }, (_, index) => [
  { id: `u${1995 + index}`, role: "user" as const, content: `Question ${1995 + index}`, createdAt: index + 1 },
  { id: `a${1995 + index}`, role: "assistant" as const, content: "A synthetic answer.\n\n".repeat(8), createdAt: index + 1 },
]).flat();
function RailFixture() {
  const [messages, setMessages] = useState(parameters.has("real") ? [] : railHistory);
  const [version, setVersion] = useState(1);
  const [streaming, setStreaming] = useState(false);
  useEffect(() => {
    if (!parameters.has("real")) return;
    const controller = new AbortController();
    void fetchWebuiThread("fixture", "websocket:rail", { limit: 40, signal: controller.signal }).then((page) => {
      if (page && !controller.signal.aborted) setMessages(projectThreadEvents(page.events));
    });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (!streaming) return;
    let count = 0;
    const user: UIMessage = { id: "stream-user", role: "user", content: "Streaming question", createdAt: Date.now() };
    const timer = window.setInterval(() => {
      count++;
      setMessages((current) => [...current.filter((message) => message.id !== "stream-user" && message.id !== "stream-answer"), user,
        { id: "stream-answer", role: "assistant", content: "Streaming text. ".repeat(count), createdAt: user.createdAt + 1, isStreaming: count < 120 }]);
      if (count === 120) setStreaming(false);
    }, 16);
    return () => window.clearInterval(timer);
  }, [streaming]);
  const navigation = usePromptHistory(messages.length ? "websocket:rail" : null, version, messages);
  const composer = <div style={{ height: parameters.has("tall-composer") ? 240 : 100, border: "1px solid #ddd", borderRadius: 20, padding: 20 }}>Message nanobot</div>;
  const viewport = (external: boolean, navigationFrame?: HTMLElement | null) => <ThreadViewport
    messages={messages} isStreaming={streaming} conversationKey="websocket:rail"
    navigation={parameters.has("short") ? undefined : navigation}
    navigationFrame={navigationFrame} composer={external ? null : composer} />;
  return <main style={{ height: "100vh", display: "flex", flexDirection: "column" }}>
    {parameters.has("real") && <div>
      <button onClick={() => setVersion((value) => value + 1)}>Refresh index</button>
      <button onClick={() => setStreaming(true)} disabled={streaming}>{streaming ? "Streaming" : "Simulate stream"}</button>
    </div>}
    {parameters.has("workbench") ? <PaneWorkbench
      panes={[{ key: "rail", title: "Rail conversation" }]} activePaneKey="rail" layout="columns" showLayoutControl={false}
      onActivatePane={() => {}} onAddPane={() => {}} onLayoutChange={() => {}} onPaneOrderChange={() => {}}
      renderPane={(_pane, context) => <>
        {viewport(true, context.navigationFrame)}
        {context.composerPortalTarget && createPortal(composer, context.composerPortalTarget)}
      </>}
    /> : viewport(false)}
  </main>;
}
const unbrandedPlugin: McpPresetInfo = {
  name: "plugin-nanobot-workflows", display_name: "Nanobot Workflows", category: "Workflow",
  description: "Engineering workflows", docs_url: "", requires: "Project files", note: "", connection_summary: "",
  transport: "stdio", install_supported: false, installed: true, configured: true,
  enabled: true, available: true, status: "enabled", required_fields: [], source: "agent-plugin",
};
function AppsFixture() {
  const noop = () => {};
  return <main className="mx-auto max-w-4xl p-6"><AppsCatalogSettings
    cliApps={{ apps: [], installed_count: 0 }}
    mcpPresets={{ presets: [
      unbrandedPlugin,
      { ...unbrandedPlugin, name: "test-mcp", display_name: "Test MCP", source: "builtin", logo_url: "/missing-app-icon.svg" },
      { ...unbrandedPlugin, name: "brand-example", display_name: "Brand Example", source: "builtin", brand_color: "#5E6AD2" },
    ], installed_count: 3 }}
    cliAppsLoading={false} mcpPresetsLoading={false} query="" filter="ready"
    cliActionKey={null} mcpActionKey={null} mcpOAuthFlow={null} mcpOAuthPopupBlocked={false}
    mcpOAuthCallbackUrl="" mcpOAuthCompleting={false} mcpOAuthCallbackError={null}
    cliMessage={null} cliError={null} cliFocusName={null} mcpMessage={null} mcpError={null}
    mcpFieldValues={{}} customMcpForm={DEFAULT_CUSTOM_MCP_FORM} mcpConfigImport=""
    showBrandLogos={parameters.get("logos") !== "hidden"} requiresRestartPending={false}
    onQueryChange={noop} onFilterChange={noop} onCliAction={noop} onMcpAction={noop}
    onMcpOAuthConnect={noop} onMcpOAuthCancel={noop} onMcpOAuthOpen={noop}
    onMcpOAuthCallbackUrlChange={noop} onMcpOAuthComplete={noop} onDismissStatus={noop}
    onBackToChat={noop} onMcpFieldChange={noop} onCustomMcpFormChange={noop}
    onMcpConfigImportChange={noop} onSaveCustomMcp={noop} onImportMcpConfig={noop}
    onMcpToolsChange={noop}
  /></main>;
}
if (parameters.get("case") === "skeleton-additions") installSkeletonPreviewApi();
await initializeI18n();
createRoot(document.getElementById("root")!).render(<TooltipProvider>
  {parameters.get("case") === "typography"
    ? <ClientProvider client={railClient} token="fixture"><TypographyFixture /></ClientProvider>
    : parameters.get("case") === "history-boundary"
    ? <ClientProvider client={railClient} token="fixture" webuiCapabilities={["webui.prompt-navigation.v1"]}><HistoryBoundaryFixture local={parameters.has("local")} navigate={parameters.has("navigate")} /></ClientProvider>
    : parameters.get("case") === "diagrams"
    ? <DiagramFixture parameters={parameters} />
    : parameters.get("case") === "new-chat-skeleton"
    ? <ClientProvider client={railClient} token="fixture"><NewChatSkeletonFixture /></ClientProvider>
    : parameters.get("case") === "skeleton-additions"
    ? <ClientProvider client={railClient} token="fixture"><SkeletonAdditionsFixture /></ClientProvider>
    : parameters.get("case") === "skeleton"
    ? <ClientProvider client={railClient} token="fixture"><SkeletonFixture surface={parameters.get("surface") ?? "skills"} loading={parameters.has("loading")} /></ClientProvider>
    : parameters.get("case") === "apps"
    ? <ClientProvider client={railClient} token="fixture"><AppsFixture /></ClientProvider>
    : parameters.get("case") === "rail"
    ? <ClientProvider client={railClient} token="fixture" webuiCapabilities={["webui.prompt-navigation.v1"]}><RailFixture /></ClientProvider>
    : parameters.get("case") === "settings-icon"
    ? <Button variant="icon" size="icon" aria-label="Settings"><SettingsIcon className="h-4 w-4" /></Button>
    : parameters.get("case") === "history"
    ? <HistoryFixture />
    : <TallDialogFixture placement={parameters.get("placement") === "bottom" ? "bottom" : "center"} />}
</TooltipProvider>);
