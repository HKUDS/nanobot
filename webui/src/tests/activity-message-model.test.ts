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
  it("keeps reused call IDs isolated by turn and picks the latest compatible legacy row", () => {
    const call = (id: string, turnId?: string): UIMessage => ({
      ...progressMessage(id, "start"), turnId,
      toolEvents: [{ call_id: "shared", phase: "start", name: "web_search" }],
    });
    const complete = (id: string, turnId?: string): UIMessage => ({
      ...call(id, turnId), toolEvents: [{ call_id: "shared", phase: "end", name: "web_search" }],
    });
    const result = coalesceActivityMessages([
      call("first", "a"), call("second", "b"), complete("finish-a", "a"),
    ]);
    expect(result.map((row) => [row.id, row.toolEvents?.[0].phase])).toEqual([
      ["first", "end"], ["second", "start"],
    ]);
    expect(coalesceActivityMessages([
      call("first", "a"), call("second", "b"), complete("legacy"),
    ]).map((row) => [row.id, row.toolEvents?.[0].phase])).toEqual([
      ["first", "start"], ["second", "end"],
    ]);
  });

  it("processes independent calls with a linear event-read budget", () => {
    let reads = 0;
    const messages: UIMessage[] = Array.from({ length: 1000 }, (_, index) => ({
      id: `${index}`, role: "tool", kind: "trace", content: `tool${index}()`, createdAt: index,
      get toolEvents() {
        reads++;
        return [{ call_id: `${index}`, phase: "end" as const, name: `tool${index}` }];
      },
    }));
    expect(coalesceActivityMessages(messages)).toEqual(messages);
    expect(reads).toBeLessThanOrEqual(messages.length * 4);
  });
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
