import { expect, it } from "vitest";
import { ThreadMessageCache } from "@/lib/thread-message-cache";
import { ThreadTranscript } from "@/lib/thread-transcript";
import type { UIMessage } from "@/lib/types";

const rows: UIMessage[] = [{ id: "u", role: "user", content: "hello", createdAt: 1 }];
const snapshot = new ThreadTranscript(rows).save();

it("keeps recently visited chats within the entry budget", () => {
  const cache = new ThreadMessageCache(() => false, 10000, 2);
  cache.set("a", snapshot); cache.set("b", snapshot);
  expect(cache.get("a")?.projection.messages).toBe(rows);
  cache.set("c", snapshot);
  expect([cache.get("a")?.projection.messages, cache.get("b"), cache.get("c")?.projection.messages])
    .toEqual([rows, undefined, rows]);
});

it("bounds large replay snapshots while retaining temporary chats", () => {
  const cache = new ThreadMessageCache((key) => key === "temporary", 4096, 2);
  cache.set("temporary", snapshot);
  cache.set("ordinary", snapshot);
  cache.set("large", new ThreadTranscript([{ ...rows[0], content: "x".repeat(4096) }]).save());
  expect(cache.get("large")).toBeUndefined();
  expect(cache.get("temporary")?.projection.messages).toBe(rows);
  expect(cache.get("ordinary")?.projection.messages).toBe(rows);
  cache.delete("temporary");
  cache.set("small", snapshot);
  expect(cache.get("small")?.projection.messages).toBe(rows);
});

it("keeps the pinned temporary working set outside ordinary byte and entry budgets", () => {
  const cache = new ThreadMessageCache((key) => key.startsWith("temporary"), 4096, 2);
  cache.set("old", snapshot);
  cache.set("recent", snapshot);
  const large = new ThreadTranscript([{ ...rows[0], content: "x".repeat(4096) }]).save();
  cache.set("temporary-a", large);
  cache.set("temporary-b", snapshot);
  cache.set("temporary-a", new ThreadTranscript([{ ...rows[0], content: "x".repeat(8192) }]).save());

  expect(cache.peek("old")).toBe(snapshot);
  expect(cache.peek("recent")).toBe(snapshot);
  expect(cache.get("temporary-a")?.projection.messages[0].content).toHaveLength(8192);
  expect(cache.peek("temporary-b")).toBe(snapshot);

  cache.get("old");
  cache.set("next", snapshot);
  expect(cache.peek("old")).toBe(snapshot);
  expect(cache.peek("recent")).toBeUndefined();
  expect(cache.peek("next")).toBe(snapshot);
  expect(cache.peek("temporary-a")).toBeDefined();
  expect(cache.peek("temporary-b")).toBe(snapshot);
});
