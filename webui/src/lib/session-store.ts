import type { NanobotClient } from "./nanobot-client";
import { ThreadMessageCache } from "./thread-message-cache";
import { ThreadTranscript } from "./thread-transcript";
import { WebuiThreadCache } from "./webui-thread-cache";
import { MemoryLruCache } from "./memory-lru-cache";
import { ThreadReadingStateStore, type ThreadReadingState } from "./thread-reading-state";
import { currentReloadScope, readReloadCache, writeReloadCache } from "./reload-cache";
import { cancelLatestThreadReads, fetchSharedLatestThread, invalidateLatestThreadRead } from "./latest-thread-request";
import type { PromptIndex, UIMessage, WebuiThreadPersistedPayload } from "./types";
import { PromptReadingPositionStore, type PromptPageQuery } from "./prompt-reading-position";

export interface PromptHistoryPage {
  messages: UIMessage[];
  body: WebuiThreadPersistedPayload;
  query: PromptPageQuery;
}

export interface PromptWindow {
  pages: PromptHistoryPage[];
  target: { id: string; sequence: number } | null;
}

/** One authenticated client owns reusable data; views only borrow its transcript. */
export class SessionStore {
  readonly temporary = new Set<string>();
  readonly messages = new ThreadMessageCache((key) => this.temporary.has(key));
  readonly canonical = new WebuiThreadCache();
  readonly promptIndexes = new MemoryLruCache<PromptIndex>(2 * 1024 * 1024, 32);
  readonly promptWindows = new MemoryLruCache<PromptWindow>(8 * 1024 * 1024, 12);
  readonly navigationPositions: PromptReadingPositionStore;
  private readonly owners = new Map<string, ThreadTranscript>();
  private readonly epochs = new Map<string, number>();
  private sequence = 0;
  private lifetime = 0;
  private readonly reading = new Map<string, ThreadReadingStateStore>();
  private readonly scope = currentReloadScope();

  constructor(private readonly client: NanobotClient) {
    this.navigationPositions = new PromptReadingPositionStore(readReloadCache("navigation", this.scope));
    this.navigationPositions.subscribe(() => writeReloadCache("navigation", this.navigationPositions.entries(), this.scope));
  }

  readingState(pane: string): ThreadReadingStateStore {
    let store = this.reading.get(pane);
    if (store) { this.reading.delete(pane); this.reading.set(pane, store); return store; }
    const saved = readReloadCache("reading", this.scope);
    const entries = Array.isArray(saved) ? saved.find((entry: unknown) => Array.isArray(entry) && entry[0] === pane) : undefined;
    const states: [string, ThreadReadingState][] = [];
    if (Array.isArray(entries?.[1])) for (const entry of entries[1]) {
      if (!Array.isArray(entry) || typeof entry[0] !== "string" || !isReadingState(entry[1])) continue;
      states.push([entry[0], entry[1]]);
    }
    store = new ThreadReadingStateStore(states.slice(-128));
    store.subscribe(() => {
      writeReloadCache("reading", Array.from(this.reading, ([key, value]) => [key,
        value.entries().filter(([session]) => !this.temporary.has(session.replace(/^websocket:/, ""))).slice(-128)]).slice(-8), this.scope);
    });
    this.reading.set(pane, store);
    while (this.reading.size > 8) this.reading.delete(this.reading.keys().next().value!);
    return store;
  }

  transcript(key: string, messages: UIMessage[], temporary: boolean, snapshots = this.messages, snapshotKey = key): ThreadTranscript {
    const active = this.owners.get(key);
    if (active) return active;
    if (temporary) this.temporary.add(snapshotKey);
    const saved = snapshots.get(snapshotKey);
    snapshots.delete(snapshotKey);
    const owner = new ThreadTranscript(messages, saved, { recordLiveContributions: !temporary });
    owner.paging = { ...owner.paging, loading: !temporary && owner.paging.version === 0,
      hasMoreBefore: temporary ? false : owner.paging.hasMoreBefore };
    this.owners.set(key, owner);
    return owner;
  }

  checkpoint(key: string, owner: ThreadTranscript, snapshots = this.messages, snapshotKey = key): void {
    if (this.owners.get(key) === owner) snapshots.set(snapshotKey, owner.save());
  }

