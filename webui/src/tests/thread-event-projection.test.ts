import { describe, expect, it } from "vitest";

import { projectThreadEvents } from "@/lib/thread-event-projection";
import type { ThreadProjectionEvent, UIMessage } from "@/lib/types";
import projectionFixture from "./fixtures/live-replay-event-projection.json";

interface ProjectionFixtureCase {
  name: string;
  transcript: Array<Record<string, unknown>>;
  expected: Array<Record<string, unknown>>;
}

const cases = (
  projectionFixture as unknown as { cases: ProjectionFixtureCase[] }
).cases;

const SEMANTIC_MESSAGE_FIELDS = [
  "role",
  "content",
  "kind",
  "traces",
  "toolEvents",
  "traceDetail",
  "fileEdits",
  "images",
  "media",
  "cliApps",
  "mcpPresets",
  "sessionMentions",
  "reasoning",
  "latencyMs",
  "source",
  "responseSources",
  "turnId",
  "turnPhase",
  "turnSeq",
] as const satisfies ReadonlyArray<keyof UIMessage>;

function fixtureEvents(records: Array<Record<string, unknown>>): ThreadProjectionEvent[] {
  return records.flatMap((record, index) => {
    if (record.event === "user") {
      return [{
        ...record,
        event: "user_message" as const,
        starts_turn: true,
        projection_id: `fixture-${index}`,
      } as unknown as ThreadProjectionEvent];
    }
    return [{
      ...record,
      projection_id: `fixture-${index}`,
    } as unknown as ThreadProjectionEvent];
  });
}

function normalizeProjection(messages: UIMessage[]): Array<Record<string, unknown>> {
  const segmentAliases = new Map<string, string>();
  return messages.map((message) => {
    const row: Record<string, unknown> = {};
    for (const field of SEMANTIC_MESSAGE_FIELDS) {
      const value = message[field];
      if (value !== undefined && value !== null) row[field] = value;
    }
    if (message.activitySegmentId) {
      let alias = segmentAliases.get(message.activitySegmentId);
      if (!alias) {
        alias = `segment-${segmentAliases.size + 1}`;
        segmentAliases.set(message.activitySegmentId, alias);
      }
      row.activitySegmentId = alias;
    }
    return row;
  });
}

describe("canonical thread event projection", () => {
  it.each(["message", "stream_end"] as const)("preserves recorded sources in %s replay", (event) => {
    const source = { provider: "xai", model: "grok", preset: "saved backup", fallback: true };
    const messages = projectThreadEvents([
      { event, chat_id: "chat", text: "Recovered", response_sources: [source] },
      { event: "turn_end", chat_id: "chat" },
      { event: "message", chat_id: "chat", text: "Legacy response" },
    ]);
    expect(messages[0].responseSources).toEqual([source]);
    expect(messages[1].responseSources).toBeUndefined();
  });

  it("clears unknown source metadata on a textless stream end", () => {
    const source = { provider: "xai", model: "grok", preset: "backup", fallback: true };
    const messages = projectThreadEvents([
      { event: "delta", chat_id: "chat", text: "Mixed answer", response_sources: [source] },
      { event: "stream_end", chat_id: "chat", response_sources: [] },
      { event: "turn_end", chat_id: "chat" },
    ]);
    expect(messages[0].responseSources).toEqual([]);
  });

  it.each(cases)("projects persisted $name events", (fixtureCase) => {
    const messages = projectThreadEvents(fixtureEvents(fixtureCase.transcript));
    expect(normalizeProjection(messages)).toEqual(fixtureCase.expected);
  });

  it("keeps deferred activity rows separately addressable in one segment", () => {
    const firstDetail = { ref: "2.history-aaaaaaaaaaaaaaaaaaaa", bytes: 40_000, traceCount: 1 };
    const secondDetail = { ref: "2.history-bbbbbbbbbbbbbbbbbbbb", bytes: 41_000, traceCount: 1 };

    const messages = projectThreadEvents([
      {
        event: "message",
        chat_id: "chat-1",
        text: "exec(…)",
        kind: "progress",
        projection_id: "history-aaaaaaaaaaaaaaaaaaaa",
        trace_detail: firstDetail,
      },
      {
        event: "message",
        chat_id: "chat-1",
        text: "read_file(…)",
        kind: "tool_hint",
        projection_id: "history-bbbbbbbbbbbbbbbbbbbb",
        trace_detail: secondDetail,
      },
    ]);

    expect(messages).toHaveLength(2);
    expect(messages.map((message) => message.traceDetail)).toEqual([
      firstDetail,
      secondDetail,
    ]);
    expect(messages[0].activitySegmentId).toBe(messages[1].activitySegmentId);
  });
});
