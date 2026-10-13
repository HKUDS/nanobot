import { MemoryLruCache } from "./memory-lru-cache";
import { parseWebuiThreadPayload } from "./api";
import { readReloadCache, removeReloadCache, writeReloadCache } from "./reload-cache";
import type { WebuiThreadPersistedPayload } from "./types";

/** Bounded canonical replay cache; the most recent snapshot also survives tab reloads. */
export class WebuiThreadCache extends MemoryLruCache<WebuiThreadPersistedPayload> {
  constructor(
    maxBytes = 16 * 1024 * 1024,
    maxEntries = 12,
  ) {
    super(maxBytes, maxEntries);
  }

  override get(key: string): WebuiThreadPersistedPayload | undefined {
    const cached = super.get(key);
    if (cached) return cached;
    const stored = readReloadCache("thread");
    if (!stored || typeof stored !== "object" || !("key" in stored)
      || stored.key !== key || !("body" in stored)) return undefined;
    try {
      const body = parseWebuiThreadPayload(stored.body);
      this.set(key, body);
      return super.get(key);
    } catch {
      removeReloadCache("thread");
      return undefined;
    }
  }

  override set(key: string, body: WebuiThreadPersistedPayload): void {
    super.set(key, body);
    if (super.get(key)) writeReloadCache("thread", { key, body });
  }

  override delete(key: string): void {
    super.delete(key);
    const stored = readReloadCache("thread");
    if (stored && typeof stored === "object" && "key" in stored && stored.key === key) {
      removeReloadCache("thread");
    }
  }

  override clear(): void {
    super.clear();
    removeReloadCache("thread");
  }
}

export const webuiThreadCache = new WebuiThreadCache();
