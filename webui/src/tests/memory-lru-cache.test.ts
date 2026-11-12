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
  expect(cache.get("small")).toBe(snapshot);
});

it("invalidates an oversized replacement without evicting unrelated entries", () => {
  const cache = new MemoryLruCache<string>(12, 2);
  cache.set("old", "aa");
  cache.set("recent", "bb");

  cache.set("recent", "x".repeat(7));
  expect(cache.peek("recent")).toBeUndefined();
  expect(cache.peek("old")).toBe("aa");

  cache.set("next", "cc");
  cache.set("latest", "dd");
  expect(cache.peek("old")).toBeUndefined();
  expect(cache.peek("next")).toBe("cc");
  expect(cache.peek("latest")).toBe("dd");
});

it("uses reads, but not peeks, to select byte-budget eviction victims", () => {
  const cache = new MemoryLruCache<string>(12, 3);
  cache.set("old", "aa");
  cache.set("recent", "bb");
  expect(cache.get("old")).toBe("aa");

  cache.set("next", "ccc");
  expect(cache.peek("recent")).toBeUndefined();
  expect(cache.peek("old")).toBe("aa");

  cache.set("latest", "dd");
  expect(cache.peek("old")).toBeUndefined();
  expect(cache.peek("next")).toBe("ccc");
  expect(cache.peek("latest")).toBe("dd");
});

it("counts objects shared by arrays, maps and sets only once within a snapshot", () => {
  const shared = { text: "x".repeat(40) };
  const snapshot = {
    rows: [shared, shared],
    byId: new Map([["row", shared]]),
    selected: new Set([shared]),
  };
  const cache = new MemoryLruCache<typeof snapshot>(260, 2);
  cache.set("shared", snapshot);
  expect(cache.peek("shared")).toBe(snapshot);

  cache.set("copies", {
    rows: [{ ...shared }, { ...shared }],
    byId: new Map([["row", { ...shared }]]),
    selected: new Set([{ ...shared }]),
  });
  expect(cache.peek("copies")).toBeUndefined();
  expect(cache.peek("shared")).toBe(snapshot);
});

it("charges each snapshot independently even when they share objects", () => {
  const row = { text: "x".repeat(40) };
  const cache = new MemoryLruCache<{ row: typeof row }>(200, 2);
  cache.set("old", { row });
  const next = { row };
  cache.set("next", next);
  expect(cache.peek("old")).toBeUndefined();
  expect(cache.peek("next")).toBe(next);
});

it("re-estimates mutable collections shared with an earlier snapshot", () => {
  const cache = new MemoryLruCache<{ members: Map<string, string> }>(200, 2);
  const members = new Map([["turn", "short"]]);
  const snapshot = { members };
  cache.set("other", { members: new Map() });
  cache.set("mutable", snapshot);

  members.set("turn", "x".repeat(80));
  cache.set("mutable", { members });
  expect(cache.peek("mutable")).toBeUndefined();
  expect(cache.peek("other")).toBeDefined();

  members.set("turn", "short");
  cache.set("mutable", snapshot);
  expect(cache.peek("mutable")).toBe(snapshot);
});
