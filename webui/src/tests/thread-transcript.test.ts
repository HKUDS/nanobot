import { beforeEach, describe, expect, it } from "vitest";

import { ThreadTranscript } from "@/lib/thread-transcript";
import type { ThreadProjectionEvent, WebuiThreadPersistedPayload } from "@/lib/types";

const NOW = 1_800_000_000_000;
let nextId = 0;

beforeEach(() => { nextId = 0; });

function at(turn_id: string, turn_seq: number) {
  return { chat_id: "hydration-chat", turn_id, turn_seq };
}

function input(turnId: string, text: string): ThreadProjectionEvent {
  return { ...at(turnId, 1), event: "user_message", text, starts_turn: true };
}

function history(
  events: ThreadProjectionEvent[],
  options: Partial<Omit<WebuiThreadPersistedPayload, "schemaVersion" | "projection" | "events">> = {},
): WebuiThreadPersistedPayload {
  return {
    schemaVersion: 3,
    projection: "events",
    events: events.map((event, index) => ({
      ...event,
      projection_id: event.projection_id
        ?? `canonical:${event.turn_id}:${"turn_seq" in event ? event.turn_seq : index}`,
    })),
    page: { before_cursor: null, has_more_before: false, user_message_offset: 0 },
    ...options,
  };
}

function receive(thread: ThreadTranscript, ...events: ThreadProjectionEvent[]): void {
  for (const event of events) thread.project(event, {
    createId: () => `received-${++nextId}`,
    now: NOW,
  });
}

