import { afterEach, describe, expect, it, vi } from "vitest";
import { NanobotClient } from "@/lib/nanobot-client";
import { getSessionStore } from "@/lib/session-store";
import { activateReloadCache, clearReloadCache, readReloadCache } from "@/lib/reload-cache";
import type { WebuiThreadPersistedPayload } from "@/lib/types";

function client(url = "ws://localhost") {
  const socket = { readyState: 1, onopen: null as (() => void) | null, send() {}, close() {} };
  const client = new NanobotClient({ url, reconnect: false, socketFactory: () => socket as unknown as WebSocket });
  client.connect();
  socket.onopen?.();
  return client;
}

function body(revision = "one", generation = "generation-one"): WebuiThreadPersistedPayload {
  return { schemaVersion: 1, projection: "events", revision, events: [],
    page: { before_cursor: null, after_cursor: null, has_more_before: false, has_more_after: false,
      user_message_offset: 0, history_generation: generation } };
}

afterEach(() => { vi.unstubAllGlobals(); clearReloadCache(); });

describe("authenticated session store", () => {
  it("retains an orphaned latest result for the next view without applying it to the detached view", async () => {
    const store = getSessionStore(client());
    let finish!: (response: Response) => void;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => new Promise<Response>((resolve) => { finish = resolve; })));
    const controller = new AbortController();
    const pending = store.latest("test-token", "websocket:a", controller.signal);
    const cancelled = expect(pending).rejects.toMatchObject({ name: "AbortError" });
    controller.abort();
    await cancelled;
    finish(Response.json(body()));
    await vi.waitFor(() => expect(store.canonical.get("websocket:a")?.revision).toBe("one"));
    store.clear();
  });

  it("deletion fences pending reads and detached projections instead of resurrecting a deleted session", async () => {
    const store = getSessionStore(client());
    const key = "websocket:deleted";
    const owner = store.transcript(key, [{ id: "old", role: "assistant", content: "old", createdAt: 1 }], false);
    let finish!: (response: Response) => void;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => new Promise<Response>((resolve) => { finish = resolve; })));
    const pending = store.latest("test-token", key);
    const cancelled = expect(pending).rejects.toMatchObject({ name: "AbortError" });
    store.delete(key);
    await cancelled;
    store.release(key, owner);
    finish(Response.json(body()));
    await Promise.resolve();
    expect(store.messages.get(key)).toBeUndefined();
    expect(store.canonical.get(key)).toBeUndefined();
  });

  it("invalidates only the replaced history generation's navigation data", () => {
    const store = getSessionStore(client());
    for (const key of ["websocket:a", "websocket:b"]) {
      store.publish(key, body());
      store.promptIndexes.set(key, { prompts: [], revision: "index-one" });
      store.promptWindows.set(key, { pages: [{ body: body(), messages: [], query: { cursor: "start", direction: "after" } }], target: null });
    }
    store.publish("websocket:a", body("two", "generation-two"));
    expect(store.promptIndexes.get("websocket:a")).toBeUndefined();
    expect(store.promptWindows.get("websocket:a")).toBeUndefined();
    expect(store.promptIndexes.get("websocket:b")?.revision).toBe("index-one");
    expect(store.promptWindows.get("websocket:b")?.pages).toHaveLength(1);
    store.clear();
  });

  it("restores lightweight pane reading state after reload without sharing another pane's camera", () => {
    activateReloadCache("ws://first-host/ws");
    const first = getSessionStore(client("ws://first-host/ws"));
    const state = { anchor: { sources: ['["message","sequence","turn",3]'], relativeOffset: -12, scrollTop: 450 }, visibleMessageCount: 240, followTail: false };
    first.readingState("primary").set("websocket:a", state);
    first.navigationPositions.set("websocket:a", { queries: [{ cursor: "opaque-cursor", direction: "after" }], generation: "one" });
    const reloaded = getSessionStore(client("ws://first-host/ws"));
    expect(reloaded.readingState("primary").get("websocket:a")).toEqual(state);
    expect(reloaded.readingState("split-pane").get("websocket:a")).toBeUndefined();
    expect(reloaded.navigationPositions.get("websocket:a")?.queries).toEqual([{ cursor: "opaque-cursor", direction: "after" }]);
    reloaded.delete("websocket:a");
    expect(reloaded.readingState("primary").get("websocket:a")).toBeUndefined();
    expect(reloaded.navigationPositions.get("websocket:a")).toBeUndefined();
  });

  it("isolates identical session keys and reload writes across authenticated hosts", () => {
    activateReloadCache("ws://first-host/ws");
    const first = getSessionStore(client("ws://first-host/ws"));
    first.publish("websocket:shared", body("first"));
    activateReloadCache("ws://second-host/ws");
    const second = getSessionStore(client("ws://second-host/ws"));
    expect(second.canonical.get("websocket:shared")).toBeUndefined();
    second.publish("websocket:shared", body("second"));
    first.publish("websocket:shared", body("late-first"));
    expect(second.canonical.get("websocket:shared")?.revision).toBe("second");
    expect(readReloadCache("thread")).toMatchObject({ body: { revision: "second" } });
    first.clear();
    expect(readReloadCache("thread")).toMatchObject({ body: { revision: "second" } });
    second.clear();
  });
});
