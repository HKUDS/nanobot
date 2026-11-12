import { expect, it } from "vitest";

import { MemoryLruCache } from "@/lib/memory-lru-cache";

it.each([
  { collection: "Map keys", small: new Map([["turn", "source"]]), large: new Map([["x".repeat(64), "source"]]) },
  { collection: "Map values", small: new Map([["turn", "source"]]), large: new Map([["turn", "x".repeat(64)]]) },
  { collection: "Set members", small: new Set(["turn"]), large: new Set(["x".repeat(64)]) },
])("counts shared nested $collection once and re-estimates changed snapshots", ({ small, large }) => {
  const cache = new MemoryLruCache<{ members: typeof large }>(110, 2);
  const snapshot = { members: small, alias: small };
  cache.set("small", snapshot);
  expect(cache.get("small")).toBe(snapshot);

  cache.set("large", { members: large });
  expect(cache.get("large")).toBeUndefined();
  expect(cache.get("small")).toBe(snapshot);

  // A saved transcript can share mutable collections with its next snapshot.
  if (small instanceof Map) small.set("turn", "x".repeat(64));
  else small.add("x".repeat(64));
  cache.set("small", snapshot);
  expect(cache.get("small")).toBeUndefined();
});
