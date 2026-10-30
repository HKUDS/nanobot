import { useCallback, useEffect, useState } from "react";

import { ThreadShell } from "@/components/thread/ThreadShell";
import { settings } from "@/dev/gallery/settings";
import { NanobotClient } from "@/lib/nanobot-client";
import { ThreadMessageCache } from "@/lib/thread-message-cache";
import { ClientProvider } from "@/providers/ClientProvider";

export function AnswerOrderFixture() {
  const [client] = useState(() => new NanobotClient({
    url: `ws://${location.host}/answer-order-socket`, reconnect: false,
  }));
  const [cache] = useState(() => new ThreadMessageCache(() => false));
  const [chatId, setChatId] = useState("answer-order");
  const [revision, setRevision] = useState(0);
  const [, setCompletedRevision] = useState(0);
  const onTurnEnd = useCallback(() => setCompletedRevision(revision), [revision]);
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
        settingsSnapshot={settings} messageCache={cache}
      />
    </main>
  </ClientProvider>;
}
