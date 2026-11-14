import { useState } from "react";

import { ThreadShell } from "@/components/thread/ThreadShell";
import { PaneWorkbench } from "@/components/workbench/PaneWorkbench";
import { transitionSession } from "@/components/thread/session-transition";
import { settings } from "@/dev/gallery/settings";
import { ComposerDraftStore } from "@/lib/composer-draft";
import { ThreadMessageCache } from "@/lib/thread-message-cache";
import { ClientProvider } from "@/providers/ClientProvider";
import { createStreamClient } from "@/tests/stream-client";

const goalSummary = new URLSearchParams(location.search).has("long-goal")
  ? "完成会话切换和目标状态界面的优化，统一明暗主题下的布局、文字、图标与交互，验证桌面和窄屏体验后提交代码并更新发布说明"
  : "Keep the composer stable";
export function installSessionTransitionPreviewApi() {
  const original = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = new URL(input instanceof Request ? input.url : String(input), location.href);
    if (url.origin !== location.origin || !url.pathname.startsWith("/api/")) return original(input, init);
    if (url.pathname === "/api/commands") return Response.json({ commands: [
      { command: "/cancel_goal", title: "Cancel goal", description: "Cancel the goal", icon: "square", lifecycle: "side_channel", accepts_args: false },
    ] });
    if (url.pathname.endsWith("/subagents")) return Response.json({ tasks: [] });
    if (url.pathname.endsWith("/webui-thread")) {
      const topic = decodeURIComponent(url.pathname.split("/")[3]).split(":")[1];
      return Response.json({ schemaVersion: 3, projection: "events", events: [
        { event: "user_message", chat_id: topic, projection_id: `${topic}-prompt`, turn_id: "fixture-turn", starts_turn: true, text: `Question for ${topic}` },
        { event: "message", chat_id: topic, projection_id: `${topic}-answer`, turn_id: "fixture-turn", text: `Answer for ${topic}\n\n` + "A long conversation stays at its reading position.\n\n".repeat(25) },
      ] });
    }
    return Response.json({}, { status: 404 });
  };
}

export function SessionTransitionFixture() {
  const [pendingCancel, setPendingCancel] = useState<{ chat_id: string; turn_id: string } | null>(null);
  const [{ client, receive, socket }] = useState(() => {
    const preview = createStreamClient((data) => {
      const frame = JSON.parse(data);
      if (frame.content === "/cancel_goal") setPendingCancel({ chat_id: frame.chat_id, turn_id: frame.turn_id });
    });
    for (const topic of ["goal", "together", "blocked"]) {
      preview.receive({ event: "goal_state", chat_id: topic, goal_state: {
        active: topic !== "blocked", status: topic === "blocked" ? "blocked" : "active",
        ui_summary: goalSummary,
        objective: "Verify session navigation with real components.\n\n" + "- Preserve drafts, reading position and usable header controls.\n".repeat(6),
        ...(topic === "blocked" ? { recap: "Waiting for a workspace permission decision." } : {}),
      } });
    }
    if (new URLSearchParams(location.search).has("preview")) {
      const send = preview.client.sendSystemCommand.bind(preview.client);
      preview.client.sendSystemCommand = (chatId, command) => send(chatId, command, 600_000);
    }
    return preview;
  });
  const [online, setOnline] = useState(true);
  const cancelPreview = new URLSearchParams(location.search).has("cancel-goal");
  const finishCancel = (success: boolean) => {
    if (!pendingCancel) return;
    if (success) {
      if (client.getGoalState(pendingCancel.chat_id)?.active) {
        receive({ event: "turn_end", chat_id: pendingCancel.chat_id, turn_id: "live-turn" });
      }
      receive({ event: "goal_state", chat_id: pendingCancel.chat_id, goal_state: { active: false } });
    }
    receive({ event: "message", ...pendingCancel, text: success ? "Goal cancelled." : "Could not save goal cancellation." });
    setPendingCancel(null);
  };
  const workbench = new URLSearchParams(location.search).has("workbench");
  const [topic, setTopic] = useState(new URLSearchParams(location.search).get("topic") ?? (workbench ? "goal" : "plain"));
  const [cache] = useState(() => new ThreadMessageCache(() => false));
  const [drafts] = useState(() => new ComposerDraftStore());
  const dark = new URLSearchParams(location.search).has("dark");
  document.documentElement.classList.toggle("dark", dark);
  return <ClientProvider client={client} token="fixture" webuiCapabilities={["webui.core.v1", "webui.subagents.v1"]}>
    <main className="thread-workspace flex min-w-0 flex-col overflow-hidden bg-background text-foreground" style={{ height: "100dvh" }} data-session={topic}>
      <nav aria-label="Sessions" className="flex shrink-0 flex-wrap gap-4 px-4 py-2 text-xs">
        {(workbench ? ["goal", "blocked"] : ["plain", "goal", "tasks", "together", "blocked", "cold"]).map(key => <button key={key} onClick={() => transitionSession(() => setTopic(key), !workbench && key !== topic)}>{key}</button>)}
        <button onClick={() => receive({ event: "goal_state", chat_id: topic, goal_state: {
          ...client.getGoalState(topic), active: false, status: "blocked", recap: "Waiting for a workspace permission decision.",
        } })}>Block goal</button>
        <button onClick={() => receive({ event: "goal_state", chat_id: topic, goal_state: { active: false } })}>Clear goal</button>
        <button onClick={() => {
          receive({ event: "goal_status", chat_id: topic, turn_id: "live-turn", status: "running", started_at: Date.now() / 1000 });
          receive({ event: "delta", chat_id: topic, turn_id: "live-turn", stream_id: "live", text: "Live reply continues" });
        }}>Stream reply</button>
        {cancelPreview ? <>
          <button disabled={!pendingCancel} onClick={() => finishCancel(true)}>Confirm cancellation</button>
          <button disabled={!pendingCancel} onClick={() => finishCancel(false)}>Fail cancellation</button>
          <button onClick={() => {
            if (online) client.close();
            else { client.connect(); socket.onopen?.(); }
            setOnline(!online);
          }}>{online ? "Disconnect" : "Reconnect"}</button>
        </> : null}
      </nav>
      {workbench ? <PaneWorkbench
        panes={["goal", "blocked"].map(key => ({ key, title: key }))} activePaneKey={topic} layout="columns"
        showLayoutControl={false} onActivatePane={setTopic} onAddPane={() => {}} onLayoutChange={() => {}} onPaneOrderChange={() => {}}
        renderPane={(pane, context) => <ThreadShell
          session={{ key: `websocket:${pane.key}`, channel: "websocket", chatId: pane.key, createdAt: null, updatedAt: null, preview: "" }}
          title={pane.title} hideHeaderTitle onToggleSidebar={() => {}} theme={dark ? "dark" : "light"}
          settingsSnapshot={settings} messageCache={cache} draftStore={drafts} emptyComposerVariant="thread"
          headerPortalTarget={context.headerPortalTarget} headerActive={context.active}
          composerPortalTarget={context.composerPortalTarget} composerActive={context.active} headerActions={context.headerActions}
        />}
      /> : <ThreadShell session={{ key: `websocket:${topic}`, channel: "websocket", chatId: topic, createdAt: null, updatedAt: null, preview: "" }}
        title={topic} hideHeaderTitle onToggleSidebar={() => {}} theme={dark ? "dark" : "light"}
        settingsSnapshot={settings} messageCache={cache} draftStore={drafts} emptyComposerVariant="thread" />}
    </main>
  </ClientProvider>;
}
