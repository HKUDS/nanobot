import { useState } from "react";
import { ThreadShell } from "@/components/thread/ThreadShell";
import type { WorkspaceScopePayload } from "@/lib/types";
import { StartupSkeleton } from "@/components/StartupSkeleton";
import { settings } from "@/dev/gallery/settings";
import "@/components/startup-skeleton.css";

const noop = () => {};

export function NewChatSkeletonFixture() {
  const params = new URLSearchParams(location.search);
  const [workspaceScope, setWorkspaceScope] = useState<WorkspaceScopePayload>({ project_path: "/workspace", access_mode: "full" });
  const sidebarExpanded = !params.has("collapsed");
  const sidebarWidth = Number(params.get("sidebarWidth") ?? 272);
  const dark = params.has("dark");
  document.documentElement.classList.toggle("dark", dark);
  return <div className="flex overflow-hidden bg-background" style={{ height: "100dvh" }}>
    {params.has("loading") ? <StartupSkeleton sidebarExpanded={sidebarExpanded} sidebarWidth={sidebarWidth} /> : <>
      <aside className="hidden shrink-0 bg-sidebar lg:block" style={{ width: sidebarExpanded ? sidebarWidth : 56 }} />
      <main className="thread-workspace relative flex min-w-0 flex-1 flex-col overflow-hidden">
        <ThreadShell session={null} title="nanobot" onToggleSidebar={noop} theme={dark ? "dark" : "light"}
          hideSidebarToggleForHostChrome onTemporaryChatEnabledChange={noop} settingsSnapshot={settings}
          workspaceScope={workspaceScope}
          workspaceDefaultScope={{ project_path: "/workspace", access_mode: "full" }}
          workspaceControls={{ can_change_project: true, can_browse_directories: true }} onWorkspaceScopeChange={setWorkspaceScope} />
      </main>
    </>}
  </div>;
}
