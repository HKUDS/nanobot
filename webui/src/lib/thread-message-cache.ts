import type { ThreadTranscriptSnapshot } from "./thread-transcript";
import { MemoryLruCache } from "./memory-lru-cache";
import type { UIMessage } from "./types";

export type LoadedThreadMessages = readonly UIMessage[][];

/** Bounded replay cache; temporary chats remain pinned because they have no disk history. */
export class ThreadMessageCache extends MemoryLruCache<ThreadTranscriptSnapshot> {
  private loaded = new Map<string, LoadedThreadMessages>();
  private listeners = new Set<() => void>();
  private revision = 0;
  private updating = false;

  constructor(
    isPinned: (key: string) => boolean,
    maxBytes = 16 * 1024 * 1024,
    maxEntries = 12,
  ) {
    super(maxBytes, maxEntries, (key) => !isPinned(key));
  }

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  readonly getRevision = (): number => this.revision;

  readLoadedMessages(key: string): LoadedThreadMessages {
    const mounted = this.loaded.get(key);
    if (mounted) return mounted;
    const saved = this.peek(key);
    return saved ? [saved.projection.messages] : [];
  }

  setLoadedMessages(key: string, messages: LoadedThreadMessages): void {
    this.loaded.set(key, messages);
    this.changed();
  }

  deleteLoadedMessages(key: string): void {
    if (this.loaded.delete(key)) this.changed();
  }

  override set(key: string, value: ThreadTranscriptSnapshot): void {
    this.updating = true;
    try {
      super.set(key, value);
    } finally {
      this.updating = false;
      this.changed();
    }
  }

  override delete(key: string): void {
    const existed = this.peek(key) !== undefined;
    super.delete(key);
    if (existed) this.changed();
  }

  override clear(): void {
    super.clear();
    this.changed();
  }

  private changed(): void {
    if (this.updating) return;
    this.revision++;
    for (const listener of this.listeners) listener();
  }
}
