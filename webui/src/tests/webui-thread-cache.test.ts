import { describe, expect, it } from "vitest";

import { WebuiThreadCache } from "@/lib/webui-thread-cache";
import type { WebuiThreadPersistedPayload } from "@/lib/types";

function payload(id: string): WebuiThreadPersistedPayload {
  return {
    schemaVersion: 3,
    revision: `rev-${id}`,
    messages: [{ id, role: "assistant", content: id, createdAt: 1 }],
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

  it("does not retain a payload larger than the byte budget", () => {
    const cache = new WebuiThreadCache(64, 2);
    cache.set("large", payload("x".repeat(100)));

    expect(cache.get("large")).toBeUndefined();
  });
});
