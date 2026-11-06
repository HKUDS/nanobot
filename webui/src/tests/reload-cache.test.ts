import { afterEach, describe, expect, it, vi } from "vitest";
import { activateReloadCache, clearReloadCache, readReloadSessions, writeReloadCache } from "@/lib/reload-cache";
import { parseWebuiThreadPayload } from "@/lib/api";
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

  it("restores all 50 graph references and usages from tab storage", () => {
    activateReloadCache("ws://localhost:8765/?token=first");
    const events = Array.from({ length: 50 }, (_, index) => ({
      event: "model_request", chat_id: "growing", request_id: String(index), run_id: "run", sequence: index + 1,
      phase: "completed", request_usage: { context_tokens: 10000 + index },
      context_graph_detail_ref: `graph-${index}`,
    }));
    const body = parseWebuiThreadPayload({ schemaVersion: 3, sessionKey: "websocket:growing", revision: "growing-50",
      projection: "events", active_turn_id: null, page: { before_cursor: "older", has_more_before: true }, events,
    });
    const cache = new WebuiThreadCache();
    cache.set("websocket:growing", body);
    expect(cache.get("websocket:growing")).toBe(body);
    const raw = sessionStorage.getItem("nanobot.reload.v1.thread");
    expect(raw).not.toBeNull();
    expect(raw!.length).toBeLessThanOrEqual(512 * 1024);
    const restored = new WebuiThreadCache().get("websocket:growing");
    expect(restored).toEqual(body);
    const frames = restored!.events.filter((event) => event.event === "model_request");
    expect(frames).toHaveLength(50);
    for (let index = 0; index < frames.length; index += 1) {
      expect(frames[index].context_graph_detail_ref).toBe(`graph-${index}`);
      expect(frames[index].request_usage?.context_tokens).toBe(10000 + index);
    }
  });

  it("restores deferred references and compaction estimates without materializing graphs", () => {
    activateReloadCache("ws://localhost:8765/");
    const body = parseWebuiThreadPayload({ schemaVersion: 3, projection: "events", events: [
      { event: "context_compaction", chat_id: "chat", compaction_id: "compact", phase: "succeeded",
        context_snapshot: { graph_detail_ref: "baseline", estimated_tokens: 100, context_window_tokens: 1000 } },
      { event: "model_request", chat_id: "chat", request_id: "request", run_id: "run", sequence: 2, phase: "completed",
        context_graph_detail_ref: "request-graph", request_usage: { context_tokens: 200 }, round_usages: [{ prompt_tokens: 200 }] },
    ] });
    new WebuiThreadCache().set("websocket:chat", body);
    expect(new WebuiThreadCache().get("websocket:chat")).toEqual(body);
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
