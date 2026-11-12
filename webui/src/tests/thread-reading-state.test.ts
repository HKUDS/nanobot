import { describe, expect, it, vi } from "vitest";
import { ThreadReadingStateStore, type ThreadReadingState } from "@/lib/thread-reading-state";

const state: ThreadReadingState = {
  anchor: { sources: ['["message","id","a"]'], relativeOffset: -12, scrollTop: 812 },
  visibleMessageCount: 240,
  followTail: false,
};

describe("ThreadReadingStateStore", () => {
  it("isolates live anchor reconciliation from stored and serialized snapshots", () => {
    const store = new ThreadReadingStateStore();
    store.set("a", state);
    const snapshot = store.entries();
    const restored = new ThreadReadingStateStore(snapshot);
    const live = restored.get("a")!;
    live.anchor!.scrollTop = 999;
    live.anchor!.sources.push("another-source");
    snapshot[0][1].visibleMessageCount = 120;
    expect(store.get("a")).toEqual(state);
    expect(restored.get("a")).toEqual(state);
  });

  it("notifies its caller when a conversation is saved or removed", () => {
    const store = new ThreadReadingStateStore();
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);
    store.set("a", state);
    expect(listener).toHaveBeenCalledTimes(1);
    expect(store.get("a")).toEqual(state);
    store.delete("a");
    expect(listener).toHaveBeenCalledTimes(2);
    expect(store.entries()).toEqual([]);
    unsubscribe();
    store.set("b", state);
    store.clear();
    expect(listener).toHaveBeenCalledTimes(2);
    expect(store.entries()).toEqual([]);
  });
});
