import type { FilePreviewPayload } from "@/lib/types";

const FRESH_MS = 5_000;
const RETAIN_MS = 60_000;
const MAX_ENTRIES = 4;
const MAX_BYTES = 8 * 1024 * 1024;

/** Short-lived, in-memory only. The caller owns one resource per session/loader. */
export function createFilePreviewResource(fetchPreview: (path: string) => Promise<FilePreviewPayload>) {
  const entries = new Map<string, {
    payload?: FilePreviewPayload;
    pending?: Promise<FilePreviewPayload>;
    loadedAt: number;
    bytes: number;
  }>();
  const peek = (path: string) => {
    const entry = entries.get(path);
    return entry?.payload && Date.now() - entry.loadedAt < RETAIN_MS ? entry.payload : undefined;
  };
  const load = (path: string): Promise<FilePreviewPayload> => {
    const existing = entries.get(path);
    if (existing?.pending) return existing.pending;
    if (existing?.payload && Date.now() - existing.loadedAt < FRESH_MS) {
      return Promise.resolve(existing.payload);
    }
    const entry = { payload: peek(path), loadedAt: existing?.loadedAt ?? 0, bytes: existing?.bytes ?? 0,
      pending: undefined as Promise<FilePreviewPayload> | undefined };
    entries.delete(path);
    entries.set(path, entry);
    while (entries.size > MAX_ENTRIES) entries.delete(entries.keys().next().value!);
    entry.pending = Promise.resolve().then(() => fetchPreview(path)).then((payload) => {
      // An evicted request may finish, but must not put its data back into the cache.
      if (entries.get(path) === entry) {
        entry.payload = payload;
        entry.pending = undefined;
        entry.loadedAt = Date.now();
        entry.bytes = 2 * (payload.kind === "image" ? payload.data_url.length : payload.content.length);
        let total = [...entries.values()].reduce((sum, item) => sum + item.bytes, 0);
        for (const [key, item] of entries) {
          if (total <= MAX_BYTES) break;
          total -= item.bytes;
          entries.delete(key);
        }
      }
      return payload;
    }, (error: unknown) => {
      if (entries.get(path) === entry) entries.delete(path);
      throw error;
    });
    return entry.pending;
  };
  return { peek, load };
}