describe("ThreadTranscript admission", () => {
  it.each(["succeeded", "failed", "cancelled"] as const)("reconciles one idle compaction across live phases and history (%s)", (phase) => {
    const thread = new ThreadTranscript();
    const base = [
      input("turn-before-idle", "Question"),
      { ...at("turn-before-idle", 2), event: "stream_end" as const, stream_id: "answer-before-idle", text: "Answer" },
      { ...at("turn-before-idle", 3), event: "turn_end" as const },
    ];
    const completed = { completed_turn_ids: ["turn-before-idle"] };
    expect(thread.accept(history(base, completed), thread.begin("initial"))).toBe(true);
    const compaction = { event: "context_compaction" as const, chat_id: "hydration-chat", compaction_id: "idle-one" };
    receive(thread, { ...compaction, phase: "started" });
    const staleRead = thread.begin("latest");
    receive(thread, { ...compaction, phase });
    expect(thread.accept(history(base, completed), staleRead)).toBe(true);
    expect(thread.messages.map((row) => row.id).filter((id) => id === "compaction-idle-one")).toHaveLength(1);
    expect(thread.messages.at(-1)?.compaction?.phase).toBe(phase);

    const body = history([...base, { ...compaction, phase }], completed);
    expect(thread.accept(body, thread.begin("latest"))).toBe(true);
    expect(thread.messages.map((row) => row.content)).toEqual(["Question", "Answer", ""]);
    expect(thread.messages[2]).toMatchObject({ id: "compaction-idle-one", compaction: { phase } });
    const owners = thread.save().units.filter((unit) => unit.rows.has("compaction-idle-one"));
    expect(owners).toHaveLength(1);
    expect(thread.accept(body, thread.begin("latest"))).toBe(true);
    const restored = new ThreadTranscript([], thread.save());
    receive(restored, { ...compaction, phase });
    expect(restored.accept(body, restored.begin("latest"))).toBe(true);
    expect(restored.messages.map((row) => row.id).filter((id) => id === "compaction-idle-one")).toHaveLength(1);
  });

  it("keeps distinct native and idle compactions when history refreshes a live idle notice", () => {
    const thread = new ThreadTranscript();
    const native: ThreadProjectionEvent = { ...at("turn-native", 2), event: "context_compaction", compaction_id: "native", phase: "succeeded" };
    const base: ThreadProjectionEvent[] = [
      input("turn-native", "Question"), native,
      { ...at("turn-native", 3), event: "stream_end", stream_id: "answer-native", text: "Answer" },
      { ...at("turn-native", 4), event: "turn_end" },
    ];
    const completed = { completed_turn_ids: ["turn-native"] };
    expect(thread.accept(history(base, completed), thread.begin("initial"))).toBe(true);
    const idle: ThreadProjectionEvent = { event: "context_compaction", chat_id: "hydration-chat", compaction_id: "idle", phase: "succeeded" };
    receive(thread, idle);
    expect(thread.accept(history([...base, idle], completed), thread.begin("latest"))).toBe(true);
    expect(thread.messages.map((row) => row.compaction?.id ?? row.content)).toEqual(["Question", "native", "Answer", "idle"]);
  });

  it("installs an older safe prefix without replacing or redirecting the received foreground", () => {
    const thread = new ThreadTranscript();
    const read = thread.begin("initial");
    receive(thread,
      input("turn-now", "Current question"),
      { ...at("turn-now", 2), event: "delta", stream_id: "answer-now", text: "Live " },
    );
    const foregroundId = thread.messages.at(-1)?.id;

    expect(thread.accept(history([
      input("turn-before", "Earlier question"),
      { ...at("turn-before", 2), event: "message", text: "Earlier answer" },
      { ...at("turn-before", 3), event: "turn_end" },
      input("turn-now", "Current question"),
    ], { page: { before_cursor: "before-earlier", has_more_before: true, user_message_offset: 7 } }), read)).toBe(true);

    expect(thread.messages.map((row) => row.content)).toEqual([
      "Earlier question", "Earlier answer", "Current question", "Live ",
    ]);
    expect(thread.paging).toMatchObject({ beforeCursor: "before-earlier", hasMoreBefore: true, userMessageOffset: 7 });
    receive(thread, { ...at("turn-now", 3), event: "delta", stream_id: "answer-now", text: "continues" });
    expect(thread.messages.at(-1)).toMatchObject({ id: foregroundId, content: "Live continues" });
  });

  it("admits independent same-text segments in the active turn using their distinct source identities", () => {
    const thread = new ThreadTranscript();
    const read = thread.begin("initial");
    // Attach during C; A and B ended before this WebSocket attachment.
    receive(thread,
      input("turn-active", "Continue"),
      { ...at("turn-active", 6), event: "delta", stream_id: "wire-C", text: "Current" },
      { ...at("turn-active", 7), event: "stream_end", stream_id: "wire-C", text: "Current", resuming: true, merge_next: true },
      { ...at("turn-active", 8), event: "delta", stream_id: "wire-C", text: " tail" },
    );
    const foregroundId = thread.messages.at(-1)?.id;

    expect(thread.accept(history([
      input("turn-active", "Continue"),
      { ...at("turn-active", 3), event: "stream_end", stream_id: "wire-A", text: "same" },
      { ...at("turn-active", 5), event: "stream_end", stream_id: "wire-B", text: "same" },
      { ...at("turn-active", 7), event: "stream_end", stream_id: "wire-C", text: "Current", resuming: true, merge_next: true },
    ]), read)).toBe(true);

    const answers = thread.messages.filter((row) => row.role === "assistant");
    expect(answers.map((row) => row.content)).toEqual(["same", "same", "Current tail"]);
    expect(answers[0].id).not.toBe(answers[1].id);
    expect(answers[2].id).toBe(foregroundId);
    receive(thread, { ...at("turn-active", 9), event: "delta", stream_id: "wire-C", text: " next" });
    expect(thread.messages.at(-1)).toMatchObject({ id: foregroundId, content: "Current tail next" });
  });

  it("holds every live slice of one cumulative wire and does not move its hosted tool before the first slice", () => {
    const thread = new ThreadTranscript();
    const read = thread.begin("initial");
    receive(thread,
      input("turn-hosted", "Inspect"),
      { ...at("turn-hosted", 4), event: "delta", stream_id: "wire-hosted", text: "L1 " },
      { ...at("turn-hosted", 5), event: "message", kind: "progress", text: "Hosted search" },
      { ...at("turn-hosted", 6), event: "delta", stream_id: "wire-hosted", text: "L2" },
    );
    const leftId = thread.messages[1].id;
    const rightId = thread.messages[3].id;
    const aggregate: ThreadProjectionEvent = {
      ...at("turn-hosted", 7), event: "stream_end", stream_id: "wire-hosted",
      text: "L1 L2", resuming: true, merge_next: true,
    };

    // HTTP has compacted S's deltas into its later cumulative end, after the tool.
    expect(thread.accept(history([
      input("turn-hosted", "Inspect"),
      { ...at("turn-hosted", 3), event: "stream_end", stream_id: "wire-earlier", text: "Earlier independent segment" },
      { ...at("turn-hosted", 5), event: "message", kind: "progress", text: "Hosted search" },
      aggregate,
    ]), read)).toBe(true);

    expect(thread.messages.map((row) => row.content)).toEqual([
      "Inspect", "Earlier independent segment", "L1 ", "Hosted search", "L2",
    ]);
    expect(thread.messages[2].id).toBe(leftId);
    expect(thread.messages[4].id).toBe(rightId);
    // A held aggregate grants no text certificate: the real end must still project.
    receive(thread, aggregate,
      { ...at("turn-hosted", 8), event: "delta", stream_id: "wire-hosted", text: " continued" },
    );
    expect(thread.messages.at(-1)).toMatchObject({ id: rightId, content: "L1 L2 continued" });
    expect(thread.messages[2]).toMatchObject({ id: leftId, content: "L1 " });
    expect(thread.messages[3].content).toBe("Hosted search");
  });

  it("holds a mixed reasoning-and-answer row as a whole while its answer has a newer continuation", () => {
    const thread = new ThreadTranscript();
    const read = thread.begin("initial");
    receive(thread,
      input("turn-mixed", "Explain"),
      { ...at("turn-mixed", 2), event: "reasoning_delta", stream_id: "reasoning-mixed", text: "Think." },
      { ...at("turn-mixed", 3), event: "reasoning_end", stream_id: "reasoning-mixed" },
      { ...at("turn-mixed", 4), event: "delta", stream_id: "answer-mixed", text: "Draft" },
      { ...at("turn-mixed", 5), event: "stream_end", stream_id: "answer-mixed", text: "Draft", resuming: true, merge_next: true },
      { ...at("turn-mixed", 6), event: "delta", stream_id: "answer-mixed", text: " live" },
    );
    const sharedId = thread.messages[1].id;

    expect(thread.accept(history([
      input("turn-mixed", "Explain"),
      { ...at("turn-mixed", 3), event: "reasoning_end", stream_id: "reasoning-mixed", text: "Think." },
      { ...at("turn-mixed", 5), event: "stream_end", stream_id: "answer-mixed", text: "Draft", resuming: true, merge_next: true },
    ]), read)).toBe(true);

    expect(thread.messages.filter((row) => row.role === "assistant")).toMatchObject([
      { id: sharedId, reasoning: "Think.", content: "Draft live" },
    ]);
    receive(thread, { ...at("turn-mixed", 7), event: "delta", stream_id: "answer-mixed", text: " more" });
    expect(thread.messages.at(-1)).toMatchObject({ id: sharedId, reasoning: "Think.", content: "Draft live more" });
  });

  it("suppresses history-covered late text but continues the installed cursor and respects its next real end", () => {
    const thread = new ThreadTranscript();
    const installed: ThreadProjectionEvent = {
      ...at("turn-history-first", 4), event: "stream_end", stream_id: "answer-first",
      text: "Installed ", resuming: true, merge_next: true,
    };
    expect(thread.accept(history([input("turn-history-first", "Continue"), installed]), thread.begin("initial"))).toBe(true);
    const answerId = thread.messages[1].id;

    receive(thread,
      { ...at("turn-history-first", 2), event: "delta", stream_id: "answer-first", text: "Installed " },
      installed,
      { ...at("turn-history-first", 5), event: "delta", stream_id: "answer-first", text: "continuation" },
    );
    expect(thread.messages).toHaveLength(2);
    expect(thread.messages[1]).toMatchObject({ id: answerId, content: "Installed continuation" });

    receive(thread,
      { ...at("turn-history-first", 6), event: "stream_end", stream_id: "answer-first", text: "Installed continuation" },
      { ...at("turn-history-first", 7), event: "delta", stream_id: "answer-next", text: "Next segment" },
    );
    expect(thread.messages.filter((row) => row.role === "assistant").map((row) => row.content))
      .toEqual(["Installed continuation", "Next segment"]);
    expect(thread.messages[2].id).not.toBe(answerId);
  });

  it.each([false, true])("retains a closed wire through a truncated page and historical delivery (visible slice: %s)", (visibleSlice) => {
    const thread = new ThreadTranscript();
    // A capped active-turn window can start after an earlier chunk. A textless
    // end is a wire fence even when this window has no body for that wire.
    expect(thread.accept(history([
      ...(visibleSlice ? [{ ...at("turn-capped", 3), event: "delta" as const, stream_id: "closed-wire", text: "Retained slice" }] : []),
      { ...at("turn-capped", 4), event: "stream_end", stream_id: "closed-wire", resuming: true },
      { ...at("turn-capped", 7), event: "stream_end", stream_id: "current-wire", text: "Current", resuming: true, merge_next: true },
    ], { page: { before_cursor: "earlier", has_more_before: true, user_message_offset: 0,
      truncated_oversized_turn: true } }), thread.begin("initial"))).toBe(true);
    const restored = new ThreadTranscript([], thread.save());
    const contents = restored.messages.map((row) => row.content);
    receive(restored, { ...at("turn-capped", 2), event: "delta", stream_id: "closed-wire", text: "Late older chunk" });
    expect(restored.messages.map((row) => row.content)).toEqual(contents);
    receive(restored, { ...at("turn-capped", 8), event: "delta", stream_id: "current-wire", text: " continues" });
    expect(restored.messages.at(-1)?.content).toBe("Current continues");
  });

  it("keeps missing-ID reasoning segments separate at their actual ends and does not swallow a fresh segment", () => {
    const thread = new ThreadTranscript();
    expect(thread.accept(history([
      input("turn-no-id", "Think in stages"),
      { ...at("turn-no-id", 3), event: "reasoning_end", text: "First thought" },
      { ...at("turn-no-id", 4), event: "message", kind: "progress", text: "Read a file" },
      { ...at("turn-no-id", 7), event: "reasoning_end", text: "Second thought" },
    ]), thread.begin("initial"))).toBe(true);

    receive(thread,
      { ...at("turn-no-id", 2), event: "reasoning_delta", text: "First thought" },
      { ...at("turn-no-id", 6), event: "reasoning_delta", text: "Second thought" },
      { ...at("turn-no-id", 3), event: "reasoning_end", text: "First thought" },
      { ...at("turn-no-id", 8), event: "reasoning_delta", text: "Third thought" },
      { ...at("turn-no-id", 9), event: "reasoning_end" },
      { ...at("turn-no-id", 10), event: "delta", stream_id: "answer-after-thoughts", text: "Fresh answer" },
    );

    expect(thread.messages.filter((row) => row.reasoning).map((row) => row.reasoning))
      .toEqual(["First thought", "Second thought", "Third thought"]);
    expect(thread.messages).toHaveLength(5);
    expect(thread.messages.at(-1)).toMatchObject({ reasoning: "Third thought", content: "Fresh answer" });
  });

  it("admits earlier missing-ID reasoning segments before an already received later segment", () => {
    const thread = new ThreadTranscript();
    const read = thread.begin("initial");
    // Attach after the first reasoning end; the received delta belongs to the second buffer.
    receive(thread,
      input("turn-reasoning-attach", "Think in stages"),
      { ...at("turn-reasoning-attach", 6), event: "reasoning_delta", text: "Second live" },
    );
    const foregroundId = thread.messages.at(-1)?.id;

    expect(thread.accept(history([
      input("turn-reasoning-attach", "Think in stages"),
      { ...at("turn-reasoning-attach", 3), event: "reasoning_end", text: "First thought" },
      { ...at("turn-reasoning-attach", 4), event: "message", kind: "progress", text: "Read a file" },
      { ...at("turn-reasoning-attach", 7), event: "reasoning_end", text: "Second snapshot" },
    ]), read)).toBe(true);

    expect(thread.messages.map((row) => row.reasoning || row.content)).toEqual([
      "Think in stages", "First thought", "Read a file", "Second live",
    ]);
    receive(thread, { ...at("turn-reasoning-attach", 8), event: "reasoning_delta", text: " continues" });
    expect(thread.messages.at(-1)).toMatchObject({ id: foregroundId, reasoning: "Second live continues" });
  });

  it("honors exact summary receipts while inserting a late hole without closing the foreground answer", () => {
    const thread = new ThreadTranscript();
    const detail = { ref: "2.history-summary", bytes: 40_000, traceCount: 3 };
    expect(thread.accept(history([
      input("turn-unrelated", "Earlier question"),
      { ...at("turn-unrelated", 2), event: "message", text: "Earlier answer" },
      { ...at("turn-unrelated", 3), event: "turn_end" },
      input("turn-summary", "Run tools"),
      {
        ...at("turn-summary", 3), event: "message", kind: "progress", text: "Tools summary",
        trace_detail: detail,
        projection_receipts: [{ turn_id: "turn-summary", ranges: [[3, 4], [8, 8]] }],
      },
      { ...at("turn-summary", 10), event: "stream_end", stream_id: "answer-summary", text: "Foreground ", resuming: true, merge_next: true },
    ]), thread.begin("initial"))).toBe(true);
    const foregroundId = thread.messages.at(-1)?.id;

    receive(thread,
      { ...at("turn-summary", 4), event: "message", kind: "progress", text: "Already summarized member 4" },
      { ...at("turn-summary", 8), event: "message", kind: "progress", text: "Already summarized member 8" },
      { ...at("turn-summary", 11), event: "delta", stream_id: "answer-summary", text: "live" },
      { ...at("turn-summary", 6), event: "message", kind: "progress", text: "Delayed independent tool" },
      { ...at("turn-summary", 12), event: "delta", stream_id: "answer-summary", text: " continues" },
    );

    expect(thread.messages.map((row) => row.content)).toEqual([
      "Earlier question", "Earlier answer", "Run tools", "Tools summary", "Delayed independent tool", "Foreground live continues",
    ]);
    expect(thread.messages[3].traceDetail).toEqual(detail);
    expect(thread.messages.at(-1)).toMatchObject({ id: foregroundId, isStreaming: true });
  });

  it("does not install a later turn's completion receipt behind a held canonical source", () => {
    const thread = new ThreadTranscript();
    const read = thread.begin("initial");
    receive(thread,
      input("turn-held", "Current question"),
      { ...at("turn-held", 2), event: "delta", stream_id: "answer-held", text: "Current live" },
    );
    expect(thread.accept(history([
      input("turn-held", "Current question"),
      { ...at("turn-held", 3), event: "stream_end", stream_id: "answer-held", text: "Current snapshot", resuming: true, merge_next: true },
      input("turn-later", "Later question"),
      { ...at("turn-later", 2), event: "message", text: "Later canonical answer" },
      { ...at("turn-later", 3), event: "turn_end", latency_ms: 250 },
    ]), read)).toBe(true);
    expect(thread.messages.map((row) => row.content)).toEqual(["Current question", "Current live"]);

    receive(thread,
      input("turn-later", "Later question"),
      { ...at("turn-later", 2), event: "delta", stream_id: "answer-later", text: "Later received answer" },
      { ...at("turn-later", 3), event: "turn_end", latency_ms: 250 },
    );
    expect(thread.messages.at(-1)).toMatchObject({ content: "Later received answer", isStreaming: false, latencyMs: 250 });
  });

  it("advances the accepted cursor and user offset across an older hidden-only page", () => {
    const thread = new ThreadTranscript();
    expect(thread.accept(history([
      input("turn-visible", "Visible question"),
      { ...at("turn-visible", 3), event: "stream_end", stream_id: "answer-visible", text: "Visible answer" },
      { ...at("turn-visible", 4), event: "turn_end" },
    ], { page: { before_cursor: "before-visible", has_more_before: true, user_message_offset: 6 } }), thread.begin("initial"))).toBe(true);
    const visible = thread.messages;
    const version = thread.paging.version;

    expect(thread.accept(history([], {
      page: { before_cursor: "before-hidden", has_more_before: true, user_message_offset: 4, loaded_event_count: 20 },
    }), thread.begin("older"))).toBe(true);

    expect(thread.messages).toEqual(visible);
    expect(thread.paging).toMatchObject({
      beforeCursor: "before-hidden", hasMoreBefore: true, userMessageOffset: 4,
      loadingOlder: false, olderError: null,
    });
    expect(thread.paging.version).toBe(version);
  });

  it("restores a cached full cursor and coverage before reasoning and answer continuation", () => {
    const original = new ThreadTranscript();
    expect(original.accept(history([
      input("turn-cached", "Continue after returning"),
      { ...at("turn-cached", 3), event: "reasoning_end", text: "Plan." },
      { ...at("turn-cached", 5), event: "stream_end", stream_id: "answer-cached", text: "First", resuming: true, merge_next: true },
    ]), original.begin("initial"))).toBe(true);
    const sharedId = original.messages[1].id;
    expect(original.accept(history([
      input("turn-cached-older", "Earlier cached question"),
      { ...at("turn-cached-older", 2), event: "message", text: "Earlier cached answer" },
      { ...at("turn-cached-older", 3), event: "turn_end" },
    ], { page: { before_cursor: "before-cached-older", has_more_before: true, user_message_offset: 3 } }), original.begin("older"))).toBe(true);
    const saved = original.save();
    receive(original, input("turn-other", "Another visit"));
    const restored = new ThreadTranscript([], saved);

    receive(restored,
      { ...at("turn-cached", 4), event: "delta", stream_id: "answer-cached", text: "First" },
      { ...at("turn-cached", 6), event: "reasoning_delta", text: "Continue." },
      { ...at("turn-cached", 7), event: "reasoning_end" },
      { ...at("turn-cached", 8), event: "delta", stream_id: "answer-cached", text: " second" },
    );

    expect(restored.messages).toHaveLength(4);
    expect(restored.messages.slice(0, 2).map((row) => row.content)).toEqual(["Earlier cached question", "Earlier cached answer"]);
    expect(restored.paging).toMatchObject({ beforeCursor: "before-cached-older", hasMoreBefore: true, userMessageOffset: 3 });
    expect(restored.messages.at(-1)).toMatchObject({
      id: sharedId, content: "First second", reasoning: "Plan.\n\nContinue.",
    });
    expect(restored.messages.some((row) => row.turnId === "turn-other")).toBe(false);
  });

  it("preserves the loaded older prefix and its frontier when a latest window overlaps the suffix", () => {
    const thread = new ThreadTranscript();
    const latest = [
      input("turn-second", "Second question"),
      { ...at("turn-second", 2), event: "message", text: "Second answer" },
      { ...at("turn-second", 3), event: "turn_end" },
    ] satisfies ThreadProjectionEvent[];
    expect(thread.accept(history(latest, {
      page: { before_cursor: "before-second", has_more_before: true, user_message_offset: 1 },
    }), thread.begin("initial"))).toBe(true);
    expect(thread.accept(history([
      input("turn-first", "First question"),
      { ...at("turn-first", 2), event: "message", text: "First answer" },
      { ...at("turn-first", 3), event: "turn_end" },
    ], { page: { before_cursor: "before-first", has_more_before: false, user_message_offset: 0 } }), thread.begin("older"))).toBe(true);

    expect(thread.accept(history(latest, {
      page: { before_cursor: "before-second", has_more_before: true, user_message_offset: 1 },
    }), thread.begin("latest"))).toBe(true);

    expect(thread.messages.map((row) => row.content)).toEqual([
      "First question", "First answer", "Second question", "Second answer",
    ]);
    expect(thread.paging).toMatchObject({ beforeCursor: "before-first", hasMoreBefore: false, userMessageOffset: 0 });
  });

  it("rejects an older ticket from before an authorized latest-window reset without moving the frontier", () => {
    const thread = new ThreadTranscript();
    expect(thread.accept(history([
      input("turn-canonical-old", "Old window"),
      { ...at("turn-canonical-old", 2), event: "message", text: "Old answer" },
      { ...at("turn-canonical-old", 3), event: "turn_end" },
    ], { page: { before_cursor: "before-old", has_more_before: true, user_message_offset: 4 } }), thread.begin("initial"))).toBe(true);
    const older = thread.begin("older");
    const refresh = thread.begin("latest");
    expect(thread.accept(history([
      input("turn-canonical-new", "New window"),
      { ...at("turn-canonical-new", 2), event: "message", text: "New answer" },
      { ...at("turn-canonical-new", 3), event: "turn_end" },
    ], { page: { before_cursor: "before-reset", has_more_before: true, user_message_offset: 9 } }), refresh)).toBe(true);
    const accepted = thread.messages;

    expect(thread.accept(history([
      input("turn-too-old", "Stale older question"),
      { ...at("turn-too-old", 2), event: "message", text: "Stale older answer" },
    ], { page: { before_cursor: "before-stale", has_more_before: false, user_message_offset: 0 } }), older)).toBe(false);

    expect(thread.messages).toEqual(accepted);
    expect(thread.paging).toMatchObject({ beforeCursor: "before-reset", hasMoreBefore: true, userMessageOffset: 9 });
  });

  it("reports a stalled older cursor as retryable without installing rows or claiming exhaustion", () => {
    const thread = new ThreadTranscript();
    const events = [
      input("turn-stalled", "Question"),
      { ...at("turn-stalled", 2), event: "message", text: "Answer" },
      { ...at("turn-stalled", 3), event: "turn_end" },
    ] satisfies ThreadProjectionEvent[];
    expect(thread.accept(history(events, {
      page: { before_cursor: "same-cursor", has_more_before: true, user_message_offset: 6 },
    }), thread.begin("initial"))).toBe(true);
    const accepted = thread.messages;

    expect(thread.accept(history(events, {
      page: { before_cursor: "same-cursor", has_more_before: true, user_message_offset: 4 },
    }), thread.begin("older"))).toBe(false);

    expect(thread.messages).toEqual(accepted);
    expect(thread.paging).toMatchObject({
      beforeCursor: "same-cursor", hasMoreBefore: true, userMessageOffset: 6, loadingOlder: false,
    });
    expect(thread.paging.olderError).toEqual(expect.any(String));
    expect(thread.paging.olderError).not.toBe("");
  });

  it("retains a post-request input and its received tail when an older latest snapshot returns", () => {
    const thread = new ThreadTranscript();
    const old = history([
      input("turn-settled", "Settled question"),
      { ...at("turn-settled", 2), event: "message", text: "Settled answer" },
      { ...at("turn-settled", 3), event: "turn_end" },
    ]);
    expect(thread.accept(old, thread.begin("initial"))).toBe(true);
    const refresh = thread.begin("latest");
    receive(thread,
      input("turn-new-input", "New question"),
      { ...at("turn-new-input", 2), event: "delta", stream_id: "answer-new-input", text: "New live" },
    );
    const foregroundId = thread.messages.at(-1)?.id;

    expect(thread.accept(old, refresh)).toBe(true);
    expect(thread.messages.map((row) => row.content)).toEqual([
      "Settled question", "Settled answer", "New question", "New live",
    ]);
    receive(thread, { ...at("turn-new-input", 3), event: "delta", stream_id: "answer-new-input", text: " tail" });
    expect(thread.messages.at(-1)).toMatchObject({ id: foregroundId, content: "New live tail" });
  });

  it("keeps a received answer between its two canonical input anchors when a refresh omits that answer", () => {
    const thread = new ThreadTranscript();
    expect(thread.accept(history([input("turn-fork-first", "First question")]), thread.begin("initial"))).toBe(true);
    receive(thread,
      { ...at("turn-fork-first", 2), event: "message", text: "First live answer" },
      input("turn-fork-second", "Second question"),
    );

    expect(thread.accept(history([
      input("turn-fork-first", "First question"),
      input("turn-fork-second", "Second question"),
    ]), thread.begin("latest"))).toBe(true);
    expect(thread.messages.map((row) => row.content)).toEqual([
      "First question", "First live answer", "Second question",
    ]);
  });

  it("does not treat an unanchored durable reply received after the request as proof of a new append turn", () => {
    const thread = new ThreadTranscript();
    expect(thread.accept(history([
      { chat_id: "hydration-chat", event: "message", projection_id: "old-canonical", text: "Old canonical row" },
    ]), thread.begin("initial"))).toBe(true);
    const refresh = thread.begin("latest");
    receive(thread, { ...at("turn-unanchored-tail", 2), event: "message", text: "Received durable tail" });

    expect(thread.accept(history([
      { chat_id: "hydration-chat", event: "message", projection_id: "disjoint-canonical", text: "Disjoint canonical row" },
    ]), refresh)).toBe(false);
    expect(thread.messages.map((row) => row.content)).toEqual(["Old canonical row", "Received durable tail"]);
  });

  it("retires a disjoint canonical window on refresh while keeping a post-request received tail", () => {
    const thread = new ThreadTranscript();
    expect(thread.accept(history([
      input("turn-retired", "Old cached window"),
      { ...at("turn-retired", 2), event: "stream_end", stream_id: "answer-retired", text: "Old answer" },
      { ...at("turn-retired", 3), event: "turn_end" },
    ], { page: { before_cursor: "before-retired", has_more_before: true, user_message_offset: 4 } }), thread.begin("initial"))).toBe(true);
    const older = thread.begin("older");
    const refresh = thread.begin("latest");
    receive(thread,
      input("turn-post-request", "New input"),
      { ...at("turn-post-request", 2), event: "delta", stream_id: "answer-post-request", text: "Live" },
    );
    const foregroundId = thread.messages.at(-1)?.id;

    expect(thread.accept(history([
      input("turn-revalidated", "New canonical window"),
      { ...at("turn-revalidated", 2), event: "message", text: "Canonical answer" },
      { ...at("turn-revalidated", 3), event: "turn_end" },
    ], { page: { before_cursor: "before-revalidated", has_more_before: true, user_message_offset: 9 } }), refresh)).toBe(true);
    expect(thread.messages.map((row) => row.content)).toEqual([
      "New canonical window", "Canonical answer", "New input", "Live",
    ]);
    expect(thread.paging).toMatchObject({ beforeCursor: "before-revalidated", hasMoreBefore: true, userMessageOffset: 9 });
    receive(thread, { ...at("turn-post-request", 3), event: "delta", stream_id: "answer-post-request", text: " tail" });
    expect(thread.messages.at(-1)).toMatchObject({ id: foregroundId, content: "Live tail" });
    expect(thread.accept(history([], { page: { before_cursor: null, has_more_before: false } }), older)).toBe(false);

    const saved = thread.save();
    expect(Array.from(saved.boundaries.keys())).not.toContain(JSON.stringify(["turn-retired", "answer", "answer-retired"]));
    expect(Array.from(saved.knownTurns).sort()).toEqual(["turn-post-request", "turn-revalidated"]);
    expect(Array.from(saved.installed.keys())).toEqual(["turn-revalidated"]);
    expect(saved.units.every((unit) => !unit.members.has("turn-retired"))).toBe(true);
    const restored = new ThreadTranscript([], saved);
    receive(restored, { ...at("turn-post-request", 4), event: "delta", stream_id: "answer-post-request", text: " restored" });
    expect(restored.messages.at(-1)).toMatchObject({ id: foregroundId, content: "Live tail restored" });
  });

  it("does not authorize a disjoint reset from a continuation of a source already retained before the request", () => {
    const thread = new ThreadTranscript();
    expect(thread.accept(history([
      input("turn-before-request", "Question"),
      { ...at("turn-before-request", 3), event: "stream_end", stream_id: "answer-before-request", text: "Installed", resuming: true, merge_next: true },
    ]), thread.begin("initial"))).toBe(true);
    const foregroundId = thread.messages.at(-1)?.id;
    const refresh = thread.begin("latest");
    receive(thread, { ...at("turn-before-request", 4), event: "delta", stream_id: "answer-before-request", text: " live" });

    expect(thread.accept(history([
      input("turn-disjoint", "Disjoint question"),
      { ...at("turn-disjoint", 2), event: "message", text: "Disjoint answer" },
    ]), refresh)).toBe(false);
    expect(thread.messages.map((row) => row.content)).toEqual(["Question", "Installed live"]);
    receive(thread, { ...at("turn-before-request", 5), event: "delta", stream_id: "answer-before-request", text: " continues" });
    expect(thread.messages.at(-1)).toMatchObject({ id: foregroundId, content: "Installed live continues" });
  });

  it("keeps retired-window metadata out of the resumable cache snapshot", () => {
    const thread = new ThreadTranscript();
    for (let index = 0; index < 4; index++) {
      const turn = `turn-window-${index}`;
      expect(thread.accept(history([
        input(turn, "Question"),
        { ...at(turn, 2), event: "stream_end", stream_id: `answer-${index}`, text: "Answer" },
        { ...at(turn, 3), event: "turn_end" },
      ], { completed_turn_ids: [turn] }), thread.begin(index === 0 ? "initial" : "latest"))).toBe(true);
    }

    expect(thread.messages).toHaveLength(2);
    const saved = thread.save();
    expect(Array.from(saved.projection.closedTurnIds)).toEqual(["turn-window-3"]);
    expect(Array.from(saved.knownTurns)).toEqual(["turn-window-3"]);
    expect(Array.from(saved.installed.keys())).toEqual(["turn-window-3"]);
    expect(saved.units.every((unit) => Array.from(unit.members.keys()).every((turn) => turn === "turn-window-3"))).toBe(true);
  });

  it("does not certify earlier reasoning from a truncated snapshot with an unknown left boundary", () => {
    const thread = new ThreadTranscript();
    expect(thread.accept(history([
      { ...at("turn-unknown-left", 5), event: "reasoning_end", text: "Truncated thought" },
    ], { page: { before_cursor: "before-unknown", has_more_before: true, truncated_oversized_turn: true } }), thread.begin("initial"))).toBe(true);

    receive(thread,
      { ...at("turn-unknown-left", 3), event: "reasoning_delta", text: "Earlier uncovered thought" },
      { ...at("turn-unknown-left", 6), event: "reasoning_delta", text: "Fresh thought" },
      { ...at("turn-unknown-left", 7), event: "reasoning_end" },
      { ...at("turn-unknown-left", 8), event: "delta", stream_id: "answer-unknown-left", text: "Fresh answer" },
    );
    expect(thread.messages.map((row) => row.reasoning)).toEqual([
      "Earlier uncovered thought", "Truncated thought", "Fresh thought",
    ]);
    expect(thread.messages.at(-1)).toMatchObject({ reasoning: "Fresh thought", content: "Fresh answer" });
  });

  it("does not replace a received source merely because a truncated page reports its turn completed", () => {
    const thread = new ThreadTranscript();
    const read = thread.begin("initial");
    receive(thread,
      input("turn-truncated", "Long question"),
      { ...at("turn-truncated", 2), event: "delta", stream_id: "answer-truncated", text: "Received" },
    );
    const receivedId = thread.messages[1].id;

    expect(thread.accept(history([
      input("turn-truncated", "Long question"),
      { ...at("turn-truncated", 4), event: "stream_end", stream_id: "answer-truncated", text: "Received full answer" },
      { ...at("turn-truncated", 5), event: "turn_end" },
    ], {
      completed_turn_ids: ["turn-truncated"],
      page: { before_cursor: "before-oversized", has_more_before: true, truncated_oversized_turn: true },
    }), read)).toBe(true);

    expect(thread.messages.filter((row) => row.role === "assistant")).toMatchObject([
      { id: receivedId, content: "Received" },
    ]);
    expect(thread.paging.truncated).toBe(true);
  });

  it("can replace a fully represented received turn with a nontruncated explicit canonical completion", () => {
    const thread = new ThreadTranscript();
    const read = thread.begin("initial");
    receive(thread,
      input("turn-complete", "Question"),
      { ...at("turn-complete", 2), event: "delta", stream_id: "answer-complete", text: "Received" },
    );
    const receivedId = thread.messages[1].id;

    expect(thread.accept(history([
      input("turn-complete", "Question"),
      { ...at("turn-complete", 4), event: "stream_end", stream_id: "answer-complete", text: "Received full answer" },
      { ...at("turn-complete", 5), event: "turn_end" },
    ], { completed_turn_ids: ["turn-complete"] }), read)).toBe(true);

    expect(thread.messages.filter((row) => row.role === "assistant")).toMatchObject([
      { content: "Received full answer", isStreaming: false },
    ]);
    expect(thread.messages[1].id).not.toBe(receivedId);
  });
});
