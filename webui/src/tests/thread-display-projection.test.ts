import { describe, expect, it } from "vitest";

import { deriveTitle, isModelCommandText, visibleSessionPreview } from "@/lib/format";
import { historyContentSnapshot, projectWebuiThreadMessages, sameHistoryContent } from "@/lib/thread-display-projection";
import type { UIMessage } from "@/lib/types";

const STARTED_AT = Date.UTC(2026, 6, 25, 12, 34, 0);

it("reuses completed historical rows across streaming updates and recalculates changed start times", () => {
  const prompt: UIMessage = { id: "u", role: "user", content: "hello", createdAt: 100 };
  const answer: UIMessage = { id: "a", role: "assistant", content: "world", latencyMs: 50, createdAt: 120 };
  const first = projectWebuiThreadMessages([prompt, answer]);
  const second = projectWebuiThreadMessages([prompt, answer, { id: "next", role: "user", content: "next", createdAt: 200 }]);
  expect(second[1]).toBe(first[1]);
  expect(projectWebuiThreadMessages([{ ...prompt, createdAt: 200 }, answer])[1].completedAt).toBe(250);
});

function message(
  role: UIMessage["role"],
  overrides: Partial<Omit<UIMessage, "role">> = {},
): UIMessage {
  return {
    id: role,
    role,
    content: role,
    createdAt: STARTED_AT,
    ...overrides,
  };
}

describe("command display projection", () => {
  it("removes model and silent-command turns without hiding concurrent replies", () => {
    const visible = projectWebuiThreadMessages([
      message("user", { id: "model", content: "/model fast", turnId: "model-turn" }),
      message("assistant", {
        id: "model-reply",
        content: "Switched model preset to fast.",
        turnId: "model-turn",
      }),
      message("user", { id: "silent", content: "/restart", turnId: "webui-system:restart" }),
      message("assistant", {
        id: "reply",
        content: "This unrelated reply stays visible.",
        turnId: "other-turn",
      }),
    ]);

    expect(visible.map(({ content }) => content)).toEqual([
      "This unrelated reply stays visible.",
    ]);
    expect([
      isModelCommandText("/MODEL@nanobot fast"),
      isModelCommandText("/modelish"),
    ]).toEqual([true, false]);
    expect(visibleSessionPreview("Switched model preset to `fast`.")).toBe("");
    expect(deriveTitle("## Model\n- Current model: `gpt-5.5`", "New chat")).toBe("New chat");
  });
});

describe("projectWebuiThreadMessages", () => {
  it("marks only fixed replies belonging to a compact command turn", () => {
    const rows = [
      message("user", { content: " /COMPACT ", turnId: "compact" }),
      message("assistant", { content: "Nothing to compact.", turnId: "compact" }),
      message("assistant", {
        content: "Unable to compact context. Check the logs and try again.", turnId: "compact",
      }),
      message("assistant", { content: "Nothing to compact.", turnId: "unrelated" }),
      message("assistant", { content: "Nothing to compact." }),
      message("assistant", { content: "Nothing to compact.", turnId: "compact", isStreaming: true }),
      message("assistant", { content: "Quoted: Nothing to compact.", turnId: "compact" }),
    ];
    const projected = projectWebuiThreadMessages(rows);
    expect(projected.map(({ compactReply }) => compactReply)).toEqual([
      undefined, "empty", "failed", undefined, undefined, undefined, undefined,
    ]);
    expect(projected.map(({ content }) => content)).toEqual(rows.map(({ content }) => content));
    expect(projectWebuiThreadMessages(projected)).toEqual(projected);
  });

  it("derives replayed completion time from the matching user turn", () => {
    const firstOutputAt = STARTED_AT + 5_000;
    const latencyMs = 13_000;
    const visible = projectWebuiThreadMessages([
      message("user", { turnId: "turn-1" }),
      message("assistant", {
        turnId: "turn-1",
        createdAt: firstOutputAt,
        latencyMs,
      }),
    ]);

    expect(visible[1]?.completedAt).toBe(STARTED_AT + latencyMs);
    expect(visible[1]?.completedAt).not.toBe(firstOutputAt + latencyMs);
  });

  it("preserves the exact completion time received for a live turn", () => {
    const completedAt = STARTED_AT + 13_000;
    const visible = projectWebuiThreadMessages([
      message("user", { turnId: "turn-1" }),
      message("assistant", {
        turnId: "turn-1",
        latencyMs: 13_000,
        completedAt,
        createdAt: STARTED_AT + 5_000,
      }),
    ]);

    expect(visible[1]?.completedAt).toBe(completedAt);
  });

  it("does not borrow a timestamp from a different turn", () => {
    const visible = projectWebuiThreadMessages([
      message("user", { turnId: "turn-1" }),
      message("assistant", {
        turnId: "turn-2",
        latencyMs: 13_000,
        createdAt: STARTED_AT + 60_000,
      }),
    ]);

    expect(visible[1]?.completedAt).toBeUndefined();
  });

  it("uses the nearest user start for rows without turn metadata", () => {
    const visible = projectWebuiThreadMessages([
      message("user"),
      message("assistant", {
        latencyMs: 13_000,
        createdAt: STARTED_AT + 5_000,
      }),
    ]);

    expect(visible[1]?.completedAt).toBe(STARTED_AT + 13_000);
  });

  it("does not attach a previous user turn to proactive messages", () => {
    const visible = projectWebuiThreadMessages([
      message("user"),
      message("assistant", {
        source: { kind: "cron" },
        latencyMs: 13_000,
        createdAt: STARTED_AT + 26 * 60_000,
      }),
    ]);

    expect(visible[1]?.completedAt).toBeUndefined();
  });
});


