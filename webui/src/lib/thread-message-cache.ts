import type { UIMessage } from "./types";

/** Bounded replay cache; temporary chats remain pinned because they have no disk history. */
export class ThreadMessageCache {
  private entries = new Map<string, { messages: UIMessage[]; bytes: number }>();
  private sizes = new WeakMap<object, number>();
  private bytes = 0;

  constructor(
    private isPinned: (key: string) => boolean,
    private maxBytes = 16 * 1024 * 1024,
    private maxEntries = 12,
  ) {}

  get(key: string): UIMessage[] | undefined {
    const entry = this.entries.get(key);
    if (!entry) return undefined;
    this.entries.delete(key);
    this.entries.set(key, entry);
    return entry.messages;
  }

  set(key: string, messages: UIMessage[]): void {
    this.delete(key);
    const bytes = this.estimate(messages);
    this.entries.set(key, { messages, bytes });
    this.bytes += bytes;
    for (const candidate of this.entries.keys()) {
      if (this.bytes <= this.maxBytes && this.entries.size <= this.maxEntries) break;
      if (!this.isPinned(candidate)) this.delete(candidate);
    }
  }

  delete(key: string): void {
    const entry = this.entries.get(key);
    if (entry) this.bytes -= entry.bytes;
    this.entries.delete(key);
  }

  private estimate(value: unknown): number {
    if (typeof value === "string") return value.length * 2;
    if (!value || typeof value !== "object") return 8;
    const cached = this.sizes.get(value);
    if (cached !== undefined) return cached;
    const size = 32 + Object.values(value).reduce<number>((total, item) => total + this.estimate(item), 0);
    this.sizes.set(value, size);
    return size;
  }
}
