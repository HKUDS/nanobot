import { describe, expect, it } from "vitest";

import { coalesceActivityMessages } from "@/components/thread/activity/activity-message-model";
import type { UIMessage } from "@/lib/types";

const trace = 'web_search({"query":"same query"})';

function progressMessage(id: string, phase: "start" | "end" | "error"): UIMessage {
  return {
    id,
    role: "tool",
    kind: "trace",
    content: trace,
    traces: [trace],
    toolEvents: [{ phase, name: "web_search", arguments: { query: "same query" } }],
    createdAt: 1,
  };
}

describe("activity message coalescing", () => {
  it("folds persisted start and terminal progress into one activity", () => {
    const result = coalesceActivityMessages([
      progressMessage("start", "start"),
      progressMessage("end", "end"),
    ]);

    expect(result).toHaveLength(1);
    expect(result[0].toolEvents?.[0]?.phase).toBe("end");
  });

  it("keeps repeated completed calls as separate activities", () => {
    const result = coalesceActivityMessages([
      progressMessage("first", "end"),
      progressMessage("second", "end"),
    ]);

    expect(result).toHaveLength(2);
  });
});
