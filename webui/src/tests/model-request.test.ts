import { describe, expect, it } from "vitest";
import { parseWebuiThreadPayload } from "@/lib/api";
import { composerContextSnapshots } from "@/lib/context-graph";
import { composerUsageSnapshots } from "@/lib/model-request";
import { projectWebuiThreadMessages } from "@/lib/thread-display-projection";
import { ThreadTranscript } from "@/lib/thread-transcript";
import type { ThreadProjectionEvent } from "@/lib/types";

const envelope = { chat_id: "chat", turn_id: "turn" };
const request = (sequence: number, extra: Partial<Extract<ThreadProjectionEvent, { event: "model_request" }>> = {}): ThreadProjectionEvent => ({
  ...envelope, event: "model_request", run_id: "run", request_id: `request-${sequence}`,
  sequence, turn_seq: sequence, phase: "started", ...extra,
});
const usage = (count: number) => ({ prompt_tokens: count * 100, completion_tokens: count * 10,
  context_tokens: 100 + count, request_count: count });
const rounds = (count: number) => Array.from({ length: count }, (_, index) => ({ prompt_tokens: 100 + index, completion_tokens: 10 }));
function project(transcript: ThreadTranscript, event: ThreadProjectionEvent, persisted = false) {
  return transcript.project(event, { createId: () => `event-${event.turn_seq}`, now: 1, persisted });
}

