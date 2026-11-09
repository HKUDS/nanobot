import { useState } from "react";
import { ChatList } from "@/components/ChatList";
import type { ChatSummary } from "@/lib/types";

const sessions: ChatSummary[] = ["Review history", "Locate messages", "Refine message bubbles", "Check MCP connection"].map((title, index) => ({
  key: `websocket:activity-${index}`,
  chatId: `activity-${index}`,
  channel: "websocket",
  title,
  preview: "",
  createdAt: "2026-10-21T10:00:00Z",
  updatedAt: "2026-10-21T10:00:00Z",
  handle: { id: `handle_activity_${index}`, name: ["bate", "jaru", "goyo", "tami"][index] },
}));

export function SidebarActivityFixture() {
  const [count, setCount] = useState(new URLSearchParams(location.search).has("all") ? sessions.length : 1);
  const [visible, setVisible] = useState(true);
  const [activeKey, setActiveKey] = useState(sessions[0].key);
  return <main className="flex min-h-screen flex-wrap items-start gap-6 bg-background p-4 text-foreground">
    <section aria-label="Activity sidebar" className="h-[480px] w-80 max-w-full bg-sidebar">
      {visible && <ChatList
        sessions={sessions} activeKey={activeKey} onSelect={setActiveKey}
        runningChatIds={sessions.slice(0, count).map((session) => session.chatId)}
        sort="title_asc" onRequestDelete={() => {}} onTogglePin={() => {}}
        onRequestRename={async () => {}} onToggleArchive={() => {}}
      />}
    </section>
    <div className="flex flex-col gap-3">
      <button onClick={() => setCount((value) => Math.min(sessions.length, value + 1))}>Start next conversation</button>
      <button onClick={() => setCount(1)}>Reset conversations</button>
      <button onClick={() => setVisible((value) => !value)}>Toggle sidebar</button>
      <button onClick={() => document.documentElement.classList.toggle("dark")}>Toggle theme</button>
    </div>
  </main>;
}
