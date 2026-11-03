import { describe, expect, it } from "vitest";
import { parseWebuiThreadPayload } from "@/lib/api";
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
      expect(composerUsageSnapshots(transcript.messages).at(-1)?.usage?.request_count).toBe(count);
      expect(composerUsageSnapshots(transcript.messages).at(-1)?.roundUsages).toHaveLength(count);
    }
    const started = request(7);
    events.push(started); project(transcript, started);
    expect(composerUsageSnapshots(transcript.messages).at(-1)?.usage?.context_tokens).toBe(103);
    const answer: ThreadProjectionEvent = { ...envelope, event: "delta", text: "answer", turn_seq: 8 };
    events.push(answer); project(transcript, answer);
    expect(composerUsageSnapshots(transcript.messages)).toHaveLength(1);
    const end: ThreadProjectionEvent = { ...envelope, event: "turn_end", turn_seq: 9, usage: usage(3), round_usages: rounds(3) };
    events.push(end); project(transcript, end);
    expect(composerUsageSnapshots(transcript.messages).flatMap((entry) => entry.roundUsages ?? [])).toHaveLength(3);
    const replay = new ThreadTranscript();
    events.forEach((event) => project(replay, event, true));
    expect(composerUsageSnapshots(replay.messages).at(-1)?.usage).toEqual(usage(3));
    project(transcript, request(10, { usage: usage(99) }));
    expect(composerUsageSnapshots(transcript.messages).at(-1)?.usage).toEqual(usage(3));
  });

  it.each([false, true])("invalidates compacted context until fresh completion (persisted=%s)", (persisted) => {
    const transcript = new ThreadTranscript();
    const send = (event: ThreadProjectionEvent) => project(transcript, event, persisted);
    const latest = () => composerUsageSnapshots(transcript.messages).at(-1)!;
    send(request(1, { phase: "completed", usage: usage(1), round_usages: rounds(1) }));
    expect(projectWebuiThreadMessages(transcript.messages)).toEqual([]);
    send({ ...envelope, event: "context_compaction", compaction_id: "compact", phase: "started", turn_seq: 2 });
    expect(latest().compacted).toBe(false);
    send({ ...envelope, event: "context_compaction", compaction_id: "compact", phase: "succeeded", turn_seq: 3 });
    expect(latest().compacted).toBe(true);
    expect(latest().roundUsages).toEqual(rounds(1));
    send(request(4, { usage: usage(1), round_usages: rounds(1) }));
    expect(latest().compacted).toBe(true);
    expect(latest().roundUsages).toEqual(rounds(1));
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
    const snapshot = composerUsageSnapshots(transcript.messages).at(-1)!;
    expect(snapshot.compacted).toBe(true);
    expect(snapshot.roundUsages).toEqual(rounds(1));
  });

  it("preserves legacy compaction invalidation and historical rounds without request events", () => {
    const transcript = new ThreadTranscript();
    project(transcript, { ...envelope, event: "delta", text: "answer", turn_seq: 1 });
    project(transcript, { ...envelope, event: "turn_end", usage: usage(1), round_usages: rounds(1), turn_seq: 2 });
    project(transcript, { ...envelope, turn_id: "compact-turn", event: "context_compaction", compaction_id: "compact", phase: "succeeded", turn_seq: 1 });
    const snapshots = composerUsageSnapshots(transcript.messages);
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
    expect(composerUsageSnapshots(restored.messages).at(-1)?.usage).toEqual(usage(3));
    expect(projectWebuiThreadMessages(restored.messages)).toEqual([]);
  });

  it("reconciles reconnect history without replacing newer live usage", () => {
    const transcript = new ThreadTranscript();
    const initial = request(1, { phase: "completed", usage: usage(1), round_usages: rounds(1) });
    project(transcript, initial);
    const read = transcript.begin("latest");
    project(transcript, request(2, { phase: "completed", usage: usage(2), round_usages: rounds(2) }));
    expect(transcript.accept({ schemaVersion: 3, projection: "events", events: [initial] }, read)).toBe(true);
    expect(composerUsageSnapshots(transcript.messages).at(-1)?.usage).toEqual(usage(2));
    const fresh = new ThreadTranscript();
    expect(fresh.accept(parseWebuiThreadPayload({ schemaVersion: 3, projection: "events", events: [initial, request(2)] }), fresh.begin("initial"))).toBe(true);
    expect(composerUsageSnapshots(fresh.messages).at(-1)?.roundUsages).toHaveLength(1);
  });

  it.each([false, true])("does not treat a missing-usage completion as fresh after compaction (replay=%s)", (persisted) => {
    const transcript = new ThreadTranscript();
    project(transcript, request(1, { phase: "completed", usage: usage(1), round_usages: rounds(1) }), persisted);
    project(transcript, { ...envelope, event: "context_compaction", compaction_id: "compact", phase: "succeeded", turn_seq: 2 }, persisted);
    project(transcript, request(3, { usage: usage(1), round_usages: rounds(1) }), persisted);
    project(transcript, request(4, { phase: "completed", usage: usage(1), round_usages: rounds(1) }), persisted);
    expect(composerUsageSnapshots(transcript.messages).at(-1)?.compacted).toBe(true);
    project(transcript, request(5, { phase: "failed", usage: usage(2), round_usages: rounds(2) }), persisted);
    expect(composerUsageSnapshots(transcript.messages).at(-1)?.compacted).toBe(false);
  });

  it("keeps active history snapshots and bounds rounds to the latest eight calls", () => {
    const replay = new ThreadTranscript();
    project(replay, request(1, { phase: "completed", usage: usage(10), round_usages: rounds(10) }), true);
    project(replay, request(2), true);
    const snapshot = composerUsageSnapshots(replay.messages).at(-1)!;
    expect(snapshot.roundUsages).toHaveLength(8);
    expect(snapshot.roundUsages?.[0].prompt_tokens).toBe(102);
  });
});