describe("model request snapshots", () => {
  it("replays each request's matching file graph and usage after reload", () => {
    const transcript = new ThreadTranscript();
    const first = { nodes: [{ path: "/a.md", name: "a.md", state: "loaded" as const, tokens: 100 }], edges: [] };
    const second = { nodes: [...first.nodes, { path: "/b.md", name: "b.md", state: "discovered" as const, tokens: 0 }], edges: [{ source: "/a.md", target: "/b.md" }] };
    for (const event of [
      request(1, { request_id: "first", context_graph: first }),
      request(2, { request_id: "first", phase: "completed", context_graph: first, round_usages: rounds(1) }),
      request(3, { request_id: "second", context_graph: second }),
      request(4, { request_id: "second", phase: "completed", context_graph: second, round_usages: rounds(2) }),
    ]) project(transcript, event, true);
    expect(transcript.modelRequests.get("turn")?.contextSnapshots?.map((snapshot) => ({
      graph: snapshot.graph, tokens: snapshot.usage?.prompt_tokens,
    }))).toEqual([{ graph: first, tokens: 100 }, { graph: second, tokens: 101 }]);
  });
  it("validates request identity, phase, sequence, and usage at the history boundary", () => {
    for (const invalid of [{ phase: "unknown" }, { sequence: -1 }, { run_id: null }, { usage: { context_tokens: "123" } }]) {
      expect(() => parseWebuiThreadPayload({ schemaVersion: 3, projection: "events", events: [{ ...request(1), ...invalid }] })).toThrow();
    }
    expect(parseWebuiThreadPayload({ schemaVersion: 3, projection: "events", events: [] }).events).toEqual([]);
  });
  it("updates active usage cumulatively, retains it during the next call, and replaces the final snapshot", () => {
    const transcript = new ThreadTranscript();
    const events: ThreadProjectionEvent[] = [{ ...envelope, event: "user_message", text: "hello", starts_turn: true, turn_seq: 0 }];
    project(transcript, events[0]);
    for (let count = 1; count <= 3; count++) {
      const event = request(count * 2, { phase: "completed", usage: usage(count), round_usages: rounds(count), context_window_tokens: 128000 });
      events.push(event); project(transcript, event);
      expect(composerUsageSnapshots(transcript.messages, transcript.modelRequests).at(-1)?.usage?.request_count).toBe(count);
      expect(composerUsageSnapshots(transcript.messages, transcript.modelRequests).at(-1)?.roundUsages).toHaveLength(count);
    }
    const started = request(7);
    events.push(started); project(transcript, started);
    expect(composerUsageSnapshots(transcript.messages, transcript.modelRequests).at(-1)?.usage?.context_tokens).toBe(103);
    const answer: ThreadProjectionEvent = { ...envelope, event: "delta", text: "answer", turn_seq: 8 };
    events.push(answer); project(transcript, answer);
    expect(composerUsageSnapshots(transcript.messages, transcript.modelRequests)).toHaveLength(1);
    const end: ThreadProjectionEvent = { ...envelope, event: "turn_end", turn_seq: 9, usage: usage(3), round_usages: rounds(3) };
    events.push(end); project(transcript, end);
    expect(composerUsageSnapshots(transcript.messages, transcript.modelRequests).flatMap((entry) => entry.roundUsages ?? [])).toHaveLength(3);
    const replay = new ThreadTranscript();
    events.forEach((event) => project(replay, event, true));
    expect(composerUsageSnapshots(replay.messages, replay.modelRequests).at(-1)?.usage).toEqual(usage(3));
    project(transcript, request(10, { usage: usage(99) }));
    expect(composerUsageSnapshots(transcript.messages, transcript.modelRequests).at(-1)?.usage).toEqual(usage(3));
  });

  it.each([false, true])("invalidates compacted context until fresh completion (persisted=%s)", (persisted) => {
    const transcript = new ThreadTranscript();
    const send = (event: ThreadProjectionEvent) => project(transcript, event, persisted);
    const latest = () => composerUsageSnapshots(transcript.messages, transcript.modelRequests).at(-1)!;
    send(request(1, { phase: "completed", usage: usage(1), round_usages: rounds(1) }));
    expect(projectWebuiThreadMessages(transcript.messages)).toEqual([]);
    send({ ...envelope, event: "context_compaction", compaction_id: "compact", phase: "started", turn_seq: 2 });
    expect(latest().compacted).toBe(false);
    send({ ...envelope, event: "context_compaction", compaction_id: "compact", phase: "succeeded", turn_seq: 3 });
    expect(latest().compacted).toBe(true);
    expect(latest().roundUsages).toBeUndefined();
    send(request(4, { usage: usage(1), round_usages: rounds(1) }));
    expect(latest().compacted).toBe(true);
    expect(latest().roundUsages).toBeUndefined();
    expect(projectWebuiThreadMessages(transcript.messages).map((row) => row.kind)).toEqual(["compaction"]);
    const smaller = { ...usage(2), context_tokens: 50 };
    send(request(5, { request_id: "request-4", phase: "completed", usage: smaller, round_usages: rounds(2) }));
    expect(latest().compacted).toBe(false);
    expect(latest().usage?.context_tokens).toBe(50);
    send({ ...envelope, event: "turn_end", turn_seq: 6, usage: smaller, round_usages: rounds(2) });
    expect(latest().compacted).toBe(false);
    expect(latest().usage?.context_tokens).toBe(50);
    expect(latest().roundUsages).toEqual(rounds(2));
    expect(projectWebuiThreadMessages(transcript.messages).map((row) => row.kind)).toEqual(["compaction"]);
  });

  it.each([false, true])("does not treat turn-end cumulative usage as fresh after compaction (persisted=%s)", (persisted) => {
    const transcript = new ThreadTranscript();
    for (const event of [
      request(1, { phase: "completed", usage: usage(1), round_usages: rounds(1) }),
      { ...envelope, event: "context_compaction", compaction_id: "compact", phase: "started", turn_seq: 2 },
      { ...envelope, event: "context_compaction", compaction_id: "compact", phase: "succeeded", turn_seq: 3 },
      { ...envelope, event: "turn_end", turn_seq: 4, usage: usage(1), round_usages: rounds(1) },
    ] as ThreadProjectionEvent[]) project(transcript, event, persisted);
    const snapshot = composerUsageSnapshots(transcript.messages, transcript.modelRequests).at(-1)!;
    expect(snapshot.compacted).toBe(true);
    expect(snapshot.roundUsages).toBeUndefined();
  });

  it("preserves legacy compaction invalidation and historical rounds without request events", () => {
    const transcript = new ThreadTranscript();
    project(transcript, { ...envelope, event: "delta", text: "answer", turn_seq: 1 });
    project(transcript, { ...envelope, event: "turn_end", usage: usage(1), round_usages: rounds(1), turn_seq: 2 });
    project(transcript, { ...envelope, turn_id: "compact-turn", event: "context_compaction", compaction_id: "compact", phase: "succeeded", turn_seq: 1 });
    const snapshots = composerUsageSnapshots(transcript.messages, transcript.modelRequests);
    expect(snapshots.at(-1)?.compacted).toBe(true);
    expect(snapshots.flatMap((row) => row.roundUsages ?? [])).toEqual(rounds(1));
  });

  it("rejects duplicates, reordered snapshots, and superseded runs after checkpoint restoration", () => {
    const transcript = new ThreadTranscript();
    project(transcript, request(2, { usage: usage(2) }));
    project(transcript, request(1, { usage: usage(1) }));
    project(transcript, request(2, { usage: usage(99) }));
    project(transcript, request(1, { run_id: "new-run", turn_seq: 3, usage: usage(3) }));
    const restored = new ThreadTranscript([], transcript.save());
    project(restored, request(4, { usage: usage(99) }));
    expect(composerUsageSnapshots(restored.messages, restored.modelRequests).at(-1)?.usage).toEqual(usage(3));
    expect(projectWebuiThreadMessages(restored.messages)).toEqual([]);
  });

  it("reconciles reconnect history without replacing newer live usage", () => {
    const transcript = new ThreadTranscript();
    const initial = request(1, { phase: "completed", usage: usage(1), round_usages: rounds(1) });
    project(transcript, initial);
    const read = transcript.begin("latest");
    project(transcript, request(2, { phase: "completed", usage: usage(2), round_usages: rounds(2) }));
    expect(transcript.accept({ schemaVersion: 3, projection: "events", events: [initial] }, read)).toBe(true);
    expect(composerUsageSnapshots(transcript.messages, transcript.modelRequests).at(-1)?.usage).toEqual(usage(2));
    const fresh = new ThreadTranscript();
    expect(fresh.accept(parseWebuiThreadPayload({ schemaVersion: 3, projection: "events", events: [initial, request(2)] }), fresh.begin("initial"))).toBe(true);
    expect(composerUsageSnapshots(fresh.messages, fresh.modelRequests).at(-1)?.roundUsages).toHaveLength(1);
  });

  it("retains proactive usage without body rows across history and clears it with a completed history reset", () => {
    const transcript = new ThreadTranscript();
    const events: ThreadProjectionEvent[] = [
      { ...envelope, turn_id: "old", event: "message", text: "Old answer", turn_seq: 1, created_at_ms: 1000 },
      { ...envelope, turn_id: "old", event: "turn_end", turn_seq: 2, usage: usage(1), round_usages: rounds(1) },
    ];
    const body = { schemaVersion: 3 as const, projection: "events" as const, events, completed_turn_ids: ["old"] };
    expect(transcript.accept(body, transcript.begin("initial"))).toBe(true);
    const read = transcript.begin("latest");
    project(transcript, request(1, { phase: "completed", created_at_ms: 2000, usage: usage(2), round_usages: rounds(2) }));
    expect(transcript.accept(body, read)).toBe(true);
    expect(composerUsageSnapshots(transcript.messages, transcript.modelRequests).map((row) => row.usage)).toEqual([usage(1), usage(2)]);
    project(transcript, { ...envelope, event: "turn_end", turn_seq: 2, usage: usage(2), round_usages: rounds(2) });
    const restored = new ThreadTranscript([], transcript.save());
    expect(composerUsageSnapshots(restored.messages, restored.modelRequests).at(-1)?.usage).toEqual(usage(2));
    expect(restored.accept({ schemaVersion: 3, projection: "events", events: [] }, restored.begin("latest"))).toBe(true);
    expect(composerUsageSnapshots(restored.messages, restored.modelRequests)).toEqual([]);
  });

  it("backfills missed answer and tool history while retaining newer live usage", () => {
    const transcript = new ThreadTranscript();
    const user: ThreadProjectionEvent = { ...envelope, event: "user_message", text: "question", starts_turn: true, turn_seq: 0 };
    const initial = request(1);
    project(transcript, user);
    project(transcript, initial);
    const read = transcript.begin("latest");
    const latest = request(3, { turn_seq: 5, phase: "completed", usage: usage(2), round_usages: rounds(2), context_window_tokens: 128000 });
    project(transcript, latest);
    const events: ThreadProjectionEvent[] = [user, initial,
      request(2, { phase: "completed", usage: usage(1), round_usages: rounds(1) }),
      { ...envelope, event: "stream_end", turn_seq: 3, stream_id: "missed-answer", text: "missed answer", resuming: true },
      { ...envelope, event: "message", turn_seq: 4, kind: "tool_hint", text: "", tool_events: [{
        version: 1, name: "read_file", call_id: "missed-tool", phase: "end",
        arguments: { path: "example.txt" }, result: "missed tool result",
      }] },
    ];
    expect(transcript.accept({ schemaVersion: 3, projection: "events", events,
      active_turn_id: "turn", completed_turn_ids: [], has_pending_tool_calls: true }, read)).toBe(true);
    expect(transcript.messages.map((row) => row.content)).toContain("missed answer");
    expect(transcript.messages.flatMap((row) => row.toolEvents ?? [])).toMatchObject([
      { call_id: "missed-tool", phase: "end", result: "missed tool result" },
    ]);
    expect(composerUsageSnapshots(transcript.messages, transcript.modelRequests).at(-1)).toMatchObject({
      usage: usage(2), roundUsages: rounds(2), contextWindowTokens: 128000,
    });
    const restored = new ThreadTranscript([], transcript.save());
    const final: ThreadProjectionEvent = { ...envelope, event: "turn_end", turn_seq: 6,
      usage: usage(3), round_usages: rounds(3), context_window_tokens: 64000 };
    project(restored, final);
    expect(composerUsageSnapshots(restored.messages, restored.modelRequests).at(-1)).toMatchObject({
      usage: usage(3), roundUsages: rounds(3), contextWindowTokens: 64000,
    });
    const reloaded = new ThreadTranscript();
    expect(reloaded.accept({ schemaVersion: 3, projection: "events", events: [...events, latest, final],
      completed_turn_ids: ["turn"] }, reloaded.begin("initial"))).toBe(true);
    expect(composerUsageSnapshots(reloaded.messages, reloaded.modelRequests).at(-1)?.usage).toEqual(usage(3));
    expect(reloaded.messages.map((row) => row.content)).toContain("missed answer");
  });

  it.each([false, true])("does not treat a missing-usage completion as fresh after compaction (replay=%s)", (persisted) => {
    const transcript = new ThreadTranscript();
    project(transcript, request(1, { phase: "completed", usage: usage(1), round_usages: rounds(1) }), persisted);
    project(transcript, { ...envelope, event: "context_compaction", compaction_id: "compact", phase: "succeeded", turn_seq: 2 }, persisted);
    project(transcript, request(3, { usage: usage(1), round_usages: rounds(1) }), persisted);
    project(transcript, request(4, { phase: "completed", usage: usage(1), round_usages: rounds(1) }), persisted);
    expect(composerUsageSnapshots(transcript.messages, transcript.modelRequests).at(-1)?.compacted).toBe(true);
    project(transcript, request(5, { phase: "failed", usage: usage(2), round_usages: rounds(2) }), persisted);
    expect(composerUsageSnapshots(transcript.messages, transcript.modelRequests).at(-1)?.compacted).toBe(false);
  });

  it("keeps active history snapshots and bounds rounds to the latest eight calls", () => {
    const replay = new ThreadTranscript();
    project(replay, request(1, { phase: "completed", usage: usage(10), round_usages: rounds(10) }), true);
    project(replay, request(2), true);
    const snapshot = composerUsageSnapshots(replay.messages, replay.modelRequests).at(-1)!;
    expect(snapshot.roundUsages).toHaveLength(8);
    expect(snapshot.roundUsages?.[0].prompt_tokens).toBe(102);
  });
});


