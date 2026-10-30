import { expect, it } from "vitest";

import { MemoryLruCache } from "@/lib/memory-lru-cache";

it.each([
  { collection: "Map keys", small: new Map([["turn", "source"]]), large: new Map([["x".repeat(64), "source"]]) },
  { collection: "Map values", small: new Map([["turn", "source"]]), large: new Map([["turn", "x".repeat(64)]]) },
  { collection: "Set members", small: new Set(["turn"]), large: new Set(["x".repeat(64)]) },
])("counts nested $collection toward the byte budget", ({ small, large }) => {
  const cache = new MemoryLruCache<{ members: typeof large }>(160, 2);
  const snapshot = { members: small };
  cache.set("small", snapshot);
  expect(cache.get("small")).toBe(snapshot);

  cache.set("large", { members: large });
  expect(cache.get("large")).toBeUndefined();

  cache.set("small", snapshot);
  expect(cache.get("small")).toBe(snapshot);
});
