import { useState } from "react";
import { createPortal } from "react-dom";
import { Sidebar } from "@/components/Sidebar";
import { PaneWorkbench } from "@/components/workbench/PaneWorkbench";
import { ThreadViewport } from "@/components/thread/ThreadViewport";
import { ThreadHistoryStatus } from "@/components/thread/ThreadHistoryStatus";
import { formatQuotedUserMessage } from "@/lib/user-message-quote";
import type { ChatSummary, UIMessage } from "@/lib/types";
import { ThreadComposer } from "@/components/thread/ThreadComposer";
import { ThreadHeader } from "@/components/thread/ThreadHeader";
import { ThemeProvider, useTheme } from "@/hooks/useTheme";

export function ThemeToggleFixture() {
  const { theme, toggle } = useTheme();
  return (
    <ThemeProvider theme={theme}>
      {new URLSearchParams(location.search).has("chat") ? <ThemeChatFixture theme={theme} toggle={toggle} /> : (
        <main data-theme-surface className="thread-workspace relative flex flex-col justify-center gap-8 bg-background px-6" style={{ height: "100vh" }}>
          <div className="absolute inset-x-0 top-0">
            <ThreadHeader title="Theme preview" hideTitle theme={theme} onToggleTheme={toggle} onToggleSidebar={() => {}} />
          </div>
          <div className="workbench-body">
            <section data-theme-surface className="workbench-pane flex flex-col gap-8 bg-background">
              <h1 data-testid="hero-greeting" data-theme-ink className="text-center text-4xl text-foreground">Where should we start?</h1>
              <ThreadComposer variant="hero" onSend={() => {}} />
            </section>
          </div>
        </main>
      )}
    </ThemeProvider>
  );
}

const sessions: ChatSummary[] = ["Theme chat", "Another chat"].map((title, index) => ({
  key: `websocket:theme-${index}`, channel: "websocket", chatId: `theme-${index}`,
  title, preview: "", createdAt: null, updatedAt: null,
}));
const messages: UIMessage[] = [
  { id: "user", role: "user", content: formatQuotedUserMessage("Keep the surface layers in sync.", "Quoted context has its own translucent fill."), createdAt: 1 },
  { id: "answer", role: "assistant", content: "An existing conversation with a portaled composer.", createdAt: 2 },
  { id: "session", role: "user", content: "An incoming session message.", createdAt: 3,
    sessionMessage: { message_id: "incoming", session: { id: "handle_0123456789abcdef0123456789abcdef", name: "nori" } } },
];
const noop = () => {};

function ThemeChatFixture({ theme, toggle }: { theme: "light" | "dark"; toggle: () => void }) {
  const [activeKey, setActiveKey] = useState(sessions[0].key);
  const composer = <ThreadComposer onSend={noop} />;
  return <main data-theme-surface className="flex bg-background" style={{ height: "100vh" }}>
    <aside className="hidden w-64 shrink-0 sm:block">
      <Sidebar sessions={sessions} activeKey={activeKey} onSelect={setActiveKey} loading={false} newChatActive={false}
        onNewChat={noop} onRequestDelete={noop} onTogglePin={noop} onRequestRename={async () => {}}
        onToggleArchive={noop} onToggleGroup={noop} onRequestRenameProject={noop} onNewChatInProject={noop}
        onOpenSettings={noop} onOpenApps={noop} onOpenSkills={noop} onOpenAutomations={noop}
        onOpenChannels={noop} onOpenSearch={noop} onToggleArchived={noop} />
    </aside>
    <div className="min-w-0 flex-1">
      <PaneWorkbench panes={[{ key: "theme", title: "Theme chat" }]} activePaneKey="theme" layout="columns"
        showLayoutControl={false} onActivatePane={noop} onAddPane={noop} onLayoutChange={noop} onPaneOrderChange={noop}
        renderPane={(_pane, context) => <div className="relative flex min-h-0 flex-1 flex-col">
          <ThreadHeader title="Theme chat" hideTitle theme={theme} onToggleTheme={toggle} onToggleSidebar={noop} />
          <ThreadViewport messages={messages} isStreaming={false} conversationKey={activeKey}
            navigationFrame={context.navigationFrame} composer={null} />
          <ThreadHistoryStatus loading={false} error={null} exhausted onRetry={noop} />
          {context.composerPortalTarget && createPortal(composer, context.composerPortalTarget)}
        </div>} />
    </div>
  </main>;
}