  release(key: string, owner: ThreadTranscript, snapshots = this.messages, snapshotKey = key): void {
    this.checkpoint(key, owner, snapshots, snapshotKey);
    if (this.owners.get(key) === owner) this.owners.delete(key);
  }

  /** Detaching a pane cancels its delivery, not the store-owned bounded HTTP read. */
  latest(token: string, key: string, signal?: AbortSignal, retainOnDetach = true): Promise<WebuiThreadPersistedPayload | null> {
    const epoch = this.epoch(key);
    const lifetime = this.lifetime;
    return fetchSharedLatestThread(this.client, token, key, this.canonical, (body) => this.publish(key, body), signal, retainOnDetach).then((body) => {
      if (this.lifetime !== lifetime || this.epoch(key) !== epoch) throw new DOMException("The request was aborted", "AbortError");
      return body;
    });
  }

  epoch(key: string): number { return this.epochs.get(key) ?? this.lifetime; }

  publish(key: string, body: WebuiThreadPersistedPayload): void {
    const previous = this.promptWindows.peek(key)?.pages[0]?.body.page?.history_generation
      ?? this.navigationPositions.get(key)?.generation ?? this.canonical.peek(key)?.page?.history_generation;
    const next = body.page?.history_generation;
    if (previous && next && previous !== next) {
      this.epochs.set(key, ++this.sequence);
      this.promptIndexes.delete(key);
      this.promptWindows.delete(key);
      this.navigationPositions.delete(key);
      for (const reading of this.reading.values()) reading.delete(key);
    }
    this.canonical.set(key, body);
  }

  delete(key: string): void {
    this.epochs.set(key, ++this.sequence);
    cancelLatestThreadReads(this.client, key);
    this.owners.delete(key);
    this.messages.delete(key);
    this.messages.delete(key.replace(/^websocket:/, ""));
    this.messages.deleteLoadedMessages(key);
    this.messages.deleteLoadedMessages(key.replace(/^websocket:/, ""));
    this.canonical.delete(key);
    this.promptIndexes.delete(key);
    this.promptWindows.delete(key);
    this.navigationPositions.delete(key);
    for (const reading of this.reading.values()) reading.delete(key);
  }

  invalidateRead(signal: AbortSignal): void { invalidateLatestThreadRead(signal); }
  cancelReads(): void { cancelLatestThreadReads(this.client); }

  clear(): void {
    this.lifetime = ++this.sequence;
    this.cancelReads();
    this.epochs.clear();
    this.owners.clear();
    this.messages.clear();
    this.temporary.clear();
    this.canonical.clear();
    this.promptIndexes.clear();
    this.promptWindows.clear();
    this.navigationPositions.clear();
    for (const reading of this.reading.values()) reading.clear();
    this.reading.clear();
  }
}

function isReadingState(value: unknown): value is ThreadReadingState {
  if (!value || typeof value !== "object" || !("visibleMessageCount" in value)
    || typeof value.visibleMessageCount !== "number" || !Number.isSafeInteger(value.visibleMessageCount) || value.visibleMessageCount < 1
    || !("followTail" in value) || typeof value.followTail !== "boolean" || !("anchor" in value)) return false;
  const anchor = value.anchor;
  return anchor === null || (typeof anchor === "object" && "sources" in anchor
    && Array.isArray(anchor.sources) && anchor.sources.every(isScrollSource)
    && "relativeOffset" in anchor && typeof anchor.relativeOffset === "number" && Number.isFinite(anchor.relativeOffset)
    && "scrollTop" in anchor && typeof anchor.scrollTop === "number" && Number.isFinite(anchor.scrollTop)
    && (!("fallback" in anchor) || typeof anchor.fallback === "string"));
}

function isScrollSource(source: unknown): boolean {
  if (typeof source !== "string") return false;
  try { const parsed: unknown = JSON.parse(source); return Array.isArray(parsed) && parsed.length >= 2 && typeof parsed[1] === "string" && parsed.every((part: unknown) => typeof part === "string" || typeof part === "number" && Number.isFinite(part)); }
  catch { return false; }
}

const stores = new WeakMap<NanobotClient, SessionStore>();
export function getSessionStore(client: NanobotClient): SessionStore {
  let store = stores.get(client);
  if (!store) { store = new SessionStore(client); stores.set(client, store); }
  return store;
}
