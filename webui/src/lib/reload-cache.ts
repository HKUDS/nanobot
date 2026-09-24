import type { ChatSummary, WorkspaceScopePayload } from "./types";

const PREFIX = "nanobot.reload.v1.";
const MAX_CHARS = 512 * 1024;
let scope: string | null = null;

/** Enable tab-local replay only after bootstrap authenticates the gateway. */
export function activateReloadCache(wsUrl: string): void {
  const url = new URL(wsUrl, window.location.href);
  scope = `${url.origin}${url.pathname}`;
}

export function readReloadCache(name: string): unknown {
  if (!scope) return undefined;
  try {
    const raw = sessionStorage.getItem(PREFIX + name);
    if (!raw || raw.length > MAX_CHARS) return undefined;
    const stored: unknown = JSON.parse(raw);
    return isRecord(stored) && stored.scope === scope ? stored.value : undefined;
  } catch {
    return undefined;
  }
}

export function writeReloadCache(name: string, value: unknown): void {
  if (!scope) return;
  try {
    const raw = JSON.stringify({ scope, value });
    if (raw.length <= MAX_CHARS) sessionStorage.setItem(PREFIX + name, raw);
    else sessionStorage.removeItem(PREFIX + name);
  } catch {
    // Storage can be unavailable or full; in-memory replay remains usable.
  }
}

export function removeReloadCache(name: string): void {
  try { sessionStorage.removeItem(PREFIX + name); } catch { /* Storage is optional. */ }
}

export function clearReloadCache(): void {
  scope = null;
  removeReloadCache("sessions");
  removeReloadCache("thread");
}

export function readReloadSessions(): ChatSummary[] {
  const value = readReloadCache("sessions");
  if (!Array.isArray(value)) return [];
  return value.flatMap((row): ChatSummary[] => {
    if (!isRecord(row) || typeof row.key !== "string" || typeof row.channel !== "string"
      || typeof row.chatId !== "string" || typeof row.preview !== "string") return [];
    const workspaceScope = readWorkspaceScope(row.workspaceScope);
    return [{
      key: row.key, channel: row.channel, chatId: row.chatId, preview: row.preview,
      title: typeof row.title === "string" ? row.title : undefined,
      createdAt: typeof row.createdAt === "string" ? row.createdAt : null,
      updatedAt: typeof row.updatedAt === "string" ? row.updatedAt : null,
      ...(typeof row.modelPreset === "string" ? { modelPreset: row.modelPreset } : {}),
      ...(typeof row.runStartedAt === "number" ? { runStartedAt: row.runStartedAt } : {}),
      ...(workspaceScope ? { workspaceScope } : {}),
    }];
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function readWorkspaceScope(value: unknown): WorkspaceScopePayload | undefined {
  if (!isRecord(value) || typeof value.project_path !== "string"
    || (value.access_mode !== "full" && value.access_mode !== "restricted")
    || typeof value.restrict_to_workspace !== "boolean") return undefined;
  return {
    project_path: value.project_path,
    access_mode: value.access_mode,
    restrict_to_workspace: value.restrict_to_workspace,
    ...(typeof value.project_name === "string" ? { project_name: value.project_name } : {}),
  };
}
