import { expect, it } from "vitest";
import { ThreadMessageCache } from "@/lib/thread-message-cache";
import type { UIMessage } from "@/lib/types";

const rows: UIMessage[] = [{ id: "u", role: "user", content: "hello", createdAt: 1 }];

it("keeps recently visited chats within the entry budget", () => {
  const cache = new ThreadMessageCache(() => false, 10000, 2);
  cache.set("a", rows); cache.set("b", rows);
  expect(cache.get("a")).toBe(rows);
  cache.set("c", rows);
  expect([cache.get("a"), cache.get("b"), cache.get("c")]).toEqual([rows, undefined, rows]);
});

it("bounds large replay snapshots while retaining temporary chats", () => {
  const cache = new ThreadMessageCache((key) => key === "temporary", 1000, 2);
  cache.set("temporary", rows);
  cache.set("large", [{ ...rows[0], content: "x".repeat(1000) }]);
  expect(cache.get("large")).toBeUndefined();
  expect(cache.get("temporary")).toBe(rows);
  cache.delete("temporary");
  cache.set("small", rows);
  expect(cache.get("small")).toBe(rows);
});
