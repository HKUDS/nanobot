import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { ThreadViewport } from "@/components/thread/ThreadViewport";
import { PaneWorkbench } from "@/components/workbench/PaneWorkbench";
import { usePromptHistory } from "@/hooks/usePromptHistory";
import { fetchWebuiThread } from "@/lib/api";
import { projectThreadEvents } from "@/lib/thread-event-projection";
import type { UIMessage } from "@/lib/types";

const parameters = new URLSearchParams(location.search);
const railHistory: UIMessage[] = Array.from({ length: 5 }, (_, index) => [
  { id: `u${1995 + index}`, role: "user" as const, content: `Question ${1995 + index}`, createdAt: index + 1 },
  { id: `a${1995 + index}`, role: "assistant" as const, content: parameters.has("focus-links") && index === 4
    ? Array.from({ length: 45 }, (_, i) => `[Reference ${i}](https://example.test/ref${i})`).join("\n")
    : "A synthetic answer.\n\n".repeat(8), createdAt: index + 1 },
]).flat();

export function RailFixture() {
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
      panes={parameters.has("focus-links")
        ? [{ key: "rail", title: "Rail conversation" }, { key: "other", title: "Other conversation" }]
        : [{ key: "rail", title: "Rail conversation" }]} activePaneKey="rail" layout="columns" showLayoutControl={false}
      onActivatePane={() => {}} onAddPane={() => {}} onLayoutChange={() => {}} onPaneOrderChange={() => {}}
      renderPane={(_pane, context) => <>
        {viewport(context.composerPortalTarget !== undefined, context.navigationFrame)}
        {context.composerPortalTarget && createPortal(composer, context.composerPortalTarget)}
      </>}
    /> : viewport(false)}
  </main>;
}
