import { describe, expect, it } from "vitest";

import { copyThreadCheckpoint } from "@/lib/thread-checkpoint";
import {
  createThreadProjectionState,
  projectThreadEvent,
  type ThreadProjectionEffects,
  type ThreadProjectionOptions,
} from "@/lib/thread-event-projection";
import type { ThreadProjectionEvent, UIFileEdit } from "@/lib/types";

function createProjector(state = createThreadProjectionState()) {
  let nextId = 0;
  return (
    event: ThreadProjectionEvent,
    options: Pick<ThreadProjectionOptions, "sideChannel" | "persisted" | "startSeq"> = {},
  ) => {
    const effects: ThreadProjectionEffects = {
      bodyWrites: new Set(),
      consumed: new Set(),
    };
    state = projectThreadEvent(state, event, {
      createId: () => `row-${++nextId}`,
      now: 1_800_000_000_000,
      ...options,
      effects,
    });
    return { state, effects };
  };
}

const turn = { chat_id: "chat", turn_id: "turn" };

function fileEdit(overrides: Partial<UIFileEdit> = {}): UIFileEdit {
  return {
    call_id: "write-1",
    tool: "write_file",
    path: "notes.md",
    added: 1,
    deleted: 0,
    status: "editing",
    phase: "start",
    ...overrides,
  };
}

