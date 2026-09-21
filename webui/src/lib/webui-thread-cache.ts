import { MemoryLruCache } from "./memory-lru-cache";
import type { WebuiThreadPersistedPayload } from "./types";

/** Process-local canonical replay cache used for stale-while-revalidate session entry. */
export class WebuiThreadCache extends MemoryLruCache<WebuiThreadPersistedPayload> {
  constructor(
    maxBytes = 16 * 1024 * 1024,
    maxEntries = 12,
  ) {
    super(maxBytes, maxEntries);
  }
}

export const webuiThreadCache = new WebuiThreadCache();
