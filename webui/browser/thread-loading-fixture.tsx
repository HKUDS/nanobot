import { ThreadShell } from "@/components/thread/ThreadShell";
import { settings } from "@/dev/gallery/settings";

export function ThreadLoadingFixture() {
  const dark = new URLSearchParams(location.search).has("dark");
  document.documentElement.classList.toggle("dark", dark);
  return <main className="thread-workspace flex min-w-0 flex-col overflow-hidden bg-background" style={{ height: "100dvh" }}>
    <ThreadShell
      session={{ key: "websocket:loading-preview", channel: "websocket", chatId: "loading-preview", createdAt: null, updatedAt: null, preview: "" }}
      title="Loading preview" onToggleSidebar={() => {}} theme={dark ? "dark" : "light"}
      settingsSnapshot={settings}
    />
  </main>;
}
