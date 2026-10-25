/** Byte- and entry-bounded in-memory LRU for WebUI state. */
export class MemoryLruCache<T> {
  private entries = new Map<string, { value: T; bytes: number }>();
  private sizes = new WeakMap<object, number>();
  private bytes = 0;

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
    this.delete(key);
    const bytes = this.estimate(value);
    this.entries.set(key, { value, bytes });
    this.bytes += bytes;
    for (const candidate of this.entries.keys()) {
      if (this.bytes <= this.maxBytes && this.entries.size <= this.maxEntries) break;
      if (this.canEvict(candidate)) this.delete(candidate);
    }
  }

  delete(key: string): void {
    const entry = this.entries.get(key);
    if (entry) this.bytes -= entry.bytes;
    this.entries.delete(key);
  }

  clear(): void {
    this.entries.clear();
    this.sizes = new WeakMap<object, number>();
    this.bytes = 0;
  }

  private estimate(value: unknown): number {
    if (typeof value === "string") return value.length * 2;
    if (!value || typeof value !== "object") return 8;
    const cached = this.sizes.get(value);
    if (cached !== undefined) return cached;
    const values = value instanceof Map ? Array.from(value.entries())
      : value instanceof Set ? Array.from(value) : Object.values(value);
    const size = 32 + values.reduce<number>(
      (total, item) => total + this.estimate(item),
      0,
    );
    this.sizes.set(value, size);
    return size;
  }
}