it.each([false, true])("starts a new graph history and estimated meter at compaction (persisted=%s)", (persisted) => {
  const transcript = new ThreadTranscript();
  const oldGraph = { nodes: [{ path: "/read.md", name: "read.md", state: "loaded" as const, tokens: 300 }], edges: [] };
  const systemGraph = { nodes: [{ path: "/SOUL.md", name: "SOUL.md", state: "loaded" as const, tokens: 40 }], edges: [] };
  project(transcript, request(1, { context_graph: oldGraph, phase: "completed", usage: usage(1) }), persisted);
  const event = parseWebuiThreadPayload({ schemaVersion: 3, projection: "events", events: [{ ...envelope, event: "context_compaction", compaction_id: "boundary",
    phase: "succeeded", turn_seq: 2, context_snapshot: { graph: systemGraph, estimated_tokens: 1200, context_window_tokens: 10000 } }] }).events[0];
  expect(event).not.toBeNull();
  if (!event) throw new Error("Compaction snapshot rejected");
  project(transcript, event, persisted);
  expect(composerContextSnapshots(transcript.messages, transcript.modelRequests)).toEqual([
    { id: "compaction-boundary", graph: systemGraph, estimatedTokens: 1200, contextWindowTokens: 10000 },
  ]);
  expect(composerUsageSnapshots(transcript.messages, transcript.modelRequests).at(-1)).toMatchObject({
    compacted: true, estimatedContextTokens: 1200, contextWindowTokens: 10000,
  });
  const reloadedRequests = new Map(transcript.modelRequests);
  reloadedRequests.set("older-turn", {
    ...transcript.modelRequests.get("turn")!, createdAt: 0,
    contextSnapshots: [{ id: "older-request", graph: oldGraph, turnSeq: 1 }],
  });
  expect(composerContextSnapshots(transcript.messages, reloadedRequests).map((s) => s.id))
    .toEqual(["compaction-boundary"]);
  project(transcript, request(3, { context_graph: systemGraph, phase: "completed", usage: { context_tokens: 1300, request_count: 2 } }), persisted);
  expect(composerContextSnapshots(transcript.messages, transcript.modelRequests).map((s) => s.id)).toEqual(["compaction-boundary", "request-3"]);
  expect(composerUsageSnapshots(transcript.messages, transcript.modelRequests).at(-1)).toMatchObject({ compacted: false, usage: { context_tokens: 1300 } });
});

