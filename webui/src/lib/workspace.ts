import type { WorkspaceAccessMode, WorkspaceScopePayload, WorkspaceDirectoriesPayload } from "@/lib/types";

export function scopeWithAccessMode(
  scope: WorkspaceScopePayload,
  accessMode: WorkspaceAccessMode,
): WorkspaceScopePayload {
  return {
    ...scope,
    access_mode: accessMode,
    restrict_to_workspace: accessMode === "restricted",
  };
}

export function projectNameFromPath(path: string): string {
  const normalized = path.replace(/\\/g, "/").replace(/\/+$/, "");
  return normalized.split("/").filter(Boolean).pop() || path;
}

export function isAbsoluteWorkspacePath(path: string): boolean {
  const trimmed = path.trim();
  return (
    trimmed === "~"
    || trimmed.startsWith("~/")
    || trimmed.startsWith("~\\")
    || trimmed.startsWith("/")
    || trimmed.startsWith("\\\\")
    || /^[A-Za-z]:[\\/]/.test(trimmed)
  );
}

export function selectedProjectScope(
  scope: WorkspaceScopePayload | null,
  defaultScope: WorkspaceScopePayload | null,
): WorkspaceScopePayload | null {
  if (!scope || !defaultScope) return null;
  return sameWorkspacePath(scope.project_path, defaultScope.project_path) ? null : scope;
}

export function normalizeWorkspacePath(path: string | null | undefined): string {
  const normalized = (path ?? "").replace(/\\/g, "/").replace(/\/+$/, "");
  return normalized || "/";
}

export function sameWorkspacePath(
  a: string | null | undefined,
  b: string | null | undefined,
): boolean {
  if (!a || !b) return false;
  return normalizeWorkspacePath(a) === normalizeWorkspacePath(b);
}

export function workspacePathCompletionQuery(path: string): { path: string; query: string } | null {
  const draft = path.trim();
  if (!isAbsoluteWorkspacePath(draft)) return null;
  if (draft === "~") return { path: "~", query: "" };
  const parts = /^(.*[\\/])([^\\/]*)$/.exec(draft);
  return parts ? { path: parts[1], query: parts[2] } : null;
}

export function workspaceDirectoryPrefix(path: string): string {
  const separator = path.includes("\\") ? "\\" : "/";
  return path.replace(/[\\/]+$/, "") + separator;
}

/** Build navigation from the gateway path, never the browser's operating system. */
export function workspaceBreadcrumbs(path: string): { name: string; path: string }[] {
  const windows = /^[A-Za-z]:[\\/]/.test(path) || path.startsWith("\\\\");
  const separator = windows ? "\\" : "/";
  const normalized = windows ? path.replace(/\//g, "\\") : path;
  const root = windows
    ? normalized.match(/^(?:[A-Za-z]:\\|\\\\[^\\]+\\[^\\]+\\?)/)?.[0]
    : normalized.startsWith("/") ? "/" : normalized.startsWith("~") ? "~" : undefined;
  if (!root) return [{ name: path, path }];
  const crumbs = [{ name: root, path: root }];
  let current = root.replace(/[\\/]$/, "");
  for (const name of normalized.slice(root.length).split(separator).filter(Boolean)) {
    current += separator + name;
    crumbs.push({ name, path: current });
  }
  return crumbs;
}

export type BrowseWorkspaceDirectories = (path: string, query: string, showHidden: boolean, allowPartial?: boolean) => Promise<WorkspaceDirectoriesPayload>;
