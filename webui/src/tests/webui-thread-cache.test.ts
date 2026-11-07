import { describe, expect, it } from "vitest";

import { WebuiThreadCache } from "@/lib/webui-thread-cache";
import type { WebuiThreadPersistedPayload } from "@/lib/types";

function payload(id: string): WebuiThreadPersistedPayload {
  return {
    schemaVersion: 3,
    revision: `rev-${id}`,
    projection: "events",
    events: [{ event: "message", chat_id: id, text: id }],
  };
}

describe("WebuiThreadCache", () => {
  it("evicts the least recently used session", () => {
    const cache = new WebuiThreadCache(10_000, 2);
    cache.set("a", payload("a"));
    cache.set("b", payload("b"));
    expect(cache.get("a")).toBeDefined();

    cache.set("c", payload("c"));

    expect(cache.get("a")?.revision).toBe("rev-a");
    expect(cache.get("b")).toBeUndefined();
    expect(cache.get("c")?.revision).toBe("rev-c");
  });

  it("publishes payloads to mounted threads even when they exceed the byte budget", () => {
    const cache = new WebuiThreadCache(64, 2);
    const published: WebuiThreadPersistedPayload[] = [];
    const unsubscribe = cache.subscribe("large", (body) => published.push(body));
    const large = payload("x".repeat(100));
    cache.set("large", large);

    expect(cache.get("large")).toBeUndefined();
    expect(published).toEqual([large]);
    unsubscribe();
    cache.set("large", large);
    expect(published).toHaveLength(1);
  });
});
