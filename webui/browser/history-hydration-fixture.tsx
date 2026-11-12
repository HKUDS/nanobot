import { useEffect, useRef, useState } from "react";

import { ThreadShell } from "@/components/thread/ThreadShell";
import { settings } from "@/dev/gallery/settings";
import { NanobotClient } from "@/lib/nanobot-client";
import type { ChatSummary, ConnectionStatus } from "@/lib/types";
import { ClientProvider } from "@/providers/ClientProvider";

const sessions: ChatSummary[] = ["a", "b"].map((suffix) => ({
  key: `websocket:nan311-${suffix}`,
  channel: "websocket",
  chatId: `nan311-${suffix}`,
  createdAt: null,
  updatedAt: null,
  preview: "",
}));

// Synthetic backend-boundary reproduction, not an original user recording.
export function HistoryHydrationFixture() {
  const [client] = useState(() => new NanobotClient({
    url: `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/nan311-fixture-ws`,
    reconnect: false,
  }));
  const [status, setStatus] = useState<ConnectionStatus>("idle");
  const [session, setSession] = useState(sessions[0]!);
  const receiptRef = useRef<HTMLOutputElement>(null);

  useEffect(() => {
    // Observers provide a wire-delivery barrier even when painting is paused.
    // They never consume transcript replay, project events, or supply body rows.
    const observers = sessions.map(({ chatId }) => client.onChat(chatId, (event) => {
      if (!receiptRef.current) return;
      const sequence = "turn_seq" in event ? event.turn_seq ?? "-" : "-";
      const turn = "turn_id" in event ? event.turn_id ?? "-" : "-";
      receiptRef.current.textContent = `${chatId}/${turn}/${event.event}/${sequence}`;
    }));
    const unsubscribe = client.onStatus(setStatus);
    client.connect();
    return () => {
      observers.forEach((dispose) => dispose());
      unsubscribe();
      client.close();
    };
  }, [client]);

  return <ClientProvider client={client} token="nan311-synthetic-fixture">
    <main className="thread-workspace flex min-w-0 flex-col overflow-hidden bg-background text-foreground" style={{ height: "100dvh" }}>
      <div className="shrink-0 border-b px-3 py-2 text-xs">
        <p>Synthetic NAN-311 history hydration fixture — not a user recording.</p>
        <nav aria-label="Synthetic conversations" className="flex gap-3">
          {sessions.map((candidate, index) => <button key={candidate.key} type="button"
            aria-pressed={candidate.key === session.key} onClick={() => setSession(candidate)}>
            Conversation {index === 0 ? "A" : "B"}
          </button>)}
        </nav>
        <output aria-label="Synthetic transport status">{status}</output>
        <output aria-label="Synthetic active conversation" className="ml-3">{session.chatId}</output>
        <output ref={receiptRef} aria-label="Synthetic frame receipt" className="sr-only">Awaiting frame</output>
      </div>
      {status === "open" && <ThreadShell
        session={session} sessions={sessions} title={`Synthetic ${session.chatId}`}
        onToggleSidebar={() => {}} settingsSnapshot={settings}
      />}
    </main>
  </ClientProvider>;
}
