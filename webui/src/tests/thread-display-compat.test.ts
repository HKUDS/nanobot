import { describe, expect, it } from "vitest";

import { deriveTitle, isModelCommandText, visibleSessionPreview } from "@/lib/format";
import {
  normalizeLegacyLongTaskMessages,
  projectWebuiThreadMessages,
} from "@/lib/thread-display-compat";
import type { UIMessage } from "@/lib/types";

const STARTED_AT = Date.UTC(2026, 6, 25, 12, 34, 0);

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

describe("normalizeLegacyLongTaskMessages", () => {
  it("maps legacy long_task rows to trace lines", () => {
    const legacy = {
      id: "x",
      role: "assistant",
      kind: "long_task",
      content: "long_task · done",
      createdAt: 1,
    } as unknown as UIMessage;
    const out = normalizeLegacyLongTaskMessages([legacy]);
    expect(out[0]!.kind).toBe("trace");
    expect(out[0]!.role).toBe("tool");
    expect(out[0]!.traces).toEqual(["long_task · done"]);
  });

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

  it("uses the nearest user start for legacy rows without turn metadata", () => {
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
