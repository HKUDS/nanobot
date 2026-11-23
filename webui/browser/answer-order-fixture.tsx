import { useCallback, useEffect, useState } from "react";

import { ThreadShell } from "@/components/thread/ThreadShell";
import { settings } from "@/dev/gallery/settings";
import { NanobotClient } from "@/lib/nanobot-client";
import { ThreadMessageCache } from "@/lib/thread-message-cache";
import { ClientProvider } from "@/providers/ClientProvider";

export function AnswerOrderFixture() {
  const [client] = useState(() => new NanobotClient({
    url: `ws://${location.host}/answer-order-socket`,
    reconnect: new URLSearchParams(location.search).get("reconnect") === "1",
  }));
  const [cache] = useState(() => new ThreadMessageCache(() => false));
  const [chatId, setChatId] = useState("answer-order");
  const [revision, setRevision] = useState(0);
  const [, setCompletedRevision] = useState(0);
  const onTurnEnd = useCallback(() => setCompletedRevision(revision), [revision]);
  const fixtureSettings = new URLSearchParams(location.search).get("sendable") === "1" ? {
    ...settings,
    agent: { ...settings.agent, model_preset: "default" },
    model_presets: [{
      name: "default", label: "Default", active: true, is_default: true,
      model: "gpt-5.4", provider: "openai", resolved_provider: "openai",
      max_tokens: 8192, context_window_tokens: 200_000, temperature: 0.1, reasoning_effort: null,
    }],
    model_call_order: ["default"],
  } : settings;
  useEffect(() => {
    client.connect();
    return () => client.close();
  }, [client]);
  return <ClientProvider client={client} token="fixture">
    <main className="thread-workspace flex min-w-0 flex-col overflow-hidden bg-background" style={{ height: "100dvh" }}>
      <nav className="flex gap-4 p-2" aria-label="Fixture controls">
        <button onClick={() => setChatId(chatId === "answer-order" ? "other-chat" : "answer-order")}>Switch topic</button>
        <button onClick={() => setRevision((value) => value + 1)}>Rebuild subscription</button>
      </nav>
      <ThreadShell
        session={{ key: `websocket:${chatId}`, channel: "websocket", chatId, createdAt: null, updatedAt: null, preview: "" }}
        title={chatId} onToggleSidebar={() => {}} onTurnEnd={onTurnEnd}
        settingsSnapshot={fixtureSettings} messageCache={cache}
      />
    </main>
  </ClientProvider>;
}
