import { useState } from "react";
import { Thread } from "@/components/thread";
import { ThreadList } from "@/components/thread-list";
import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { useDataStreamRuntime } from "@assistant-ui/react-data-stream";

export default function App() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const runtime = useDataStreamRuntime({
    api: "/api/chat",
    protocol: "data-stream",
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="flex h-screen bg-background text-foreground">
        {/* Sidebar */}
        {sidebarOpen && (
          <aside className="w-64 border-r border-border bg-sidebar-background flex flex-col shrink-0">
            <div className="p-3 border-b border-border flex items-center gap-2">
              <span className="text-xl">🤖</span>
              <h1 className="text-lg font-semibold">Nanobot</h1>
            </div>
            <div className="flex-1 overflow-y-auto p-2">
              <ThreadList />
            </div>
          </aside>
        )}

        {/* Main chat area */}
        <main className="flex-1 flex flex-col min-w-0">
          <header className="border-b border-border px-4 py-2 flex items-center shrink-0">
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="mr-3 p-1 rounded hover:bg-accent text-muted-foreground"
              title={sidebarOpen ? "Hide sidebar" : "Show sidebar"}
            >
              {sidebarOpen ? "◀" : "▶"}
            </button>
            <span className="text-sm text-muted-foreground">Chat</span>
          </header>
          <div className="flex-1 min-h-0">
            <Thread />
          </div>
        </main>
      </div>
    </AssistantRuntimeProvider>
  );
}
