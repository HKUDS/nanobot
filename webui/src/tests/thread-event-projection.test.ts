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
  "fileEdits",
  "images",
  "media",
  "cliApps",
  "mcpPresets",
  "sessionMentions",
  "reasoning",
  "latencyMs",
  "source",
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
  it.each(cases)("projects persisted $name events", (fixtureCase) => {
    const messages = projectThreadEvents(fixtureEvents(fixtureCase.transcript));
    expect(normalizeProjection(messages)).toEqual(fixtureCase.expected);
  });
});
