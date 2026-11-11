import { beforeEach, describe, expect, it, vi } from "vitest";

import { ThreadTranscript } from "@/lib/thread-transcript";
import * as eventProjection from "@/lib/thread-event-projection";
import type { ThreadProjectionEvent, UIMessage, WebuiThreadPersistedPayload } from "@/lib/types";

const NOW = 1_800_000_000_000;
let nextId = 0;

beforeEach(() => { nextId = 0; });

function at(turn_id: string, turn_seq: number) {
  return { chat_id: "hydration-chat", turn_id, turn_seq };
}

function input(turnId: string, text: string): Extract<ThreadProjectionEvent, { event: "user_message" }> {
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
  it("reuses an unchanged fragment prefix but replaces a revised answer with the same identity", () => {
    const thread = new ThreadTranscript();
    const events: ThreadProjectionEvent[] = [
      input("append", "Question"),
      { ...at("append", 2), event: "stream_end", stream_id: "first", text: "First", text_from_seq: 2 },
      { ...at("append", 3), event: "message", kind: "tool_hint", text: "Tool" },
      { ...at("append", 4), event: "stream_end", stream_id: "second", text: "Second", text_from_seq: 4 },
    ];
    const page = (start: number, end: number, values = events) => history(values.slice(start, end), {
      completed_turn_ids: [], has_pending_tool_calls: true,
      page: { record_range: { turn: 0, start, end }, history_generation: "append-generation",
        truncated_oversized_turn: true, before_cursor: start ? `before-${start}` : null,
        has_more_before: start > 0, user_message_offset: 0 },
    });
    expect(thread.accept(page(0, 3), thread.begin("initial"))).toBe(true);
    const saved = thread.save();
    const project = vi.spyOn(eventProjection, "projectThreadEvent");
    try {
      expect(thread.accept(page(2, 4), thread.begin("latest"))).toBe(true);
      expect(thread.messages.map((row) => row.content)).toEqual(["Question", "First", "Tool", "Second"]);
      expect(project).toHaveBeenCalledTimes(1);
      expect(project.mock.calls[0][1]).toMatchObject({ event: "stream_end", text: "Second" });
      project.mockClear();
      expect(thread.accept(page(2, 4), thread.begin("latest"))).toBe(true);
      expect(project).toHaveBeenCalledTimes(0);
      const revised = events.map((event) => event.event === "stream_end" && event.stream_id === "second"
        ? { ...event, text: "Corrected second" } : event);
      expect(thread.accept(page(2, 4, revised), thread.begin("latest"))).toBe(true);
      expect(thread.messages.map((row) => row.content)).toEqual(["Question", "First", "Tool", "Corrected second"]);
      const restored = new ThreadTranscript([], saved);
      expect(restored.accept(page(2, 4), restored.begin("latest"))).toBe(true);
      expect(restored.messages.map((row) => row.content)).toEqual(["Question", "First", "Tool", "Second"]);
    } finally {
      project.mockRestore();
    }
  });

  it("updates a represented live input's final image URL without duplicating it", () => {
    const thread = new ThreadTranscript();
    const first: ThreadProjectionEvent = { ...at("upload", 1), event: "user_message", text: "look", starts_turn: true,
      media_urls: [{ kind: "image", url: "data:image/png;base64,AAAA", name: "image.png" }] };
    receive(thread, first);
    receive(thread, { ...first, media_urls: [{ kind: "image", url: "/api/media/final", name: "image.png" }] });
    expect(thread.messages).toHaveLength(1);
    expect(thread.messages[0]).toMatchObject({ media: [{ url: "/api/media/final" }], images: [{ url: "/api/media/final" }] });
    const restored = new ThreadTranscript([], thread.save());
    expect(restored.messages[0].media?.[0].url).toBe("/api/media/final");
  });

  it("keeps the history boundary unknown through live delivery and a failed first read", () => {
    const thread = new ThreadTranscript();
    const read = thread.begin("initial");
    receive(thread, { ...at("turn-now", 5), event: "delta", stream_id: "answer-now", text: "Live tail" });
    expect(thread.paging).toMatchObject({ loading: true, hasMoreBefore: null });

    thread.finishRead(read, "History unavailable");
    expect(thread.paging).toMatchObject({ loading: false, error: "History unavailable", hasMoreBefore: null });
    const restored = new ThreadTranscript([], thread.save());
    expect(restored.paging.hasMoreBefore).toBeNull();
    const retry = restored.begin("latest");
    expect(restored.accept(history([
      input("turn-now", "Earlier question"),
      { ...at("turn-now", 6), event: "stream_end", stream_id: "answer-now", text: "Live tail", resuming: true, merge_next: true },
    ]), retry)).toBe(true);
    expect(restored.messages.map((row) => row.content)).toEqual(["Earlier question", "Live tail"]);
    expect(restored.paging).toMatchObject({ loading: false, error: null, hasMoreBefore: false });
  });

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
      text: "Installed ", text_from_seq: 2, resuming: true, merge_next: true,
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
      { ...at("turn-no-id", 3), event: "reasoning_end", text: "First thought", text_from_seq: 2 },
      { ...at("turn-no-id", 4), event: "message", kind: "progress", text: "Read a file" },
      { ...at("turn-no-id", 7), event: "reasoning_end", text: "Second thought", text_from_seq: 6 },
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
      { ...at("turn-cached", 3), event: "reasoning_end", text: "Plan.", text_from_seq: 2 },
      { ...at("turn-cached", 5), event: "stream_end", stream_id: "answer-cached", text: "First", text_from_seq: 4, resuming: true, merge_next: true },
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

  it("refreshes a disjoint latest fragment and pages back across the gap after restoring the cache", () => {
    const events: ThreadProjectionEvent[] = [
      input("growing", "Question"),
      ...["B", "C", "D", "E", "F"].map((text, index) => ({
        ...at("growing", index + 2), event: "message" as const, text,
      })),
    ];
    const fragment = (start: number, end: number) => history(events.slice(start, end), {
      active_turn_id: "growing",
      page: { history_generation: "generation", record_range: { turn: 0, start, end },
        before_cursor: start ? `before-${start}` : null, has_more_before: start > 0, truncated_oversized_turn: true },
    });
    const initial = new ThreadTranscript();
    expect(initial.accept(fragment(1, 3), initial.begin("initial"))).toBe(true);
    const thread = new ThreadTranscript([], initial.save());
    const staleOlder = thread.begin("older");
    // A restored owner issues an initial read even though it has a cached window.
    expect(thread.accept(fragment(4, 6), thread.begin("initial"))).toBe(true);
    expect(thread.messages.map((row) => row.content)).toEqual(["E", "F"]);
    expect(thread.hasPendingFragmentGap).toBe(false);
    expect(thread.paging).toMatchObject({ beforeCursor: "before-4", hasMoreBefore: true });
    expect(thread.accept(fragment(0, 1), staleOlder)).toBe(false);
    expect(thread.paging.beforeCursor).toBe("before-4");

    expect(thread.accept(fragment(2, 4), thread.begin("older"))).toBe(true);
    expect(thread.messages.map((row) => row.content)).toEqual(["B", "C", "D", "E", "F"]);
    expect(thread.paging.beforeCursor).toBe("before-1");
    expect(thread.accept(fragment(0, 1), thread.begin("older"))).toBe(true);
    expect(thread.messages.map((row) => row.content)).toEqual(["Question", "B", "C", "D", "E", "F"]);
    expect(thread.paging.hasMoreBefore).toBe(false);
  });

  it("keeps an unpersisted live contribution visible while paging across a multi-page gap", () => {
    // D was delivered live but never persisted, so record positions and turn_seq differ.
    const events: ThreadProjectionEvent[] = [
      input("gap-live", "Question"),
      ...[[2, "B"], [3, "C"], [5, "E"], [6, "F"], [7, "G"], [8, "H"], [9, "I"]].map(([seq, text]) => ({
        ...at("gap-live", seq as number), event: "delta" as const, stream_id: "wire", text: text as string,
      })),
    ];
    const fragment = (start: number, end: number) => history(events.slice(start, end), {
      active_turn_id: "gap-live",
      page: { history_generation: "generation", record_range: { turn: 0, start, end },
        before_cursor: start ? `before-${start}` : null, has_more_before: start > 0, truncated_oversized_turn: true },
    });
    const thread = new ThreadTranscript();
    expect(thread.accept(fragment(1, 3), thread.begin("initial"))).toBe(true);
    receive(thread, { ...at("gap-live", 4), event: "delta", stream_id: "wire", text: "D" });
    const staleOlder = thread.begin("older");
    const staleLatest = thread.begin("latest");
    expect(thread.accept(fragment(6, 8), thread.begin("latest"))).toBe(true);
    expect(thread.messages.map((row) => row.content)).toEqual(["BCD"]);
    expect(thread.hasPendingFragmentGap).toBe(true);
    expect(thread.paging).toMatchObject({ beforeCursor: "before-6", hasMoreBefore: true, error: null });
    expect(thread.accept(fragment(0, 1), staleOlder)).toBe(false);
    expect(thread.accept(fragment(1, 3), staleLatest)).toBe(false);
    expect(thread.accept(fragment(4, 6), thread.begin("older"))).toBe(true);
    expect(thread.messages.map((row) => row.content)).toEqual(["BCD"]);
    expect(thread.paging.beforeCursor).toBe("before-4");

    const restored = new ThreadTranscript([], thread.save());
    expect(restored.hasPendingFragmentGap).toBe(true);
    expect(restored.accept(fragment(2, 4), restored.begin("older"))).toBe(true);
    expect(restored.hasPendingFragmentGap).toBe(false);
    expect(restored.messages.map((row) => row.content)).toEqual(["BCDEFGHI"]);
    expect(restored.accept(fragment(0, 2), restored.begin("older"))).toBe(true);
    expect(restored.messages.map((row) => row.content)).toEqual(["Question", "BCDEFGHI"]);
    receive(restored, { ...at("gap-live", 10), event: "delta", stream_id: "wire", text: "J" });
    expect(restored.messages.at(-1)?.content).toBe("BCDEFGHIJ");
  });

  it("loads the missing prefix before adopting an unknown-left media-signed snapshot", () => {
    const turn = "gap-snapshot-conflict";
    const chunk = (seq: number, text: string): ThreadProjectionEvent => ({ ...at(turn, seq), event: "delta", text });
    const fragment = (start: number, end: number, events: ThreadProjectionEvent[], completed = false) => history(events, {
      active_turn_id: completed ? null : turn,
      completed_turn_ids: completed ? [turn] : [],
      page: { history_generation: "generation", record_range: { turn: 0, start, end },
        before_cursor: start ? `before-${start}` : null, has_more_before: start > 0, truncated_oversized_turn: true },
    });
    const thread = new ThreadTranscript();
    expect(thread.accept(fragment(1, 3, [chunk(2, "B"), chunk(3, "C")]), thread.begin("initial"))).toBe(true);
    receive(thread, chunk(4, "![image](images/photo.png)"));
    expect(thread.accept(fragment(6, 8, [
      { ...at(turn, 8), event: "stream_end", text: "BC![image](/api/media/signed.png)EFG" },
      { ...at(turn, 9), event: "turn_end" },
    ], true), thread.begin("latest"))).toBe(true);
    receive(thread, chunk(5, "E"));

    expect(thread.accept(fragment(3, 6, [chunk(5, "E"), chunk(6, "F"), chunk(7, "G")]), thread.begin("older"))).toBe(true);
    expect(thread.paging.olderError).toBeNull();
    expect(thread.paging.beforeCursor).toBe("before-1");
    expect(thread.hasPendingFragmentGap).toBe(true);
    expect(thread.messages.map((row) => row.content)).toEqual(["BC![image](images/photo.png)E"]);
    expect(thread.save().live.map(({ event }) => event.turn_seq)).toEqual([4, 5]);
    expect(thread.accept(fragment(0, 1, [input(turn, "Question")]), thread.begin("older"))).toBe(true);
    expect(thread.messages.map((row) => row.content)).toEqual(["Question", "BC![image](/api/media/signed.png)EFG"]);
    expect(thread.hasPendingFragmentGap).toBe(false);
    expect(thread.save().live).toEqual([]);
  });

  it("adopts a completed canonical message only after its missing prefix has loaded", () => {
    const turn = "gap-message-conflict";
    const chunk = (seq: number, text: string): ThreadProjectionEvent => ({ ...at(turn, seq), event: "delta", stream_id: "wire", text });
    const fragment = (start: number, end: number, events: ThreadProjectionEvent[], completed = false) => history(events, {
      active_turn_id: completed ? null : turn,
      completed_turn_ids: completed ? [turn] : [],
      page: { history_generation: "generation", record_range: { turn: 0, start, end },
        before_cursor: start ? `before-${start}` : null, has_more_before: start > 0, truncated_oversized_turn: true },
    });
    const thread = new ThreadTranscript();
    expect(thread.accept(fragment(1, 3, [chunk(2, "B"), chunk(3, "C")]), thread.begin("initial"))).toBe(true);
    receive(thread, chunk(4, "D"));
    expect(thread.accept(fragment(6, 8, [
      { ...at(turn, 8), event: "message", text: "Canonical answer" },
      { ...at(turn, 9), event: "turn_end" },
    ], true), thread.begin("latest"))).toBe(true);
    receive(thread, chunk(5, "E"));

    expect(thread.accept(fragment(3, 6, [chunk(5, "E"), chunk(6, "F"), chunk(7, "G")]), thread.begin("older"))).toBe(true);
    expect(thread.paging.olderError).toBeNull();
    expect(thread.hasPendingFragmentGap).toBe(true);
    expect(thread.messages.map((row) => row.content)).toEqual(["BCDE"]);
    expect(thread.save().live.map(({ event }) => event.turn_seq)).toEqual([4, 5]);
    expect(thread.accept(fragment(0, 1, [input(turn, "Question")]), thread.begin("older"))).toBe(true);
    expect(thread.messages.map((row) => row.content)).toEqual(["Question", "Canonical answer"]);
    expect(thread.hasPendingFragmentGap).toBe(false);
    expect(thread.save().live).toEqual([]);
  });

  it.each(["before", "after"] as const)("keeps live output ordered when a session input arrives %s it", (order) => {
    const thread = new ThreadTranscript();
    const turn = "injected-fragment";
    const prefix: ThreadProjectionEvent[] = [input(turn, "Question"),
      { ...at(turn, 2), event: "message", kind: "progress", text: "Working" }];
    const provenance = { message_id: "injected", session: { id: "handle_0123456789abcdef0123456789abcdef", name: "mira" } };
    const injected: ThreadProjectionEvent = { chat_id: "hydration-chat", event: "user_message", starts_turn: false,
      text: "Please review", provenance: { session_message: provenance }, projection_id: "injected-record" };
    const fragment = (events: ThreadProjectionEvent[], end: number) => history(events, { active_turn_id: turn,
      page: { record_range: { turn: 0, start: 0, end }, truncated_oversized_turn: true } });
    expect(thread.accept(fragment(prefix, 2), thread.begin("initial"))).toBe(true);
    const admit = () => {
      const row: UIMessage = { id: "session-message:injected", role: "user", content: "Please review", createdAt: NOW, sessionMessage: provenance };
      thread.projection = { ...thread.projection, messages: [...thread.messages, row] };
      thread.registerInput(row);
    };
    const output = () => receive(thread,
      { ...at(turn, 3), event: "model_request", request_id: "new-request", run_id: turn, sequence: 2, phase: "started" },
      { ...at(turn, 4), event: "delta", stream_id: "new-wire", text: "Answer" });
    if (order === "before") { admit(); output(); } else { output(); admit(); }
    expect(thread.accept(fragment([...prefix, injected], 3), thread.begin("latest"))).toBe(true);
    const body = thread.messages.filter((message) => message.role === "user" || message.kind !== "trace").map((message) => message.content);
    expect(body).toEqual(order === "before" ? ["Question", "Please review", "Answer"] : ["Question", "Answer", "Please review"]);
    if (order === "before") {
      receive(thread, { ...at(turn, 5), event: "delta", stream_id: "new-wire", text: " continued" });
      expect(thread.messages.at(-1)?.content).toBe("Answer continued");
    }
  });

  it("keeps a late unpersisted tool activity in its completed historical turn", () => {
    const thread = new ThreadTranscript();
    const turn = "late-history-tool";
    const answer: ThreadProjectionEvent = { ...at(turn, 5), event: "stream_end", stream_id: "wire", text: "Answer" };
    expect(thread.accept(history([answer,
      { ...at(turn, 6), event: "turn_end" }], { completed_turn_ids: [turn],
      page: { record_range: { turn: 0, start: 3, end: 5 }, before_cursor: "before", has_more_before: true } }), thread.begin("initial"))).toBe(true);
    receive(thread, { ...at(turn, 4), event: "message", kind: "tool_hint", text: "read_file()" });
    const tool = thread.messages.find((message) => message.kind === "trace")!;
    expect(tool.turnId).toBe(turn);
    expect(thread.messages.indexOf(tool)).toBeLessThan(thread.messages.findIndex((message) => message.content === "Answer"));
    expect(thread.messages.at(-1)?.content).toBe("Answer");
    expect(thread.projection.closedTurnIds.has(turn)).toBe(true);
  });

  it("stores each raw event once when many latest pages slide over each other", () => {
    // Some raw positions have no projected event; equal text is not an identity.
    const records = Array.from({ length: 28 }, (_, position): ThreadProjectionEvent | null =>
      position % 7 === 0 ? null : { chat_id: "hydration-chat", event: "message",
        projection_id: `raw-record-${position}`, text: position % 2 ? "same" : "other" });
    const fragment = (start: number) => history(records.slice(start, start + 5).filter((event): event is ThreadProjectionEvent => !!event), {
      page: { history_generation: "generation", record_range: { turn: 0, start, end: start + 5 },
        before_cursor: `before-${start}`, has_more_before: true, truncated_oversized_turn: true },
    });
    const thread = new ThreadTranscript();
    for (let start = 1; start <= 23; start++) {
      expect(thread.accept(fragment(start), thread.begin(start === 1 ? "initial" : "latest"))).toBe(true);
    }
    const expected = records.slice(1, 28).filter((event): event is ThreadProjectionEvent => !!event);
    expect(thread.messages.map((row) => row.content)).toEqual(expected.map((event) => "text" in event ? event.text : ""));
    const stored = thread.save().fragments.flatMap((page) => page.events.map((event) => event.projection_id));
    expect(stored).toEqual(expected.map((event) => event.projection_id));
    expect(new Set(stored).size).toBe(stored.length);
  });

  it.each([{ position: 1, gap: false }, { position: 2, gap: false }, { position: 2, gap: true }])("withdraws recovered answers from an open fragment (%j)", ({ position, gap }) => {
    const thread = new ThreadTranscript();
    const partial: ThreadProjectionEvent = { ...at("recovery", position + 1), event: "stream_end", stream_id: "old-answer", text: "Partial answer" };
    const reasoning: ThreadProjectionEvent = { ...at("recovery", 4), event: "reasoning_end", text: "Retained reasoning" };
    const tool: ThreadProjectionEvent = { ...at("recovery", 5), event: "message", kind: "tool_hint", text: "read_file()" };
    // Telemetry accounts for the raw positions that have no projected body event.
    const active = history([partial, reasoning, tool], { active_turn_id: "recovery",
      page: { history_generation: "generation", record_range: { turn: 0, start: 1, end: 4001 },
        before_cursor: "before-1", has_more_before: true, truncated_oversized_turn: true } });
    const recovered = history([...(gap ? [] : [reasoning, tool]),
      { chat_id: "hydration-chat", turn_id: "recovery", event: "message", text: "Correct final answer", projection_id: "canonical-recovery" },
      { ...at("recovery", gap ? 12000 : 4002), event: "turn_end" },
    ], { completed_turn_ids: ["recovery"],
      page: { history_generation: "generation", record_range: { turn: 0, start: gap ? 6002 : 2, end: gap ? 10002 : 4002 }, recovered_answers: true,
        before_cursor: gap ? "before-6002" : "before-2", has_more_before: true, truncated_oversized_turn: true } });
    expect(thread.accept(active, thread.begin("initial"))).toBe(true);
    if (gap) receive(thread, { ...at("recovery", 9000), event: "delta", stream_id: "unpersisted", text: "Unconfirmed live tail" });
    let restored = new ThreadTranscript([], thread.save());
    expect(restored.accept(recovered, restored.begin("latest"))).toBe(true);
    if (gap) {
      restored = new ThreadTranscript([], restored.save());
      expect(restored.accept(history([], {
        page: { history_generation: "generation", record_range: { turn: 0, start: 4001, end: 6002 }, before_cursor: "before-4001", has_more_before: true },
      }), restored.begin("older"))).toBe(true);
    }
    const reopened = new ThreadTranscript();
    expect(reopened.accept(recovered, reopened.begin("initial"))).toBe(true);
    const answers = (owner: ThreadTranscript) => owner.messages.filter((row) => row.role === "assistant" && row.kind !== "trace" && row.content).map((row) => row.content);
    const expected = [...(gap ? ["Unconfirmed live tail"] : []), ...answers(reopened)];
    expect(answers(reopened)).toEqual(["Correct final answer"]);
    expect(answers(restored)).toEqual(expected);
    expect(restored.messages.filter((row) => row.reasoning).map((row) => row.reasoning)).toEqual(["Retained reasoning"]);
    expect(restored.messages.filter((row) => row.kind === "trace").map((row) => row.content)).toEqual(["read_file()"]);
    expect(restored.accept(history([input("recovery", "Question")], {
      page: { history_generation: "generation", record_range: { turn: 0, start: 0, end: 2 }, before_cursor: null, has_more_before: false },
    }), restored.begin("older"))).toBe(true);
    expect(answers(restored)).toEqual(expected);
    expect(restored.messages.filter((row) => row.role === "user").map((row) => row.content)).toEqual(["Question"]);
  });

  it("reprojects adjacent pages of one turn without losing a cumulative answer", () => {
    const events: ThreadProjectionEvent[] = [
      input("long-turn", "Question"),
      { ...at("long-turn", 2), event: "reasoning_end", text: "Earlier reasoning" },
      { ...at("long-turn", 3), event: "stream_end", stream_id: "long-answer", text: "First", resuming: true, merge_next: true },
      { ...at("long-turn", 4), event: "message", kind: "progress", text: "tool()" },
      { ...at("long-turn", 5), event: "stream_end", stream_id: "long-answer", text: "First second" },
      { ...at("long-turn", 6), event: "turn_end" },
    ];
    const complete = new ThreadTranscript();
    expect(complete.accept(history(events, { completed_turn_ids: ["long-turn"] }), complete.begin("initial"))).toBe(true);

    const thread = new ThreadTranscript();
    expect(thread.accept(history(events.slice(3), {
      completed_turn_ids: ["long-turn"],
      page: { before_cursor: "inside-turn", has_more_before: true, truncated_oversized_turn: true,
        record_range: { turn: 0, start: 3, end: 6 } },
    }), thread.begin("initial"))).toBe(true);
    expect(thread.accept(history(events.slice(0, 3), {
      page: { before_cursor: null, has_more_before: false, truncated_oversized_turn: true,
        record_range: { turn: 0, start: 0, end: 3 } },
    }), thread.begin("older"))).toBe(true);

    const visible = (value: ThreadTranscript) => value.messages.map((row) => ({
      role: row.role, kind: row.kind, content: row.content, reasoning: row.reasoning, traces: row.traces,
    }));
    expect(visible(thread)).toEqual(visible(complete));
    expect(thread.paging.hasMoreBefore).toBe(false);
  });

  it("keeps tool activity in order when an older fragment meets a live answer", () => {
    const thread = new ThreadTranscript();
    const question = input("long-tool", "Question");
    const a: ThreadProjectionEvent = { ...at("long-tool", 2), event: "delta", stream_id: "wire", text: "A" };
    const b: ThreadProjectionEvent = { ...at("long-tool", 3), event: "delta", stream_id: "wire", text: "B" };
    const tool: ThreadProjectionEvent = { ...at("long-tool", 4), event: "message", kind: "progress", text: "tool()" };
    const c: ThreadProjectionEvent = { ...at("long-tool", 5), event: "delta", stream_id: "wire", text: "C" };
    expect(thread.accept(history([b], { active_turn_id: "long-tool", has_pending_tool_calls: true,
      page: { before_cursor: "inside", has_more_before: true, truncated_oversized_turn: true,
        record_range: { turn: 0, start: 2, end: 3 } } }), thread.begin("initial"))).toBe(true);
    const read = thread.begin("older");
    receive(thread, tool, c);
    expect(thread.accept(history([question, a], {
      page: { before_cursor: null, has_more_before: false, truncated_oversized_turn: true,
        record_range: { turn: 0, start: 0, end: 2 } } }), read)).toBe(true);
    const expected = new ThreadTranscript();
    expect(expected.accept(history([question, a, b, tool, c], { active_turn_id: "long-tool", has_pending_tool_calls: true }),
      expected.begin("initial"))).toBe(true);
    const visible = (value: ThreadTranscript) => value.messages.map((row) => ({
      role: row.role, kind: row.kind, content: row.content, reasoning: row.reasoning, traces: row.traces,
    }));
    expect(visible(thread)).toEqual(visible(expected));
    receive(thread, { ...at("long-tool", 6), event: "delta", stream_id: "wire", text: "D" });
    expect(thread.messages.at(-1)?.content).toBe("CD");
  });

  it("prunes only exactly persisted live records through repeated overlapping latest reads", () => {
    const thread = new ThreadTranscript();
    const delta = (seq: number): ThreadProjectionEvent => ({
      ...at("journal", seq), event: "delta", stream_id: "wire", text: String(seq),
    });
    const fragment = (end: number) => history(Array.from({ length: end - 1 }, (_, index) => delta(index + 2)), {
      active_turn_id: "journal",
      page: { history_generation: "generation", record_range: { turn: 0, start: 1, end },
        before_cursor: "before-1", has_more_before: true, truncated_oversized_turn: true },
    });
    expect(thread.accept(fragment(2), thread.begin("initial"))).toBe(true);
    receive(thread, delta(3));
    for (let seq = 3; seq <= 12; seq++) {
      receive(thread, delta(seq + 1));
      expect(thread.accept(fragment(seq), thread.begin("latest"))).toBe(true);
      expect(thread.save().live.map(({ event }) => event.turn_seq)).toEqual([seq + 1]);
      expect(thread.messages.at(-1)?.content).toBe(Array.from({ length: seq }, (_, index) => String(index + 2)).join(""));
    }
  });

  it("can project and restore temporary live output without retaining a raw journal", () => {
    const thread = new ThreadTranscript([], undefined, { recordLiveContributions: false });
    for (let seq = 1; seq <= 200; seq++) {
      receive(thread, { ...at("temporary", seq), event: "delta", stream_id: "wire", text: "x" });
    }
    expect(thread.messages.at(-1)?.content).toBe("x".repeat(200));
    expect(thread.save().live).toHaveLength(0);
    const restored = new ThreadTranscript([], thread.save(), { recordLiveContributions: false });
    receive(restored, { ...at("temporary", 201), event: "delta", stream_id: "wire", text: "y" });
    expect(restored.messages.at(-1)?.content).toBe(`${"x".repeat(200)}y`);
    expect(restored.save().live).toHaveLength(0);
  });

  it("retires live chunks after ordinary completed turns persist cumulative end snapshots without receipts", () => {
    const thread = new ThreadTranscript();
    const persisted: ThreadProjectionEvent[] = [];
    const completed: string[] = [];
    for (let index = 0; index < 6; index++) {
      const turn = `ordinary-${index}`;
      const stream_id = `ordinary-wire-${index}`;
      const question = input(turn, `Question ${index}`);
      const a: ThreadProjectionEvent = { ...at(turn, 2), event: "delta", stream_id, text: "First " };
      const b: ThreadProjectionEvent = { ...at(turn, 3), event: "delta", stream_id, text: "second" };
      const end: ThreadProjectionEvent = { ...at(turn, 4), event: "stream_end", stream_id };
      const done: ThreadProjectionEvent = { ...at(turn, 5), event: "turn_end" };
      const read = thread.begin(index ? "latest" : "initial");
      receive(thread, question, a, b, end, done);
      persisted.push(question, { ...end, text: "First second" }, done);
      completed.push(turn);
      expect(thread.accept(history(persisted, { completed_turn_ids: [...completed] }), read)).toBe(true);
      expect(thread.save().live).toHaveLength(0);
    }
    expect(thread.messages.filter((row) => row.role === "assistant").map((row) => row.content))
      .toEqual(Array(6).fill("First second"));
  });

  it("retires covered deltas across successive cumulative stream snapshots", () => {
    const thread = new ThreadTranscript();
    const question = input("ordinary-resume", "Question");
    const a: ThreadProjectionEvent = { ...at("ordinary-resume", 2), event: "delta", stream_id: "wire", text: "A" };
    const first: ThreadProjectionEvent = { ...at("ordinary-resume", 3), event: "stream_end", stream_id: "wire",
      text_from_seq: 2, resuming: true, merge_next: true };
    receive(thread, question, a, first);
    expect(thread.accept(history([question, { ...first, text: "A" }]), thread.begin("initial"))).toBe(true);
    expect(thread.save().live).toHaveLength(0);
    const b: ThreadProjectionEvent = { ...at("ordinary-resume", 4), event: "delta", stream_id: "wire", text: "B" };
    const last: ThreadProjectionEvent = { ...at("ordinary-resume", 5), event: "stream_end", stream_id: "wire", text_from_seq: 2 };
    const done: ThreadProjectionEvent = { ...at("ordinary-resume", 6), event: "turn_end" };
    receive(thread, b, last, done);
    expect(thread.accept(history([question, { ...first, text: "A" }, { ...last, text: "AB" }, done], {
      completed_turn_ids: ["ordinary-resume"],
    }), thread.begin("latest"))).toBe(true);
    expect(thread.messages.at(-1)?.content).toBe("AB");
    expect(thread.save().live).toHaveLength(0);
  });

  it("retires completed legacy text without swallowing an intervening tool", () => {
    const thread = new ThreadTranscript();
    const question = input("ordinary-tool", "Question");
    const a: ThreadProjectionEvent = { ...at("ordinary-tool", 2), event: "delta", stream_id: "wire", text: "A" };
    const tool: ThreadProjectionEvent = { ...at("ordinary-tool", 3), event: "message", kind: "progress", text: "tool()" };
    const b: ThreadProjectionEvent = { ...at("ordinary-tool", 4), event: "delta", stream_id: "wire", text: "B" };
    const end: ThreadProjectionEvent = { ...at("ordinary-tool", 5), event: "stream_end", stream_id: "wire" };
    const done: ThreadProjectionEvent = { ...at("ordinary-tool", 6), event: "turn_end" };
    const read = thread.begin("initial");
    receive(thread, question, a, tool, b, end, done);
    expect(thread.accept(history([question, tool, { ...end, text: "AB" }, done], {
      completed_turn_ids: ["ordinary-tool"],
    }), read)).toBe(true);
    expect(thread.messages.map((row) => row.content)).toEqual(["Question", "tool()", "AB"]);
    expect(thread.save().live).toEqual([]);
  });

  it("uses a partial snapshot's coverage without fetching its prefix or comparing signed text", () => {
    const thread = new ThreadTranscript();
    const turn = "explicit-coverage";
    receive(thread,
      input(turn, "Question"),
      { ...at(turn, 2), event: "reasoning_delta", stream_id: "wire", text: "Unpersisted reasoning" },
      { ...at(turn, 3), event: "delta", stream_id: "wire", text: "![image](local.png)" },
      { ...at(turn, 4), event: "message", kind: "progress", text: "Unpersisted tool" },
      { ...at(turn, 5), event: "delta", stream_id: "other", text: "Other stream" },
    );
    const read = thread.begin("initial");
    receive(thread, { ...at(turn, 7), event: "delta", stream_id: "wire", text: " fresh tail" });
    expect(thread.accept(history([
      { ...at(turn, 6), event: "stream_end", stream_id: "wire", text_from_seq: 3,
        text: "![image](/api/media/signed)", resuming: true, merge_next: true },
    ], { active_turn_id: turn, page: { record_range: { turn: 0, start: 5, end: 6 },
      truncated_oversized_turn: true, has_more_before: true, before_cursor: "older" } }), read)).toBe(true);
    expect(thread.messages.filter((row) => row.streamId === "wire").map((row) => row.content))
      .toEqual(["![image](/api/media/signed) fresh tail"]);
    expect(thread.messages.some((row) => row.reasoning === "Unpersisted reasoning")).toBe(true);
    expect(thread.messages.some((row) => row.content === "Unpersisted tool")).toBe(true);
    expect(thread.messages.some((row) => row.content === "Other stream")).toBe(true);
    expect(thread.save().live.map(({ event }) => event.turn_seq)).toEqual([1, 2, 4, 5, 7]);
    expect(thread.hasPendingFragmentGap).toBe(false);
    expect(thread.paging).toMatchObject({ beforeCursor: "older", hasMoreBefore: true });
  });

  it("retires live deltas covered by persisted stream snapshots", () => {
    const thread = new ThreadTranscript();
    const events: ThreadProjectionEvent[] = [input("journal-snapshots", "Question")];
    const fragment = () => history(events, {
      active_turn_id: "journal-snapshots",
      page: { history_generation: "generation", record_range: { turn: 1, start: 0, end: events.length },
        before_cursor: "before-turn", has_more_before: true, truncated_oversized_turn: true },
    });
    expect(thread.accept(fragment(), thread.begin("initial"))).toBe(true);
    for (let index = 0; index < 8; index++) {
      const stream_id = `wire-${index}`;
      const text = `piece-${index}`;
      const delta: ThreadProjectionEvent = { ...at("journal-snapshots", index * 2 + 2), event: "delta", stream_id, text };
      const end: ThreadProjectionEvent = { ...at("journal-snapshots", index * 2 + 3), event: "stream_end", stream_id,
        text_from_seq: delta.turn_seq };
      receive(thread, delta, end);
      events.push({ ...end, text });
      expect(thread.accept(fragment(), thread.begin("latest"))).toBe(true);
      expect(thread.save().live).toHaveLength(0);
    }
    expect(thread.messages.filter((row) => row.role === "assistant").map((row) => row.content))
      .toEqual(Array.from({ length: 8 }, (_, index) => `piece-${index}`));
  });

  it("retains live records covered only by an incomplete cumulative snapshot", () => {
    const thread = new ThreadTranscript();
    const question = input("journal-hole", "Question");
    const c: ThreadProjectionEvent = { ...at("journal-hole", 3), event: "reasoning_delta", text: "C" };
    const end: ThreadProjectionEvent = { ...at("journal-hole", 4), event: "reasoning_end", text: "Earlier C" };
    const e: ThreadProjectionEvent = { ...at("journal-hole", 5), event: "delta", stream_id: "wire", text: "E" };
    const fragment = (events: ThreadProjectionEvent[], endPosition: number) => history(events, {
      active_turn_id: "journal-hole",
      page: { history_generation: "generation", record_range: { turn: 1, start: 0, end: endPosition },
        before_cursor: "before-turn", has_more_before: true, truncated_oversized_turn: true },
    });
    expect(thread.accept(fragment([question], 1), thread.begin("initial"))).toBe(true);
    receive(thread, c, e);
    expect(thread.accept(fragment([question, end], 2), thread.begin("latest"))).toBe(true);
    expect(thread.messages.at(-1)).toMatchObject({ content: "E", reasoning: "C" });
    expect(thread.save().live.map(({ event }) => event.turn_seq)).toEqual([3, 5]);
    const restored = new ThreadTranscript([], thread.save());
    expect(restored.accept(fragment([question, end], 2), restored.begin("latest"))).toBe(true);
    expect(restored.messages.at(-1)).toMatchObject({ content: "E", reasoning: "C" });
    expect(restored.save().live.map(({ event }) => event.turn_seq)).toEqual([3, 5]);
  });

  it("reconciles partially persisted live batches after restoring a fragment cache", () => {
    const thread = new ThreadTranscript();
    const b: ThreadProjectionEvent = { ...at("long-cache", 3), event: "delta", stream_id: "wire", text: "B" };
    const c: ThreadProjectionEvent = { ...at("long-cache", 4), event: "delta", stream_id: "wire", text: "C" };
    const d: ThreadProjectionEvent = { ...at("long-cache", 5), event: "delta", stream_id: "wire", text: "D" };
    const fragment = (events: ThreadProjectionEvent[], start: number, end: number, before: string | null) => history(events, {
      page: { before_cursor: before, has_more_before: before !== null, truncated_oversized_turn: true,
        record_range: { turn: 0, start, end } },
    });
    expect(thread.accept(fragment([b], 2, 3, "inside"), thread.begin("initial"))).toBe(true);
    thread.project({ ...d, text: "CD", projection_receipts: [{ turn_id: "long-cache", ranges: [[4, 5]] }] }, {
      createId: () => "live-batch", now: NOW, startSeq: 4, contributions: [c, d],
    });
    const restored = new ThreadTranscript([], thread.save());
    expect(restored.accept(fragment([b, c], 2, 4, "inside"), restored.begin("latest"))).toBe(true);
    expect(restored.messages.map((row) => row.content)).toEqual(["BCD"]);
    expect(restored.accept(fragment([
      input("long-cache", "Question"),
      { ...at("long-cache", 2), event: "delta", stream_id: "wire", text: "A" },
    ], 0, 2, null), restored.begin("older"))).toBe(true);
    expect(restored.messages.map((row) => row.content)).toEqual(["Question", "ABCD"]);
    receive(restored, { ...at("long-cache", 6), event: "delta", stream_id: "wire", text: "E" });
    expect(restored.messages.at(-1)?.content).toBe("ABCDE");
  });

  it.each(["history", "live-user", "live-session-input"] as const)("does not join fragments from a deleted and recreated session (%s)", (delivery) => {
    const fragment = (generation: string, events: ThreadProjectionEvent[], start: number, end: number, before: string | null) => history(events, {
      page: { history_generation: generation, before_cursor: before, has_more_before: before !== null,
        truncated_oversized_turn: true, record_range: { turn: 0, start, end } },
    });
    const thread = new ThreadTranscript();
    expect(thread.accept(fragment("old", [
      { ...at("same-turn", 3), event: "message", text: "Old tail" },
      { ...at("same-turn", 4), event: "turn_end" },
    ], 2, 4, "old-prefix"), thread.begin("initial"))).toBe(true);
    const question: ThreadProjectionEvent = { ...input("same-turn", "Old question"), input_id: "user:old",
      ...(delivery === "live-session-input" ? { input_id: "session-message:old", provenance: { session_message: {
        message_id: "old", session: { id: "handle_0123456789abcdef0123456789abcdef", name: "mira" },
      } } } : {}) };
    if (delivery !== "history") receive(thread, { ...question, turn_seq: undefined });
    expect(thread.accept(fragment("old", [question,
      { ...at("same-turn", 2), event: "message", text: "Old middle" }], 0, 2, null), thread.begin("older"))).toBe(true);
    expect(thread.accept(fragment("new", [
      { ...at("same-turn", 3), event: "message", text: "New tail" },
      { ...at("same-turn", 4), event: "turn_end" },
    ], 2, 4, "new-prefix"), thread.begin("latest"))).toBe(true);
    expect(thread.messages.map((row) => row.content)).toEqual(["New tail"]);
    expect(thread.accept(fragment("new", [input("same-turn", "New question"),
      { ...at("same-turn", 2), event: "message", text: "New middle" }], 0, 2, null), thread.begin("older"))).toBe(true);
    expect(thread.messages.map((row) => row.content)).toEqual(["New question", "New middle", "New tail"]);
    if (delivery !== "history") {
      receive(thread, { ...question, turn_id: "pending-turn", turn_seq: undefined, input_id: "pending-input", text: "Pending question",
        ...(question.provenance ? { provenance: { session_message: { ...question.provenance.session_message!, message_id: "pending-message" } } } : {}) });
      expect(thread.accept(fragment("third", [input("third-turn", "Replacement")], 0, 1, null), thread.begin("latest"))).toBe(false);
      expect(thread.messages.at(-1)?.content).toBe("Pending question");
    }
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

  it("restores a fragmented turn when the gateway signs a live markdown image", () => {
    const thread = new ThreadTranscript();
    const turn = "signed-image-fragment";
    const question = input(turn, "Question");
    const request: ThreadProjectionEvent = { ...at(turn, 2), event: "model_request", request_id: "request",
      run_id: "run", sequence: 1, phase: "started", projection_id: "request" };
    const answer: ThreadProjectionEvent = { ...at(turn, 4), event: "stream_end", stream_id: "wire",
      text: "![image](/api/media/signed.png)", projection_id: "answer" };
    const done: ThreadProjectionEvent = { ...at(turn, 5), event: "turn_end", projection_id: "done" };
    const fragment = (events: ThreadProjectionEvent[], start: number, end: number, before: string | null) => history(events, {
      completed_turn_ids: end === 4 ? [turn] : [],
      page: { history_generation: "generation", record_range: { turn: 0, start, end },
        before_cursor: before, has_more_before: before !== null, truncated_oversized_turn: true },
    });
    expect(thread.accept(fragment([request], 1, 2, "inside"), thread.begin("initial"))).toBe(true);
    receive(thread, { ...at(turn, 3), event: "delta", stream_id: "wire", text: "![image](images/photo.png)" });
    expect(thread.accept(fragment([request, answer, done], 1, 4, "inside"), thread.begin("latest"))).toBe(true);
    expect(thread.accept(fragment([question], 0, 1, null), thread.begin("older"))).toBe(true);
    expect(thread.messages.map((row) => row.content)).toEqual(["Question", "![image](/api/media/signed.png)"]);
    expect(thread.paging.hasMoreBefore).toBe(false);
  });

  it("uses the signed canonical image and does not duplicate a delayed live suffix", () => {
    const thread = new ThreadTranscript();
    const read = thread.begin("initial");
    const question = input("turn-completed-conflict", "Question");
    const live: ThreadProjectionEvent = { ...at("turn-completed-conflict", 2), event: "delta", stream_id: "wire",
      text: "![image](images/photo.png)" };
    receive(thread, question, live);
    // The completed HTTP read can precede the final live chunk. The gateway
    // signs the image path for display.
    const complete = history([
      question,
      { ...at("turn-completed-conflict", 4), event: "stream_end", stream_id: "wire",
        text: "![image](/api/media/signed.png) tail" },
      { ...at("turn-completed-conflict", 5), event: "turn_end" },
    ], { completed_turn_ids: ["turn-completed-conflict"] });
    expect(thread.accept(complete, read)).toBe(true);
    expect(thread.messages.map((row) => row.content)).toEqual(["Question", "![image](/api/media/signed.png) tail"]);

    const restored = new ThreadTranscript([], thread.save());
    receive(restored, { ...at("turn-completed-conflict", 3), event: "delta", stream_id: "wire", text: " tail" });
    expect(restored.messages.map((row) => row.content)).toEqual(["Question", "![image](/api/media/signed.png) tail"]);
    expect(restored.accept(complete, restored.begin("latest"))).toBe(true);
    expect(restored.messages.map((row) => row.content)).toEqual(["Question", "![image](/api/media/signed.png) tail"]);
  });

  it("does not duplicate a delayed local image chunk after the signed snapshot is installed", () => {
    const thread = new ThreadTranscript();
    const question = input("turn-prefix-conflict", "Question");
    const first: ThreadProjectionEvent = { ...at("turn-prefix-conflict", 2), event: "delta", stream_id: "wire", text: "See " };
    const complete = history([
      question,
      { ...at("turn-prefix-conflict", 4), event: "stream_end", stream_id: "wire",
        text: "See ![image](/api/media/signed.png)" },
      { ...at("turn-prefix-conflict", 5), event: "turn_end" },
    ], { completed_turn_ids: ["turn-prefix-conflict"] });
    const read = thread.begin("initial");
    receive(thread, question, first);
    expect(thread.accept(complete, read)).toBe(true);

    const restored = new ThreadTranscript([], thread.save());
    receive(restored, { ...at("turn-prefix-conflict", 3), event: "delta", stream_id: "wire",
      text: "![image](images/photo.png)" });
    expect(restored.messages.map((row) => row.content)).toEqual(["Question", "See ![image](/api/media/signed.png)"]);
    expect(restored.accept(complete, restored.begin("latest"))).toBe(true);
    expect(restored.messages.map((row) => row.content)).toEqual(["Question", "See ![image](/api/media/signed.png)"]);
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
