import { describe, expect, it } from "vitest";

import { createThreadProjectionState, projectThreadEvent, projectThreadEvents } from "@/lib/thread-event-projection";
import { normalizeActivityTimeline } from "@/lib/activity-timeline";
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
  it("routes late snapshots by stream without moving same-text answers or stealing the active cursor", () => {
    let state = createThreadProjectionState();
    const emit = (event: ThreadProjectionEvent) => {
      state = projectThreadEvent(state, event, { createId: () => `live-${state.messages.length}`, now: 100 });
    };
    emit({ event: "delta", chat_id: "chat", turn_id: "turn", stream_id: "first", turn_seq: 1, text: "Same answer" });
    emit({ event: "stream_end", chat_id: "chat", turn_id: "turn", stream_id: "first", turn_seq: 2, resuming: true });
    emit({ event: "message", chat_id: "chat", turn_id: "turn", turn_seq: 3, kind: "tool_hint", text: "read_file(first)" });
    emit({ event: "delta", chat_id: "chat", turn_id: "turn", stream_id: "second", turn_seq: 4, text: "Same answer" });
    const source = { provider: "fixture", model: "fixture", preset: "fixture" };
    emit({ event: "stream_end", chat_id: "chat", turn_id: "turn", stream_id: "first", turn_seq: 5, text: "Same answer", response_sources: [source] });
    expect(state.activeAssistantId).toBe("live-2");
    emit({ event: "delta", chat_id: "chat", turn_id: "turn", stream_id: "second", turn_seq: 6, text: " continued" });
    emit({ event: "stream_end", chat_id: "chat", turn_id: "turn", stream_id: "empty", turn_seq: 7, response_sources: [] });
    expect(state.activeAssistantId).toBe("live-2");
    expect(normalizeActivityTimeline(state.messages).map((unit) => unit.type === "message"
      ? unit.message.content : unit.messages.map((message) => message.content).join("")))
      .toEqual(["Same answer", "read_file(first)", "Same answer continued"]);
    expect(state.messages[0]).toMatchObject({ projectionStartSeq: 1, turnSeq: 5, responseSources: [source] });
    expect(state.messages[2]).toMatchObject({ projectionStartSeq: 4, turnSeq: 6, streamId: "second" });
  });

  it("updates an identified reasoning snapshot without duplicating it or closing another phase", () => {
    const messages = projectThreadEvents([
      { event: "reasoning_delta", chat_id: "chat", turn_id: "turn", stream_id: "first", turn_seq: 1, text: "First thought" },
      { event: "reasoning_end", chat_id: "chat", turn_id: "turn", stream_id: "first", turn_seq: 2, text: "First thought" },
      { event: "delta", chat_id: "chat", turn_id: "turn", stream_id: "first", turn_seq: 3, text: "Answer" },
      { event: "stream_end", chat_id: "chat", turn_id: "turn", stream_id: "first", turn_seq: 4, resuming: true },
      { event: "reasoning_delta", chat_id: "chat", turn_id: "turn", turn_seq: 5, text: "Second thought" },
      { event: "reasoning_end", chat_id: "chat", turn_id: "turn", stream_id: "first", turn_seq: 6, text: "First thought revised" },
      { event: "reasoning_delta", chat_id: "chat", turn_id: "turn", turn_seq: 7, text: " continued" },
    ]);
    expect(messages).toHaveLength(2);
    expect(messages[0]).toMatchObject({
      content: "Answer", reasoning: "First thought revised", streamId: "first", reasoningStreamId: "first", projectionStartSeq: 1,
    });
    expect(messages[1]).toMatchObject({ reasoning: "Second thought continued", projectionStartSeq: 5 });
    expect(normalizeActivityTimeline(messages).some((unit) => unit.type === "message" && unit.message.content === "Answer")).toBe(true);
  });

  it("retains completion latency for a live identified reasoning snapshot", () => {
    const now = 1_700_000_000_000;
    let state = projectThreadEvent(createThreadProjectionState(), {
      event: "reasoning_delta", chat_id: "chat", stream_id: "reasoning", text: "Thought",
    }, { createId: () => "live", now });
    state = projectThreadEvent(state, {
      event: "reasoning_end", chat_id: "chat", stream_id: "reasoning", text: "Thought",
    }, { createId: () => "end", now: now + 75 });
    expect(state.messages).toHaveLength(1);
    expect(state.messages[0]).toMatchObject({ reasoning: "Thought", reasoningStreaming: false, latencyMs: 75 });
  });

  it("keeps one cumulative merge_next answer through completed HTTP replay", () => {
    const messages = projectThreadEvents([
      { event: "stream_end", chat_id: "chat", turn_id: "turn", stream_id: "answer", turn_seq: 2, text: "First ", resuming: true, merge_next: true, projection_id: "replay-one" },
      { event: "reasoning_end", chat_id: "chat", turn_id: "turn", stream_id: "answer", turn_seq: 3, text: "More reasoning", projection_id: "replay-reasoning" },
      { event: "stream_end", chat_id: "chat", turn_id: "turn", stream_id: "answer", turn_seq: 5, text: "First last", projection_id: "replay-two" },
      { event: "turn_end", chat_id: "chat", turn_id: "turn", turn_seq: 6 },
    ]);
    expect(messages).toHaveLength(1);
    expect(messages[0]).toMatchObject({
      id: "replay-one", content: "First last", reasoning: "More reasoning",
      streamId: "answer", reasoningStreamId: "answer", projectionStartSeq: 2, turnSeq: 5,
    });
  });

  it.each(["First ", "![plot](/api/media/signature/immutable-plot.png)\n\n"])(
    "keeps legacy cumulative replay contributions around tools: %s", (prefix) => {
      const messages = projectThreadEvents([
        { event: "stream_end", chat_id: "chat", turn_id: "turn", stream_id: "answer", turn_seq: 2, text: prefix, resuming: true, merge_next: true },
        { event: "message", chat_id: "chat", turn_id: "turn", turn_seq: 3, kind: "tool_hint", text: "web_search(query)" },
        { event: "stream_end", chat_id: "chat", turn_id: "turn", stream_id: "answer", turn_seq: 5, text: prefix + "After tool." },
        { event: "turn_end", chat_id: "chat", turn_id: "turn", turn_seq: 6 },
      ]);
      expect(normalizeActivityTimeline(messages).map((unit) => unit.type === "message"
        ? unit.message.content : unit.messages.map((message) => message.content).join("")))
        .toEqual([prefix.trim(), "web_search(query)", "After tool."]);
      expect(messages[0]).toMatchObject({ content: prefix, projectionStartSeq: 2 });
      expect(messages[2]).toMatchObject({ content: "After tool.", projectionStartSeq: 5 });
    },
  );

  it("preserves the stream's position when a complete message replaces its active row", () => {
    const messages = projectThreadEvents([
      { event: "delta", chat_id: "chat", turn_id: "turn", stream_id: "answer", turn_seq: 1, text: "Partial" },
      { event: "message", chat_id: "chat", turn_id: "turn", turn_seq: 3, text: "Complete answer" },
      { event: "turn_end", chat_id: "chat", turn_id: "turn", turn_seq: 4 },
    ]);
    expect(messages).toHaveLength(1);
    expect(messages[0]).toMatchObject({ content: "Complete answer", projectionStartSeq: 1, turnSeq: 3 });
  });

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


it("uses deterministic unknown replay time and preserves distinct same-text inputs", () => {
  const events: ThreadProjectionEvent[] = [
    { event: "user_message", chat_id: "chat", text: "same", starts_turn: true, turn_id: "input-one", projection_id: "u1" },
    { event: "turn_end", chat_id: "chat", turn_id: "input-one" },
    { event: "user_message", chat_id: "chat", text: "same", starts_turn: true, turn_id: "input-two", projection_id: "u2" },
  ];
  const messages = projectThreadEvents(events);
  expect(messages.map((message) => message.id)).toEqual(["u1", "u2"]);
  expect(messages.map((message) => message.createdAt)).toEqual([0, 0]);
  expect(projectThreadEvents(events)).toEqual(messages);
});
