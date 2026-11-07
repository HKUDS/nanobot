import { MemoryLruCache } from "./memory-lru-cache";
import { parseWebuiThreadPayload } from "./api";
import { readReloadCache, removeReloadCache, writeReloadCache } from "./reload-cache";
import type { ContextGraph, WebuiThreadPersistedPayload } from "./types";

/** Persist shared graph entities instead of expanding them in every replay frame. */
function reloadPayload(body: WebuiThreadPersistedPayload): unknown {
  function table<T extends object>(key: (value: T) => string) {
    const values: T[] = [];
    const identities = new Map<T, number>();
    const keys = new Map<string, number>();
    return { values, index(value: T): number {
      const known = identities.get(value);
      if (known !== undefined) return known;
      const valueKey = key(value);
      let index = keys.get(valueKey);
      if (index === undefined) {
        index = values.length;
        values.push(value);
        keys.set(valueKey, index);
      }
      identities.set(value, index);
      return index;
    } };
  }
  const nodes = table<ContextGraph["nodes"][number]>((node) => JSON.stringify([node.path, node.name, node.tokens, node.state]));
  const edges = table<ContextGraph["edges"][number]>((edge) => JSON.stringify([edge.source, edge.target]));
  const references = new Map<ContextGraph, string>();
  const graphs: Record<string, { nodes: number[]; edges: number[] }> = {};
  const reference = (graph: ContextGraph): string => {
    const known = references.get(graph);
    if (known !== undefined) return known;
    const key = String(references.size);
    references.set(graph, key);
    graphs[key] = { nodes: graph.nodes.map(nodes.index), edges: graph.edges.map(edges.index) };
    return key;
  };
  const events = body.events.map((event) => {
    if (event.event === "model_request" && event.context_graph) {
      const { context_graph, ...rest } = event;
      return { ...rest, context_graph_ref: reference(context_graph) };
    }
    if (event.event === "context_compaction" && event.context_snapshot) {
      const { graph, ...snapshot } = event.context_snapshot;
      return { ...event, context_snapshot: { ...snapshot, graph_ref: reference(graph) } };
    }
    return event;
  });
  return references.size ? { ...body, events, context_graphs: graphs,
    context_graph_nodes: nodes.values, context_graph_edges: edges.values } : body;
}

/** Bounded canonical replay cache; the most recent snapshot also survives tab reloads. */
export class WebuiThreadCache extends MemoryLruCache<WebuiThreadPersistedPayload> {
  private readonly listeners = new Map<string, Set<(body: WebuiThreadPersistedPayload) => void>>();

  constructor(
    maxBytes = 16 * 1024 * 1024,
    maxEntries = 12,
  ) {
    super(maxBytes, maxEntries);
  }

  override get(key: string): WebuiThreadPersistedPayload | undefined {
    const cached = super.get(key);
    if (cached) return cached;
    const stored = readReloadCache("thread");
    if (!stored || typeof stored !== "object" || !("key" in stored)
      || stored.key !== key || !("body" in stored)) return undefined;
    try {
      const body = parseWebuiThreadPayload(stored.body);
      this.set(key, body);
      return super.get(key);
    } catch {
      removeReloadCache("thread");
      return undefined;
    }
  }

  override set(key: string, body: WebuiThreadPersistedPayload): void {
    super.set(key, body);
    if (super.get(key)) writeReloadCache("thread", { key, body: reloadPayload(body) });
    for (const listener of this.listeners.get(key) ?? []) listener(body);
  }

  subscribe(key: string, listener: (body: WebuiThreadPersistedPayload) => void): () => void {
    const listeners = this.listeners.get(key) ?? new Set();
    listeners.add(listener);
    this.listeners.set(key, listeners);
    return () => {
      listeners.delete(listener);
      if (listeners.size === 0) this.listeners.delete(key);
    };
  }

  override delete(key: string): void {
    super.delete(key);
    const stored = readReloadCache("thread");
    if (stored && typeof stored === "object" && "key" in stored && stored.key === key) {
      removeReloadCache("thread");
    }
  }

  override clear(): void {
    super.clear();
    removeReloadCache("thread");
  }
}

export const webuiThreadCache = new WebuiThreadCache();
