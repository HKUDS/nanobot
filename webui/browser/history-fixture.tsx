import { useState } from "react";

import { MessageBubble } from "@/components/MessageBubble";
import { ThreadMessages } from "@/components/thread/ThreadMessages";
import type { UIMessage } from "@/lib/types";

const history: UIMessage[] = [
  { id: "question", role: "user", content: "Earlier question", createdAt: 1_700_000_000_000 },
  { id: "answer", role: "assistant", content: "Earlier answer", createdAt: 1_700_000_001_000 },
];
const trace: UIMessage = {
  id: "trace", role: "tool", kind: "trace", content: "Earlier tool call", createdAt: 1_700_000_002_000,
};

export function HistoryFixture() {
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

export function SessionMessagesFixture() {
  const messages: UIMessage[] = [
    { id: "own-input", role: "user", content: "Please review the update.", createdAt: 1 },
    {
      id: "session-message:short", role: "user", content: "Looks good.", createdAt: 2,
      sessionMessage: { message_id: "short", session: { id: "handle_0123456789abcdef0123456789abcdef", name: "mira" } },
    },
    {
      id: "session-message:long", role: "user", createdAt: 3,
      content: "**Review notes**\n\n- Keep the layout left-aligned.\n- Preserve Markdown and links.\n\n```ts\nconst message = \"" + "long-path/".repeat(30) + "\";\n```\n\n[Release notes](https://example.com/release-notes)",
      sessionMessage: { message_id: "long", session: { id: "handle_fedcba9876543210fedcba9876543210", name: "nori" } },
    },
    { id: "reply", turnId: "review", role: "assistant", content: "Thanks, I will keep those details.", createdAt: 4 },
    { ...trace, turnId: "monitor", createdAt: 5 },
    { id: "trigger", turnId: "monitor", role: "assistant", content: "The scheduled update is ready.", createdAt: 6,
      source: { kind: "local_trigger", label: "Release monitor" },
      responseSources: [{ provider: "xai", model: "grok", preset: "Release fallback model", fallback: true }] },
  ];
  return <main className="thread-viewport mx-auto max-w-3xl px-6 py-8" aria-label="Session messages">
    <ThreadMessages messages={messages} isStreaming={false} onForkFromMessage={() => {}} />
  </main>;
}
