import { useState } from "react";
import { SessionSearchDialog } from "@/components/SessionSearchDialog";
import { useAppViewport } from "@/hooks/useAppViewport";
import { ThreadMessageCache } from "@/lib/thread-message-cache";
import { ThreadTranscript } from "@/lib/thread-transcript";
import type { ChatSummary } from "@/lib/types";

const sessions: ChatSummary[] = Array.from({ length: 2 }, (_, index) => ({
  key: `websocket:topic-${index}`, chatId: `topic-${index}`, channel: "websocket",
  title: `Topic ${index}`, preview: `Preview ${index}`, createdAt: null, updatedAt: null,
}));

export function LoadedSessionSearchFixture() {
  useAppViewport();
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [cache] = useState(() => {
    const value = new ThreadMessageCache(() => false);
    value.set("topic-1", new ThreadTranscript([
      { id: "user", role: "user", content: "我们讨论权限与配对", createdAt: 1 },
    ]).save());
    return value;
  });
  return <main className="h-[100dvh] bg-background p-6 text-foreground">
    <button onClick={() => setOpen(true)}>Search</button>
    <output aria-label="Selected topic">{selected}</output>
    <SessionSearchDialog open={open} onOpenChange={setOpen} sessions={sessions}
      activeKey={selected} loading={false} messageCache={cache} onSelect={setSelected} />
  </main>;
}
