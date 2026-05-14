import { describe, expect, it } from "vitest";

import { mergeCanonicalHistoryPreservingLongTasks } from "@/lib/thread-history-merge";
import type { UIMessage } from "@/lib/types";

describe("mergeCanonicalHistoryPreservingLongTasks", () => {
  it("re-inserts disk trace rows before the final assistant reply when historical is longer", () => {
    const historical: UIMessage[] = [
      { id: "u1", role: "user", content: "hi", createdAt: 1 },
      { id: "a1", role: "assistant", content: "done", createdAt: 3 },
    ];
    const trace: UIMessage = {
      id: "tr1",
      role: "assistant",
      kind: "trace",
      content: "",
      traces: ["tool x"],
      createdAt: 2,
    };
    const prev: UIMessage[] = [historical[0]!, trace];
    const merged = mergeCanonicalHistoryPreservingLongTasks(prev, historical);
    expect(merged.map((m) => m.id)).toEqual(["u1", "tr1", "a1"]);
  });

  it("places traces after reasoning-only assistant rows, before the final reply", () => {
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
    const trace: UIMessage = {
      id: "tr1",
      role: "assistant",
      kind: "trace",
      content: "",
      traces: ["tool x"],
      createdAt: 2.5,
    };
    const prev: UIMessage[] = [historical[0]!, historical[1]!, trace];
    const merged = mergeCanonicalHistoryPreservingLongTasks(prev, historical);
    expect(merged.map((m) => m.id)).toEqual(["u1", "a_think", "tr1", "a1"]);
  });

  it("prefers disk trace payload when historical shares the same trace id", () => {
    const traceDisk: UIMessage = {
      id: "tr1",
      role: "assistant",
      kind: "trace",
      content: "",
      traces: ["tool x", "tool y"],
      createdAt: 2,
    };
    const traceCanon: UIMessage = {
      ...traceDisk,
      traces: ["tool x"],
    };
    const historical: UIMessage[] = [
      { id: "u1", role: "user", content: "hi", createdAt: 1 },
      traceCanon,
      { id: "a1", role: "assistant", content: "done", createdAt: 3 },
    ];
    const disk: UIMessage[] = [historical[0]!, traceDisk, historical[2]!];
    const merged = mergeCanonicalHistoryPreservingLongTasks(disk, historical);
    const traces = merged.filter((m) => m.kind === "trace");
    expect(traces.length).toBe(1);
    expect(traces[0]!.traces).toEqual(["tool x", "tool y"]);
  });

  it("keeps each turn's traces in that turn after refresh (no tail accumulation)", () => {
    const traceT1: UIMessage = {
      id: "t1",
      role: "tool",
      kind: "trace",
      content: "old",
      traces: Array.from({ length: 40 }, (_, i) => `tool-${i}`),
      createdAt: 2,
    };
    const traceT2: UIMessage = {
      id: "t2",
      role: "tool",
      kind: "trace",
      content: "new",
      traces: ["only-two"],
      createdAt: 5,
    };
    const prev: UIMessage[] = [
      { id: "u1", role: "user", content: "one", createdAt: 1 },
      traceT1,
      { id: "a1", role: "assistant", content: "r1", createdAt: 3 },
      { id: "u2", role: "user", content: "two", createdAt: 4 },
      traceT2,
      { id: "a2", role: "assistant", content: "r2", createdAt: 6 },
    ];
    const historical: UIMessage[] = [
      { id: "u1", role: "user", content: "one", createdAt: 1 },
      { id: "a1", role: "assistant", content: "r1", createdAt: 3 },
      { id: "u2", role: "user", content: "two", createdAt: 4 },
      { id: "a2", role: "assistant", content: "r2", createdAt: 6 },
    ];
    const merged = mergeCanonicalHistoryPreservingLongTasks(prev, historical);
    expect(merged.map((m) => m.id)).toEqual(["u1", "t1", "a1", "u2", "t2", "a2"]);
    const t2row = merged.find((m) => m.id === "t2");
    expect(t2row?.traces?.length).toBe(1);
  });
});
