import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { ThreadViewport } from "@/components/thread/ThreadViewport";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ThreadReadingStateStore } from "@/lib/thread-reading-state";
import type { UIMessage } from "@/lib/types";
import { initializeI18n } from "@/i18n";
import "../src/globals.css";

const parameters = new URLSearchParams(location.search);
const a: UIMessage[] = Array.from({ length: 300 }, (_, index) => ({
  id: `a-${index}`, role: "user", content: `A message ${index}`, createdAt: index,
  turnId: `a-turn-${index}`, turnSeq: index,
}));
const b: UIMessage[] = Array.from({ length: 14 }, (_, index) => ({
  id: `b-${index}`, role: "user", content: `B message ${index}`, createdAt: index,
}));

function ReadingFixture() {
  const [store] = useState(() => new ThreadReadingStateStore());
  const [selected, setSelected] = useState("a");
  const [rendered, setRendered] = useState("a");
  const [ready, setReady] = useState(true);
  const [mounted, setMounted] = useState(true);
  const [replayed, setReplayed] = useState(false);
  const [bottomSignal, setBottomSignal] = useState(0);
  const messages = rendered === "a"
    ? replayed ? a.map((message, index) => ({ ...message, id: `replayed-${index}` })) : a
    : b;
  const select = (key: string) => { setSelected(key); setRendered(key); setReady(true); };
  return <main style={{ height: "100vh", display: "flex", flexDirection: "column" }}>
    <nav className="flex gap-4">
      <button onClick={() => select("a")}>Select A</button>
      <button onClick={() => select("b")}>Select B</button>
      <button onClick={() => { setSelected("a"); setReady(false); }}>Select A pending</button>
      <button onClick={() => { setRendered("a"); setReady(true); }}>Hydrate A</button>
      <button onClick={() => setReplayed(true)}>Replay IDs</button>
      <button onClick={() => setMounted((value) => !value)}>{mounted ? "Detach viewport" : "Mount viewport"}</button>
      <button onClick={() => setBottomSignal((value) => value + 1)}>Force bottom</button>
    </nav>
    {mounted && <ThreadViewport messages={messages} isStreaming={false} conversationKey={selected}
      messagesKey={rendered} conversationReady={ready} scrollToBottomSignal={bottomSignal}
      readingState={parameters.has("external") ? store : undefined}
      composer={<div style={{ height: 100 }}>Composer</div>} />}
  </main>;
}

function ColdErrorFixture() {
  const [messages, setMessages] = useState<UIMessage[]>(parameters.has("cached-error") ? a : []);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch("/reading-fixture-history");
      if (!response.ok) throw new Error(`HTTP ${response.status}: unavailable`);
      setMessages(parameters.has("cached-error") ? a : [a[0]]);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { void load(); }, []);
  return <main style={{ height: "100vh", display: "flex" }}>
    <ThreadViewport messages={messages} isStreaming={false} conversationKey="cold"
      initialLoading={loading} initialError={error} onRetryInitial={() => { void load(); }}
      emptyState={<p>{loading ? "Loading fixture history" : "Welcome fixture"}</p>}
      composer={<div style={{ height: 100 }}>Composer</div>} />
  </main>;
}

await initializeI18n();
createRoot(document.getElementById("root")!).render(<TooltipProvider>
  {parameters.has("cold-error") || parameters.has("cached-error") ? <ColdErrorFixture /> : <ReadingFixture />}
</TooltipProvider>);
