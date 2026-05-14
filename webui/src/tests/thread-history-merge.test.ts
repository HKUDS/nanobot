import { describe, expect, it } from "vitest";

import { mergeCanonicalHistoryPreservingLongTasks } from "@/lib/thread-history-merge";
import type { UIMessage } from "@/lib/types";

describe("mergeCanonicalHistoryPreservingLongTasks", () => {
  it("re-inserts long_task before the last assistant row of the turn (final reply)", () => {
    const historical: UIMessage[] = [
      { id: "u1", role: "user", content: "hi", createdAt: 1 },
      {
        id: "a1",
        role: "assistant",
        content: "done",
        createdAt: 2,
      },
    ];
    const lt: UIMessage = {
      id: "lt1",
      role: "assistant",
      kind: "long_task",
      content: "long_task ·",
      createdAt: 1.5,
      longTask: {
        run_id: "r1",
        event: "task_complete",
        goal: "g",
      },
    };
    const prev = [historical[0]!, lt];
    const merged = mergeCanonicalHistoryPreservingLongTasks(prev, historical);
    expect(merged.map((m) => m.id)).toEqual(["u1", "lt1", "a1"]);
  });

  it("places long_task after reasoning-only assistant rows, before the final reply", () => {
    const historical: UIMessage[] = [
      { id: "u1", role: "user", content: "hi", createdAt: 1 },
      {
        id: "a_think",
        role: "assistant",
        content: "",
        reasoning: "…",
        createdAt: 2,
      },
      {
        id: "a1",
        role: "assistant",
        content: "done",
        createdAt: 3,
      },
    ];
    const lt: UIMessage = {
      id: "lt1",
      role: "assistant",
      kind: "long_task",
      content: "long_task ·",
      createdAt: 2.5,
      longTask: { run_id: "r1", event: "task_complete", goal: "g" },
    };
    const prev: UIMessage[] = [historical[0]!, historical[1]!, lt];
    const merged = mergeCanonicalHistoryPreservingLongTasks(prev, historical);
    expect(merged.map((m) => m.id)).toEqual(["u1", "a_think", "lt1", "a1"]);
  });
});
