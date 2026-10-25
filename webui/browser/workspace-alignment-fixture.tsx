import { useState } from "react";
import { ThreadComposer } from "@/components/thread/ThreadComposer";
import type { WorkspaceScopePayload, WorkspacesPayload } from "@/lib/types";

const initialScope: WorkspaceScopePayload = { project_path: "/workspace", access_mode: "full" };
const catalog: WorkspacesPayload = {
  schema_version: 1, default_access_mode: "full", default_scope: initialScope,
  recent_projects: [], controls: { can_change_project: true },
};

export function WorkspaceAlignmentFixture({ parameters }: { parameters: URLSearchParams }) {
  const [scope, setScope] = useState(initialScope);
  return <main className="mx-auto w-full max-w-5xl px-4 pt-24" style={{ maxWidth: parameters.has("containerWidth") ? Number(parameters.get("containerWidth")) : undefined }}>
    <ThreadComposer variant={parameters.get("composerVariant") === "thread" ? "thread" : "hero"}
      onSend={() => {}} workspaceScope={scope} workspaceDefaultScope={initialScope}
      contextUsage={parameters.has("usage") ? { contextTokens: 500, contextWindowTokens: 1000 } : null}
      workspaceControls={catalog.controls} onWorkspaceScopeChange={setScope}
      onLoadWorkspaceProjects={async () => catalog}
      onResolveWorkspaceProject={async path => ({ path, name: "workspace" })}
      onFavoriteWorkspaceProject={async () => []}
      onBrowseWorkspaceDirectories={async path => ({ path, parent: null, entries: [], truncated: false, host: "fixture", platform: "Linux" })} />
  </main>;
}
