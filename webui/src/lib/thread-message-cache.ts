import type { ThreadTranscriptSnapshot } from "./thread-transcript";
import { MemoryLruCache } from "./memory-lru-cache";

/** Bounded replay cache; temporary chats remain pinned because they have no disk history. */
export class ThreadMessageCache extends MemoryLruCache<ThreadTranscriptSnapshot> {

  constructor(
    isPinned: (key: string) => boolean,
    maxBytes = 16 * 1024 * 1024,
    maxEntries = 12,
  ) {
    super(maxBytes, maxEntries, (key) => !isPinned(key));
  }
}
