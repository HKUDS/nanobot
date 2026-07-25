import { describe, expect, it } from "vitest";

import { deriveTitle, isModelCommandText, visibleSessionPreview } from "@/lib/format";
import {
  normalizeLegacyLongTaskMessages,
  projectWebuiThreadMessages,
} from "@/lib/thread-display-compat";
import type { UIMessage } from "@/lib/types";

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
    const message = (
      id: string,
      role: UIMessage["role"],
      content: string,
      turnId?: string,
    ): UIMessage => ({ id, role, content, createdAt: 1, turnId });
    const visible = projectWebuiThreadMessages([
      message("model", "user", "/model fast", "model-turn"),
      message("model-reply", "assistant", "Switched model preset to fast.", "model-turn"),
      message("silent", "user", "/restart", "webui-system:restart"),
      message("reply", "assistant", "This unrelated reply stays visible.", "other-turn"),
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
  it("derives replayed completion time from the matching user turn", () => {
    const startedAt = Date.UTC(2026, 6, 25, 12, 34, 0);
    const firstOutputAt = startedAt + 5_000;
    const latencyMs = 13_000;
    const visible = projectWebuiThreadMessages([
      {
        id: "user",
        role: "user",
        content: "Write a story",
        turnId: "turn-1",
        createdAt: startedAt,
      },
      {
        id: "assistant",
        role: "assistant",
        content: "Once upon a time",
        turnId: "turn-1",
        latencyMs,
        createdAt: firstOutputAt,
      },
    ]);

    expect(visible[1]?.completedAt).toBe(startedAt + latencyMs);
    expect(visible[1]?.completedAt).not.toBe(firstOutputAt + latencyMs);
  });

  it("preserves the exact completion time received for a live turn", () => {
    const completedAt = Date.UTC(2026, 6, 25, 12, 34, 13);
    const visible = projectWebuiThreadMessages([
      {
        id: "user",
        role: "user",
        content: "Write a story",
        turnId: "turn-1",
        createdAt: completedAt - 13_000,
      },
      {
        id: "assistant",
        role: "assistant",
        content: "Once upon a time",
        turnId: "turn-1",
        latencyMs: 13_000,
        completedAt,
        createdAt: completedAt - 8_000,
      },
    ]);

    expect(visible[1]?.completedAt).toBe(completedAt);
  });

  it("does not borrow a timestamp from a different turn", () => {
    const visible = projectWebuiThreadMessages([
      {
        id: "user",
        role: "user",
        content: "First request",
        turnId: "turn-1",
        createdAt: Date.UTC(2026, 6, 25, 12, 34, 0),
      },
      {
        id: "assistant",
        role: "assistant",
        content: "Unmatched replay page",
        turnId: "turn-2",
        latencyMs: 13_000,
        createdAt: Date.UTC(2026, 6, 25, 12, 35, 0),
      },
    ]);

    expect(visible[1]?.completedAt).toBeUndefined();
  });

  it("uses the nearest user start for legacy rows without turn metadata", () => {
    const startedAt = Date.UTC(2026, 6, 25, 12, 34, 0);
    const visible = projectWebuiThreadMessages([
      {
        id: "legacy-user",
        role: "user",
        content: "Legacy request",
        createdAt: startedAt,
      },
      {
        id: "legacy-assistant",
        role: "assistant",
        content: "Legacy answer",
        latencyMs: 13_000,
        createdAt: startedAt + 5_000,
      },
    ]);

    expect(visible[1]?.completedAt).toBe(startedAt + 13_000);
  });

  it("does not attach a previous user turn to proactive messages", () => {
    const visible = projectWebuiThreadMessages([
      {
        id: "user",
        role: "user",
        content: "Earlier request",
        createdAt: Date.UTC(2026, 6, 25, 12, 34, 0),
      },
      {
        id: "automation",
        role: "assistant",
        content: "Scheduled update",
        source: { kind: "cron" },
        latencyMs: 13_000,
        createdAt: Date.UTC(2026, 6, 25, 13, 0, 0),
      },
    ]);

    expect(visible[1]?.completedAt).toBeUndefined();
  });
});
