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

  it.each(["inline", "references"])("restores all 50 growing graph frames from compact tab storage (%s)", (format) => {
    activateReloadCache("ws://localhost:8765/?token=first");
    const nodes = Array.from({ length: 300 }, (_, index) => ({
      path: `/workspace/${index}.md`, name: `${index}.md`, tokens: 256, state: "loaded",
    }));
    const edges = nodes.flatMap((node, source) => [1, 2, 3].flatMap((offset) => source + offset < nodes.length
      ? [{ source: node.path, target: nodes[source + offset].path }] : []));
    const graphs = Array.from({ length: 50 }, (_, index) => {
      const count = 251 + index;
      const paths = new Set(nodes.slice(0, count).map((node) => node.path));
      return { nodes: nodes.slice(0, count), edges: edges.filter((edge) => paths.has(edge.source) && paths.has(edge.target)) };
    });
    const table = Object.fromEntries(graphs.map((graph, index) => [String(index), {
      nodes: graph.nodes.map((node) => nodes.indexOf(node)), edges: graph.edges.map((edge) => edges.indexOf(edge)),
    }]));
    const events = graphs.map((graph, index) => ({
      event: "model_request", chat_id: "growing", request_id: String(index), run_id: "run", sequence: index + 1,
      phase: "completed", request_usage: { context_tokens: 10000 + index },
      ...(format === "inline" ? { context_graph: structuredClone(graph) } : { context_graph_ref: String(index) }),
    }));
    const body = parseWebuiThreadPayload({ schemaVersion: 3, sessionKey: "websocket:growing", revision: "growing-50",
      projection: "events", active_turn_id: null, page: { before_cursor: "older", has_more_before: true },
      events: [{ event: "context_compaction", chat_id: "growing", compaction_id: "checkpoint", phase: "succeeded",
        ...(format === "inline" ? { context_graph: structuredClone(graphs[0]) } : { context_graph_ref: "0" }),
        context_snapshot: { estimated_tokens: 100, context_window_tokens: 100000,
          ...(format === "inline" ? { graph: structuredClone(graphs[0]) } : { graph_ref: "0" }) } }, ...events],
      ...(format === "references" ? { context_graphs: table, context_graph_nodes: nodes, context_graph_edges: edges } : {}),
    });
    const cache = new WebuiThreadCache();
    cache.set("websocket:growing", body);
    expect(cache.get("websocket:growing")).toBe(body);
    const raw = sessionStorage.getItem("nanobot.reload.v1.thread");
    expect(raw).not.toBeNull();
    expect(raw!.length).toBeLessThanOrEqual(512 * 1024);
    const restored = new WebuiThreadCache().get("websocket:growing");
    expect(restored).toEqual(body);
    expect(restored).not.toHaveProperty("context_graphs");
    expect(restored).not.toHaveProperty("context_graph_nodes");
    expect(restored).not.toHaveProperty("context_graph_edges");
    const frames = restored!.events.filter((event) => event.event === "model_request");
    expect(frames).toHaveLength(50);
    for (let index = 0; index < frames.length; index += 1) {
      expect(frames[index].context_graph).toEqual(graphs[index]);
      expect(frames[index].request_usage?.context_tokens).toBe(10000 + index);
    }
    expect(frames[0].context_graph?.nodes[0]).toBe(frames[49].context_graph?.nodes[0]);
    expect(frames[0].context_graph?.edges[0]).toBe(frames[49].context_graph?.edges[0]);
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