describe("history content admission", () => {
  it("compares displayed answers independently of replay identities and completion telemetry", () => {
    const before = historyContentSnapshot([message("assistant", { content: "First\n\nSecond" })], null);
    const after = historyContentSnapshot([
      message("assistant", { id: "slice-1", content: "First", turnId: "turn-1", turnSeq: 1 }),
      message("assistant", { id: "slice-2", content: "Second", turnId: "turn-1", turnSeq: 2,
        completedAt: STARTED_AT + 1000, latencyMs: 1000, usage: { total_tokens: 42 } }),
    ], null);
    expect(sameHistoryContent(before, after)).toBe(true);
    expect(sameHistoryContent(after, historyContentSnapshot([
      message("assistant", { content: "First\n\nSecond\n\nThird" }),
    ], null))).toBe(false);
  });

  it("ignores hidden task creation and transport placeholders", () => {
    const prompt = message("user");
    const before = historyContentSnapshot([prompt], null);
    const after = historyContentSnapshot([prompt,
      message("assistant", { content: 'subagent({"action":"create"})', kind: "trace",
        toolEvents: [{ name: "subagent", phase: "end", arguments: { action: "create" } }] }),
      message("assistant", { content: "", completedAt: STARTED_AT + 1000 }),
    ], null);
    expect(sameHistoryContent(before, after)).toBe(true);
  });

  it("recognizes a visible fork boundary without treating a leading marker as content", () => {
    const rows = [message("user"), message("assistant")];
    const before = historyContentSnapshot(rows, null);
    expect(sameHistoryContent(before, historyContentSnapshot(rows, 0))).toBe(true);
    expect(sameHistoryContent(before, historyContentSnapshot(rows, 1))).toBe(false);
  });

  it("compares nested tool payloads by content, including results and attachments", () => {
    const tool = { name: "read_file", phase: "end", arguments: { path: "test.txt" },
      result: { lines: ["first", "second"], truncated: false } };
    const trace = message("assistant", { content: "read_file(test.txt)", kind: "trace", toolEvents: [tool] });
    const before = historyContentSnapshot([trace], null);
    const replay = { ...trace, id: "replayed", toolEvents: [{ ...tool,
      arguments: { path: "test.txt" }, result: { truncated: false, lines: ["first", "second"] } }] };
    expect(sameHistoryContent(before, historyContentSnapshot([replay], null))).toBe(true);
    for (const changed of [
      { ...tool, result: { lines: ["first", "changed"], truncated: false } },
      { ...tool, result: { lines: ["first"], truncated: false } },
      { ...tool, result: null, error: "Not found" },
      { ...tool, files: [{ name: "test.txt", url: "/files/test.txt" }] },
    ]) {
      expect(sameHistoryContent(before, historyContentSnapshot([{ ...trace, toolEvents: [changed] }], null))).toBe(false);
    }
  });

  it("detects newly available media without relying on new message identities", () => {
    const original = message("user", { images: [{ name: "picture.png" }] });
    const before = historyContentSnapshot([original], null);
    expect(sameHistoryContent(before, historyContentSnapshot([
      { ...original, images: [{ name: "picture.png", url: undefined }] },
    ], null))).toBe(true);
    expect(sameHistoryContent(before, historyContentSnapshot([
      { ...original, images: [{ name: "picture.png", url: "/files/picture.png" }] },
    ], null))).toBe(false);
  });
});
