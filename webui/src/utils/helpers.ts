import { WorkspaceScopePayload } from "@/lib/types";
import { projectNameFromPath } from "@/lib/workspace";
import { COMPLETED_RUNS_STORAGE_KEY, SIDEBAR_STORAGE_KEY } from "@/constants";

export function readSidebarOpen(): boolean {
  if (typeof window === "undefined") return true;
  try {
    const raw = window.localStorage.getItem(SIDEBAR_STORAGE_KEY);
    if (raw === null) return true;
    return raw === "1";
  } catch {
    return true;
  }
}

export function readCompletedRunChatIds(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = window.localStorage.getItem(COMPLETED_RUNS_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((item): item is string => typeof item === "string"));
  } catch {
    return new Set();
  }
}

export function writeCompletedRunChatIds(chatIds: Set<string>): void {
  try {
    window.localStorage.setItem(
      COMPLETED_RUNS_STORAGE_KEY,
      JSON.stringify(Array.from(chatIds)),
    );
  } catch {
    // ignore storage errors (private mode, etc.)
  }
}

export function normalizeWorkspaceScope(scope: WorkspaceScopePayload): WorkspaceScopePayload {
  const accessMode = scope.access_mode === "restricted" ? "restricted" : "full";
  return {
    ...scope,
    project_name: scope.project_name ?? projectNameFromPath(scope.project_path),
    access_mode: accessMode,
    restrict_to_workspace: accessMode === "restricted",
  };
}