it.each(["failed", "cancelled", "completed"] as const)("does not borrow previous usage for a %s request without measurement", (phase) => {
  const transcript = new ThreadTranscript();
  const graph = { nodes: [{ path: "/a.md", name: "a.md", state: "loaded" as const, tokens: 20 }], edges: [] };
  project(transcript, request(1, { phase: "completed", context_graph: graph, request_usage: usage(1), round_usages: rounds(1) }));
  project(transcript, request(2, { phase, context_graph: graph, request_usage: null, round_usages: rounds(1) }));
  const frames = composerContextSnapshots(transcript.messages, transcript.modelRequests);
  expect(frames[0].usage).toEqual(usage(1));
  expect(frames[1].usage).toBeUndefined();
});


it.each([false, true])("shows the active system graph immediately after compaction (persisted=%s)", (persisted) => {
  const transcript = new ThreadTranscript();
  const oldGraph = { nodes: [{ path: "/before.py", name: "before.py", state: "loaded" as const, tokens: 50 }], edges: [] };
  const systemGraph = { nodes: [{ path: "/SOUL.md", name: "SOUL.md", state: "loaded" as const, tokens: 40 }], edges: [] };
  project(transcript, request(1, { request_id: "active", context_graph: oldGraph }), persisted);
  const event = parseWebuiThreadPayload({ schemaVersion: 3, projection: "events", events: [{ ...envelope,
    event: "context_compaction", compaction_id: "boundary", phase: "succeeded", turn_seq: 2, context_graph: systemGraph,
  }] }).events[0];
  project(transcript, event, persisted);
  expect(composerContextSnapshots(transcript.messages, transcript.modelRequests)).toEqual([
    { id: "compaction-boundary", graph: systemGraph },
  ]);
  project(transcript, request(3, { request_id: "active", phase: "completed", context_graph: systemGraph }), persisted);
  expect(composerContextSnapshots(transcript.messages, transcript.modelRequests).map((snapshot) => snapshot.graph))
    .toEqual([systemGraph, systemGraph]);
});
