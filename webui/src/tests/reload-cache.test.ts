import { afterEach, describe, expect, it, vi } from "vitest";
import { activateReloadCache, clearReloadCache, readReloadSessions, writeReloadCache } from "@/lib/reload-cache";
import { WebuiThreadCache } from "@/lib/webui-thread-cache";
import { canonicalThreadPayload } from "./thread-test-payload";

afterEach(() => { clearReloadCache(); vi.restoreAllMocks(); });

const thread = canonicalThreadPayload({ schemaVersion: 3, revision: "rev-1", messages: [
  { id: "a", role: "assistant", content: "Saved answer", createdAt: 1 },
] })!;

describe("tab reload cache", () => {
  it("restores authenticated replay into a fresh cache and retains it for another reload", () => {
    activateReloadCache("ws://localhost:8765/?token=old");
    new WebuiThreadCache().set("websocket:a", thread);
    activateReloadCache("ws://localhost:8765/?token=renewed");
    expect(new WebuiThreadCache().get("websocket:a")).toEqual(thread);
    expect(new WebuiThreadCache().get("websocket:a")).toEqual(thread);
    expect(new WebuiThreadCache().get("websocket:b")).toBeUndefined();
  });

  it("does not restore another gateway's data or data after logout", () => {
    activateReloadCache("ws://localhost:8765/");
    new WebuiThreadCache().set("websocket:a", thread);
    activateReloadCache("ws://localhost:8888/");
    expect(new WebuiThreadCache().get("websocket:a")).toBeUndefined();
    clearReloadCache();
    activateReloadCache("ws://localhost:8765/");
    expect(new WebuiThreadCache().get("websocket:a")).toBeUndefined();
  });

  it("removes deleted sessions and ignores malformed replay", () => {
    activateReloadCache("ws://localhost:8765/");
    const cache = new WebuiThreadCache();
    cache.set("websocket:a", thread);
    cache.delete("websocket:a");
    expect(new WebuiThreadCache().get("websocket:a")).toBeUndefined();
    writeReloadCache("thread", { key: "websocket:a", body: { projection: "events", events: [{}] } });
    expect(new WebuiThreadCache().get("websocket:a")).toBeUndefined();
  });

  it("keeps memory caching working when storage fails", () => {
    activateReloadCache("ws://localhost:8765/");
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("quota"); });
    const cache = new WebuiThreadCache();
    cache.set("websocket:a", thread);
    expect(cache.get("websocket:a")).toEqual(thread);
  });

  it("does not persist oversized replay and validates session summaries", () => {
    activateReloadCache("ws://localhost:8765/");
    writeReloadCache("thread", { key: "large", body: "x".repeat(600_000) });
    expect(sessionStorage.getItem("nanobot.reload.v1.thread")).toBeNull();
    writeReloadCache("sessions", [{ key: "bad" }, {
      key: "websocket:a", channel: "websocket", chatId: "a", preview: "Answer", title: "Topic",
    }]);
    expect(readReloadSessions()).toEqual([{
      key: "websocket:a", channel: "websocket", chatId: "a", preview: "Answer", title: "Topic",
      createdAt: null, updatedAt: null,
    }]);
  });
});
