import type { WorkspaceDirectoriesPayload } from "@/lib/types";
import { normalizeWorkspacePath, type BrowseWorkspaceDirectories } from "@/lib/workspace";

const MAX_DIRECTORIES = 64;
const DIRECTORY_TTL_MS = 30_000;

export function createWorkspaceDirectoryCache(browse: BrowseWorkspaceDirectories) {
  const entries = new Map<string, { result: WorkspaceDirectoriesPayload; expires: number }>();
  const pending = new Map<string, Promise<WorkspaceDirectoriesPayload>>();
  const keyFor = (path: string, query: string, hidden: boolean, partial = false) =>
    JSON.stringify([normalizeWorkspacePath(path.trim()), query, hidden, partial]);

  function peek(path: string, query: string, hidden: boolean, partial = false) {
    const key = keyFor(path, query, hidden, partial);
    const entry = entries.get(key);
    if (!entry) return undefined;
    entries.delete(key);
    if (entry.expires <= Date.now()) return undefined;
    entries.set(key, entry);
    return entry.result;
  }

  function load(path: string, query: string, hidden: boolean, partial = false) {
    const cached = peek(path, query, hidden, partial);
    if (cached) return Promise.resolve(cached);
    const key = keyFor(path, query, hidden, partial);
    const existing = pending.get(key);
    if (existing) return existing;
    const request = browse(path, query, hidden, partial).then(result => {
      entries.delete(key);
      entries.set(key, { result, expires: Date.now() + DIRECTORY_TTL_MS });
      if (entries.size > MAX_DIRECTORIES) entries.delete(entries.keys().next().value!);
      return result;
    }).finally(() => pending.delete(key));
    pending.set(key, request);
    return request;
  }

  return { peek, load };
}
