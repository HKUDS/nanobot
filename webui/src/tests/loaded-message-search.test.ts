import { describe, expect, it } from "vitest";

import { findLoadedMessagePreview } from "@/lib/loaded-message-search";
import { ThreadMessageCache } from "@/lib/thread-message-cache";
import { ThreadTranscript } from "@/lib/thread-transcript";
import type { UIMessage } from "@/lib/types";

function message(content: string, role: UIMessage["role"] = "assistant"): UIMessage {
  return { id: content, role, content, createdAt: 1 };
}

describe("loaded message search", () => {
  it("finds literal Chinese, code and multiword substrings, not words across messages", () => {
    const groups = [[message("我们讨论权限与配对", "user"), message("Use session_history.py at 25% with Full Access")]];
    for (const query of ["权限", "配对", "session_history.py", "25%", "full access"]) {
      expect(findLoadedMessagePreview(groups, query)?.toLowerCase()).toContain(query);
    }
    expect(findLoadedMessagePreview(groups, "full use")).toBeUndefined();
    expect(findLoadedMessagePreview(groups, "配对 use")).toBeUndefined();
    expect(findLoadedMessagePreview(groups, "session.history")).toBeUndefined();
  });

  it("uses visible user/answer text and bounds excerpts around a late match", () => {
    const groups = [[
      message("tool-only", "tool"),
      { ...message(""), reasoning: "reasoning-only" },
      { ...message("trace-only"), kind: "trace" as const },
      { ...message("/model hidden-preset", "user"), turnId: "command" },
      { ...message("hidden-reply"), turnId: "command" },
      message(`${"旧内容\n".repeat(500)}Visible TOKEN-42 ${"后续内容".repeat(100)}`),
    ]];
    for (const query of ["tool-only", "reasoning-only", "trace-only", "hidden-preset", "hidden-reply"]) {
      expect(findLoadedMessagePreview(groups, query)).toBeUndefined();
    }
    const preview = findLoadedMessagePreview(groups, "token-42")!;
    expect(preview).toContain("Visible TOKEN-42");
    expect(preview).toMatch(/^….*…$/);
    expect(preview.length).toBeLessThanOrEqual(162);
  });

  it("keeps original excerpt offsets when lowercasing expands Unicode characters", () => {
    const text = `${"İ".repeat(200)} CamelCaseTarget ${"tail".repeat(80)}`;
    expect(findLoadedMessagePreview([[message(text)]], "camelcasetarget")).toContain("CamelCaseTarget");
  });
});

describe("loaded message ownership", () => {
  it("searches cached snapshots without changing LRU eviction order", () => {
    const cache = new ThreadMessageCache(() => false, 100_000, 2);
    cache.set("old", new ThreadTranscript([message("old needle")]).save());
    cache.set("recent", new ThreadTranscript([message("recent needle")]).save());
    expect(findLoadedMessagePreview(cache.readLoadedMessages("old"), "needle")).toBe("old needle");
    cache.set("next", new ThreadTranscript([message("next needle")]).save());
    expect(cache.readLoadedMessages("old")).toEqual([]);
    expect(findLoadedMessagePreview(cache.readLoadedMessages("recent"), "needle")).toBe("recent needle");
  });

  it("uses mounted messages and already-loaded navigation pages instead of stale snapshots", () => {
    const cache = new ThreadMessageCache(() => false);
    cache.set("chat", new ThreadTranscript([message("replaced answer")]).save());
    cache.setLoadedMessages("chat", [[message("current answer")], [message("loaded older page")]]);
    expect(findLoadedMessagePreview(cache.readLoadedMessages("chat"), "replaced")).toBeUndefined();
    expect(findLoadedMessagePreview(cache.readLoadedMessages("chat"), "current")).toBe("current answer");
    expect(findLoadedMessagePreview(cache.readLoadedMessages("chat"), "older")).toBe("loaded older page");
    cache.set("chat", new ThreadTranscript([message("current answer")]).save());
    cache.deleteLoadedMessages("chat");
    expect(findLoadedMessagePreview(cache.readLoadedMessages("chat"), "current")).toBe("current answer");
    cache.delete("chat");
    expect(cache.readLoadedMessages("chat")).toEqual([]);
  });
});
