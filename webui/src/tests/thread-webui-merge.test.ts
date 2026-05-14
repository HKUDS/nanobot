import { describe, expect, it } from "vitest";

import { mergeWebuiDiskSnapshotWithHistorical } from "@/lib/thread-webui-merge";
import type { UIMessage } from "@/lib/types";

describe("mergeWebuiDiskSnapshotWithHistorical", () => {
  it("prefers historical when disk is empty", () => {
    const historical: UIMessage[] = [
      { id: "1", role: "user", content: "hi", createdAt: 1 },
    ];
    expect(mergeWebuiDiskSnapshotWithHistorical([], historical)).toEqual(historical);
  });

  it("prefers longer disk transcript when there is no ephemeral trace row", () => {
    const disk: UIMessage[] = [
      { id: "1", role: "user", content: "hello", createdAt: 1 },
      { id: "2", role: "assistant", content: "long reply", createdAt: 2 },
    ];
    const historical: UIMessage[] = [
      { id: "1", role: "user", content: "hello", createdAt: 1 },
    ];
    expect(mergeWebuiDiskSnapshotWithHistorical(disk, historical)).toEqual(disk);
  });

  it("prefers historical when it is longer than disk (no trace)", () => {
    const disk: UIMessage[] = [
      { id: "1", role: "user", content: "hello", createdAt: 1 },
    ];
    const historical: UIMessage[] = [
      { id: "1", role: "user", content: "hello", createdAt: 1 },
      { id: "2", role: "assistant", content: "reply", createdAt: 2 },
    ];
    expect(mergeWebuiDiskSnapshotWithHistorical(disk, historical)).toEqual(historical);
  });

  it("injects trace rows from disk when historical has more messages", () => {
    const disk: UIMessage[] = [
      { id: "u1", role: "user", content: "hi", createdAt: 1 },
      {
        id: "tr1",
        role: "assistant",
        kind: "trace",
        content: "",
        traces: ["…"],
        createdAt: 2,
      },
    ];
    const historical: UIMessage[] = [
      { id: "u1", role: "user", content: "hi", createdAt: 1 },
      { id: "a1", role: "assistant", content: "reply", createdAt: 3 },
    ];
    const out = mergeWebuiDiskSnapshotWithHistorical(disk, historical);
    expect(out.map((m) => m.id)).toEqual(["u1", "tr1", "a1"]);
  });

  it("merges disk + cached list without duplicating the same trace id", () => {
    const trace: UIMessage = {
      id: "tr1",
      role: "assistant",
      kind: "trace",
      content: "",
      traces: ["a"],
      createdAt: 2,
    };
    const prev: UIMessage[] = [
      { id: "u1", role: "user", content: "hi", createdAt: 1 },
      trace,
      { id: "a1", role: "assistant", content: "reply", createdAt: 3 },
    ];
    const disk: UIMessage[] = [
      prev[0]!,
      { ...trace, traces: ["a", "b"] },
      prev[2]!,
    ];
    const out = mergeWebuiDiskSnapshotWithHistorical(disk, prev);
    expect(out.filter((m) => m.kind === "trace")).toHaveLength(1);
    expect(out.find((m) => m.kind === "trace")?.traces).toEqual(["a", "b"]);
  });
});