describe("thread projection content effects", () => {
  it("reports reasoning and answer contributions to their shared body row", () => {
    const project = createProjector();
    const reasoning = project({
      ...turn, event: "reasoning_delta", text: "First thought", projection_id: "shared",
    });
    expect(reasoning.effects.bodyWrites).toEqual(new Set(["shared"]));

    const reasoningEnd = project({ ...turn, event: "reasoning_end", text: "." });
    expect(reasoningEnd.effects.bodyWrites).toEqual(new Set(["shared"]));
    expect(reasoningEnd.state.messages[0].reasoning).toBe("First thought.");

    const answer = project({ ...turn, event: "delta", text: "Answer" });
    expect(answer.effects.bodyWrites).toEqual(new Set(["shared"]));
    const end = project({
      ...turn, event: "stream_end", text: "Final answer", resuming: true, merge_next: true,
    });
    expect(end.effects.bodyWrites).toEqual(new Set(["shared"]));

    const continuation = project({ ...turn, event: "reasoning_delta", text: "More thought" });
    expect(continuation.effects.bodyWrites).toEqual(new Set(["shared"]));
    expect(continuation.effects.consumed.size).toBe(0);
    expect(continuation.state.messages[0]).toMatchObject({
      id: "shared", content: "Final answer", reasoning: "First thought.\n\nMore thought",
    });
    const closure = project({ ...turn, event: "reasoning_end" });
    expect(closure.effects.bodyWrites.size).toBe(0);
    expect(closure.effects.consumed.size).toBe(0);
  });

  it("reports identified reasoning snapshots without claiming another open reasoning row", () => {
    const project = createProjector();
    project({ ...turn, event: "reasoning_delta", stream_id: "first", text: "Thought", projection_id: "thought" });
    project({ ...turn, event: "reasoning_end", stream_id: "first" });
    project({ ...turn, event: "delta", stream_id: "first", text: "Answer" });
    project({ ...turn, event: "stream_end", stream_id: "first" });
    project({ ...turn, event: "reasoning_delta", stream_id: "second", text: "Next thought", projection_id: "next" });

    const snapshot = project({ ...turn, event: "reasoning_end", stream_id: "first", text: "Revised thought" });
    expect(snapshot.effects.bodyWrites).toEqual(new Set(["thought"]));
    expect(snapshot.effects.consumed.size).toBe(0);
    expect(snapshot.state.messages[0].reasoning).toBe("Revised thought");
    expect(snapshot.state.messages[1]).toMatchObject({ id: "next", reasoningStreaming: true });

    const ignored = project({ ...turn, event: "reasoning_delta", stream_id: "first", text: "Late" });
    expect(ignored.effects.bodyWrites.size).toBe(0);
    expect(ignored.effects.consumed.size).toBe(0);
  });

  it("reports late answer snapshot targets but not textless metadata or closure patches", () => {
    const project = createProjector();
    project({ ...turn, event: "delta", stream_id: "first", text: "Draft", projection_id: "first" });
    project({ ...turn, event: "stream_end", stream_id: "first" });
    project({ ...turn, event: "message", kind: "tool_hint", text: "Tool", projection_id: "tool" });
    project({ ...turn, event: "delta", stream_id: "second", text: "Current", projection_id: "second" });

    const snapshot = project({ ...turn, event: "stream_end", stream_id: "first", text: "Final" });
    expect(snapshot.effects.bodyWrites).toEqual(new Set(["first"]));
    expect(snapshot.effects.consumed.size).toBe(0);
    expect(snapshot.state.activeAssistantId).toBe("second");
    for (const streamId of ["first", "empty"]) {
      const metadata = project({ ...turn, event: "stream_end", stream_id: streamId, response_sources: [] });
      expect(metadata.effects.bodyWrites.size).toBe(0);
      expect(metadata.effects.consumed.size).toBe(0);
      expect(metadata.state.activeAssistantId).toBe("second");
      expect(metadata.state.messages).toHaveLength(3);
    }
    const cleared = project({ ...turn, event: "stream_end", stream_id: "first", text: "" });
    expect(cleared.effects.bodyWrites).toEqual(new Set(["first"]));
    expect(cleared.state.messages[0].content).toBe("");
    expect(cleared.state.activeAssistantId).toBe("second");
  });

  it("reports only the destination slice of legacy cumulative HTTP answer snapshots", () => {
    const project = createProjector();
    project({
      ...turn, event: "stream_end", stream_id: "answer", turn_seq: 2, text: "Before ",
      resuming: true, merge_next: true, projection_id: "before",
    }, { persisted: true });
    project({
      ...turn, event: "message", kind: "tool_hint", turn_seq: 3, text: "Tool", projection_id: "tool",
    }, { persisted: true });
    const after = project({
      ...turn, event: "stream_end", stream_id: "answer", turn_seq: 5,
      text: "Before after", projection_id: "after",
    }, { persisted: true });
    expect(after.effects.bodyWrites).toEqual(new Set(["after"]));
    expect(after.effects.consumed.size).toBe(0);
    expect(after.state.messages.map((message) => message.content)).toEqual(["Before ", "Tool", "after"]);

    const revised = project({
      ...turn, event: "stream_end", stream_id: "answer", turn_seq: 6, text: "Before revised",
    }, { persisted: true });
    expect(revised.effects.bodyWrites).toEqual(new Set(["after"]));
    expect(revised.state.messages[2]).toMatchObject({ content: "revised", projectionStartSeq: 5, turnSeq: 6 });
  });

  it("reports continuation effects after copying a merge_next checkpoint with closed wire fences", () => {
    const project = createProjector();
    project({ ...turn, event: "delta", stream_id: "first", text: "First", turn_seq: 2, projection_id: "first" }, { startSeq: 1 });
    project({ ...turn, event: "stream_end", stream_id: "first", turn_seq: 3 });
    project({ ...turn, event: "message", kind: "tool_hint", text: "Tool", turn_seq: 4, projection_id: "tool" });
    project({ ...turn, event: "delta", stream_id: "second", text: "Next ", turn_seq: 6, projection_id: "second" }, { startSeq: 5 });
    project({ ...turn, event: "stream_end", stream_id: "second", text: "Next ", turn_seq: 7, resuming: true, merge_next: true });
    const queued = project({ ...turn, event: "reasoning_delta", stream_id: "second", text: "Queued ", turn_seq: 8 });
    const checkpoint = copyThreadCheckpoint({ projection: queued.state, sideChannelTurnIds: new Set(["command"]) });
    const restored = createProjector(copyThreadCheckpoint(checkpoint).projection);

    const ignored = restored({ ...turn, event: "delta", stream_id: "first", text: "Late", turn_seq: 9 });
    expect(ignored.effects.bodyWrites.size).toBe(0);
    const reasoning = restored({ ...turn, event: "reasoning_delta", stream_id: "second", text: "continued", turn_seq: 10 });
    expect(reasoning.effects.bodyWrites).toEqual(new Set(["second"]));
    const closure = restored({ ...turn, event: "reasoning_end", stream_id: "second", turn_seq: 11 });
    expect(closure.effects.bodyWrites.size).toBe(0);
    restored({ ...turn, event: "delta", stream_id: "second", text: "last", turn_seq: 12 });
    const completed = restored({ ...turn, event: "stream_end", stream_id: "second", text: "Next last", turn_seq: 13 });
    expect(completed.effects.bodyWrites).toEqual(new Set(["second"]));
    expect(completed.effects.consumed.size).toBe(0);
    expect(completed.state.messages[0]).toMatchObject({ content: "First", projectionStartSeq: 1 });
    expect(completed.state.messages[2]).toMatchObject({
      content: "Next last", reasoning: "Queued continued", projectionStartSeq: 5, turnSeq: 13,
    });
    expect(checkpoint.projection.messages[2]).toMatchObject({ content: "Next ", reasoning: "Queued " });
    expect(checkpoint.projection.closedAnswerStreamIds.size).toBe(1);
    expect(completed.state.closedAnswerStreamIds.size).toBe(2);
  });

  it("reports only the tool body target when activity closes an answer, including trace merges", () => {
    const project = createProjector();
    project({ ...turn, event: "delta", text: "Working", projection_id: "answer" });
    const activity = project({
      ...turn,
      event: "message",
      kind: "tool_hint",
      text: "Running command",
      projection_id: "tool",
      tool_events: [{ call_id: "exec-1", name: "exec", phase: "start" }],
    });
    expect(activity.state.closedAssistantIds.has("answer")).toBe(true);
    expect(activity.effects.bodyWrites).toEqual(new Set(["tool"]));
    expect(activity.effects.consumed.size).toBe(0);

    const merged = project({
      ...turn,
      event: "message",
      kind: "progress",
      text: "Command finished",
      tool_events: [{ call_id: "exec-1", name: "exec", phase: "end", result: "done" }],
    });
    expect(merged.effects.bodyWrites).toEqual(new Set(["tool"]));
    expect(merged.state.messages.find((message) => message.id === "tool")?.toolEvents)
      .toEqual([{ call_id: "exec-1", name: "exec", phase: "end", result: "done" }]);
  });

  it("reports every stripped hint and edit target, consuming only the removed trace row", () => {
    const project = createProjector();
    const write = { call_id: "write-1", name: "write_file", arguments: { path: "notes.md" } };
    project({
      ...turn, event: "message", kind: "tool_hint", text: "Writing", projection_id: "removed-hint",
      tool_events: [{ ...write, phase: "start" }],
    });
    project({ ...turn, event: "delta", text: "Saving notes", projection_id: "answer" });
    project({
      ...turn, event: "message", kind: "progress", text: "Written", projection_id: "kept-hint",
      tool_events: [
        { ...write, phase: "end" },
        { call_id: "exec-1", name: "exec", phase: "end" },
      ],
    });

    const edit = project({
      ...turn, event: "file_edit", edits: [fileEdit()], projection_id: "edits",
    });
    expect(edit.effects.bodyWrites).toEqual(new Set(["removed-hint", "kept-hint", "edits"]));
    expect(edit.effects.consumed).toEqual(new Set(["removed-hint"]));
    expect(edit.state.messages.find((message) => message.id === "removed-hint")).toBeUndefined();
    expect(edit.state.messages.find((message) => message.id === "kept-hint")?.toolEvents)
      .toEqual([{ call_id: "exec-1", name: "exec", phase: "end" }]);
    expect(edit.state.messages.find((message) => message.id === "edits")?.fileEdits)
      .toEqual([fileEdit()]);

    const completed = project({
      ...turn, event: "file_edit", edits: [fileEdit({ status: "done", phase: "end", added: 2 })],
    });
    expect(completed.effects.bodyWrites).toEqual(new Set(["edits"]));
    expect(completed.effects.consumed.size).toBe(0);
  });

  it("transfers the consumed active row to the plain assistant replacement", () => {
    const project = createProjector();
    project({ ...turn, event: "delta", text: "Draft", projection_id: "draft" });
    const replacement = project({
      ...turn, event: "message", text: "Final reply", projection_id: "final",
    });
    expect(replacement.effects.bodyWrites).toEqual(new Set(["final"]));
    expect(replacement.effects.consumed).toEqual(new Set(["draft"]));
    expect(replacement.state.messages.find((message) => message.id === "final")?.content)
      .toBe("Final reply");
  });

  it.each([false, true])("reports reasoning-placeholder absorption (sideChannel=%s)", (sideChannel) => {
    const project = createProjector();
    project({
      ...turn, event: "message", kind: "reasoning", text: "Thinking", projection_id: "reasoning",
    });
    const absorbed = project({
      ...turn, event: "message", text: "Explained", projection_id: "unused-reply-id",
    }, { sideChannel });
    expect(absorbed.effects.bodyWrites).toEqual(new Set(["reasoning"]));
    expect(absorbed.effects.consumed).toEqual(new Set(["reasoning"]));
    expect(absorbed.state.messages[0]).toMatchObject({
      id: "reasoning", content: "Explained", reasoning: "Thinking",
    });
  });

  it("reports input, stream-end insertion and compaction bodies without owning lifecycle flags", () => {
    const project = createProjector();
    const input = project({
      ...turn, event: "user_message", text: "Prompt", starts_turn: true, projection_id: "input",
    });
    expect(input.effects.bodyWrites).toEqual(new Set(["input"]));
    const answer = project({ ...turn, event: "stream_end", text: "Reply", projection_id: "answer" });
    expect(answer.effects.bodyWrites).toEqual(new Set(["answer"]));
    const started = project({
      ...turn, event: "context_compaction", compaction_id: "compact", phase: "started",
    });
    expect(started.effects.bodyWrites).toEqual(new Set(["compaction-compact"]));
    const finished = project({
      ...turn, event: "context_compaction", compaction_id: "compact", phase: "succeeded",
    });
    expect(finished.effects.bodyWrites).toEqual(new Set(["compaction-compact"]));

    for (const event of [
      { ...turn, event: "reasoning_end" },
      { ...turn, event: "stream_end" },
      { ...turn, event: "turn_end", latency_ms: 120, context_window_tokens: 4096 },
    ] satisfies ThreadProjectionEvent[]) {
      const closure = project(event);
      expect(closure.effects.bodyWrites.size).toBe(0);
      expect(closure.effects.consumed.size).toBe(0);
    }
  });

  it("leaves projection state unchanged when reporting is optional", () => {
    const events: ThreadProjectionEvent[] = [
      { ...turn, event: "user_message", text: "Prompt", starts_turn: true },
      { ...turn, event: "reasoning_delta", text: "Thinking" },
      { ...turn, event: "reasoning_end" },
      { ...turn, event: "delta", text: "Draft" },
      { ...turn, event: "message", kind: "tool_hint", text: "Writing",
        tool_events: [{ call_id: "write-1", name: "write_file", phase: "start" }] },
      { ...turn, event: "file_edit", edits: [fileEdit()] },
      { ...turn, event: "stream_end", text: "Final reply" },
      { ...turn, event: "message", text: "Replacement" },
      { ...turn, event: "context_compaction", compaction_id: "compact", phase: "succeeded" },
      { ...turn, event: "turn_end", latency_ms: 100 },
    ];
    let reported = createThreadProjectionState();
    let unreported = createThreadProjectionState();
    events.forEach((event, index) => {
      const options = { createId: () => `row-${index}`, now: 1_800_000_000_000 };
      const effects: ThreadProjectionEffects = { bodyWrites: new Set(), consumed: new Set() };
      reported = projectThreadEvent(reported, event, { ...options, effects });
      unreported = projectThreadEvent(unreported, event, options);
      expect(reported).toEqual(unreported);
    });
  });
});
