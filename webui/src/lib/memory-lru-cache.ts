/** Byte- and entry-bounded LRU; non-evictable working state is outside that budget. */
export class MemoryLruCache<T> {
  private entries = new Map<string, { value: T; bytes: number }>();

  constructor(
    private maxBytes: number,
    private maxEntries: number,
    private canEvict: (key: string) => boolean = () => true,
  ) {}

  get(key: string): T | undefined {
    const entry = this.entries.get(key);
    if (!entry) return undefined;
    this.entries.delete(key);
    this.entries.set(key, entry);
    return entry.value;
  }

  /** Read without making a background observer retain an otherwise old entry. */
  peek(key: string): T | undefined {
    return this.entries.get(key)?.value;
  }

  set(key: string, value: T): void {
    const bytes = this.estimate(value);
    // A rejected replacement must not leave a stale snapshot under this key.
    this.delete(key);
    if (this.canEvict(key) && (bytes > this.maxBytes || this.maxEntries < 1)) return;
    this.entries.set(key, { value, bytes });

    let reclaimableBytes = 0;
    let reclaimableEntries = 0;
    for (const [candidate, entry] of this.entries) {
      if (!this.canEvict(candidate)) continue;
      reclaimableBytes += entry.bytes;
      reclaimableEntries++;
    }
    for (const [candidate, entry] of this.entries) {
      if (reclaimableBytes <= this.maxBytes && reclaimableEntries <= this.maxEntries) break;
      if (!this.canEvict(candidate)) continue;
      this.delete(candidate);
      reclaimableBytes -= entry.bytes;
      reclaimableEntries--;
    }
  }

  delete(key: string): void {
    this.entries.delete(key);
  }

  clear(): void {
    this.entries.clear();
  }

  private estimate(value: unknown, seen = new WeakSet<object>()): number {
    if (typeof value === "string") return value.length * 2;
    if (!value || typeof value !== "object") return 8;
    if (seen.has(value)) return 0;
    seen.add(value);
    let bytes = 32;
    if (value instanceof Map) {
      for (const [key, item] of value) {
        bytes += this.estimate(key, seen) + this.estimate(item, seen);
      }
    } else {
      for (const item of value instanceof Set ? value : Object.values(value)) {
        bytes += this.estimate(item, seen);
      }
    }
    return bytes;
  }
}
