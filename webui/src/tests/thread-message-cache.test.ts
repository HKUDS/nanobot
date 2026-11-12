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

it("bounds large replay snapshots without charging temporary chats to the reusable budget", () => {
  const cache = new ThreadMessageCache((key) => key === "temporary", 4096, 2);
  cache.set("ordinary-a", snapshot);
  cache.set("ordinary-b", snapshot);
  const large = new ThreadTranscript([{ ...rows[0], content: "x".repeat(4096) }]).save();
  cache.set("large", large);
  expect(cache.get("large")).toBeUndefined();
  expect(cache.peek("ordinary-a")).toBe(snapshot);
  expect(cache.peek("ordinary-b")).toBe(snapshot);

  cache.set("temporary", large);
  expect(cache.get("temporary")).toBe(large);
  expect(cache.get("ordinary-a")).toBe(snapshot);
  expect(cache.peek("ordinary-b")).toBe(snapshot);

  cache.set("small", snapshot);
  expect(cache.peek("ordinary-a")).toBe(snapshot);
  expect(cache.peek("ordinary-b")).toBeUndefined();
  expect(cache.get("small")).toBe(snapshot);
  cache.delete("temporary");
  expect(cache.get("small")).toBe(snapshot);
});
