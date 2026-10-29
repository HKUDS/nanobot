import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AgentActivityCluster } from "@/components/thread/AgentActivityCluster";
import { coalesceActivityMessages } from "@/components/thread/activity/activity-message-model";
import { setAppLanguage } from "@/i18n";
import { ThreadTranscript } from "@/lib/thread-transcript";
import { normalizeToolProgressEvents } from "@/lib/tool-traces";
import type { ExecutionProgress, ThreadProjectionEvent, ToolProgressEvent, WebuiThreadPersistedPayload } from "@/lib/types";

const command = "python work.py";

function observation(state: ExecutionProgress["state"], index: number): ToolProgressEvent {
  return {
    version: 1, call_id: "execution:public-command", name: "exec",
    phase: state === "running" || state === "stopping" ? index === 0 ? "start" : "update"
      : state === "failed" || state === "timed_out" ? "error" : "end",
    arguments: { command }, result: "initial output\nlatest output",
    execution: {
      state, observed_at: index + 1, sequence: index + 1, exit_code: state === "failed" ? 7 : state === "succeeded" ? 0 : null,
      finish_reason: state === "failed" || state === "succeeded" ? "exit"
        : state === "cancelled" ? "cancelled" : state === "timed_out" ? "max_runtime" : null,
      output_incomplete: false, truncated_chars: 0,
    },
  };
}

function wire(tool: ToolProgressEvent, seq: number): ThreadProjectionEvent {
  return { event: "message", chat_id: "synthetic", turn_id: "turn", turn_seq: seq,
    projection_id: `event-${seq}`, kind: "tool_hint", text: "", tool_events: [tool] };
}

function history(events: ThreadProjectionEvent[]): WebuiThreadPersistedPayload {
  return { schemaVersion: 3, projection: "events", events,
    completed_turn_ids: ["turn"], page: { before_cursor: null, has_more_before: false, user_message_offset: 0 } };
}

function show(thread: ThreadTranscript) {
  return render(<AgentActivityCluster messages={thread.messages} isTurnStreaming={false}
    hasBodyBelow expanded />);
}

afterEach(cleanup);

describe("public execution observations", () => {
  it.each([
    ["running", "Running at last check"], ["stopping", "Stopping at last check"],
    ["succeeded", "Ran command"], ["failed", "Command failed"],
    ["cancelled", "Command cancelled"], ["timed_out", "Command timed out"],
  ] as const)("keeps one command and its %s state through live, refresh, reconnect and detail", async (state, label) => {
    await setAppLanguage("en");
    const events: ThreadProjectionEvent[] = [
      wire(observation("running", 0), 1), wire(observation("running", 1), 2),
      wire(observation(state, 2), 3),
      { event: "turn_end", chat_id: "synthetic", turn_id: "turn", turn_seq: 4 },
    ];
    const live = new ThreadTranscript();
    for (const event of events) live.project(event, { createId: () => "live", now: 10 });
    const view = show(live);
    expect(screen.getAllByTestId("activity-step")).toHaveLength(1);
    expect(screen.getByText(new RegExp(label))).toBeTruthy();
    expect(screen.getByText(/initial output/)).toBeTruthy();
    if (state === "failed") expect(screen.getByText("Exit 7")).toBeTruthy();
    const liveRows = coalesceActivityMessages(live.messages);
    expect(liveRows.flatMap((row) => row.toolEvents ?? [])).toHaveLength(1);
    view.unmount();

    const refreshed = new ThreadTranscript();
    expect(refreshed.accept(history(events), refreshed.begin("initial"))).toBe(true);
    expect(coalesceActivityMessages(refreshed.messages).flatMap((row) => row.toolEvents ?? []))
      .toEqual(liveRows.flatMap((row) => row.toolEvents ?? []));
    const restored = new ThreadTranscript([], refreshed.save());
    for (const event of events) restored.project(event, { createId: () => "duplicate", now: 10 });
    expect(coalesceActivityMessages(restored.messages).flatMap((row) => row.toolEvents ?? [])).toHaveLength(1);
    const latest = observation(state, 2);
    const summary = new ThreadTranscript();
    const detailRef = { ref: "1.event-1", bytes: 40_000, traceCount: 1 };
    const summaryEvent = { ...wire({ ...latest, result: null }, 1), trace_detail: detailRef };
    expect(summary.accept(history([summaryEvent, events[3]]), summary.begin("initial"))).toBe(true);
    const summaryView = show(summary);
    expect(screen.getAllByTestId("activity-step")).toHaveLength(1);
    expect(screen.getByText(new RegExp(label))).toBeTruthy();
    summaryView.unmount();
    // Expand the actual deferred row through the client's detail boundary.
    summary.expandDetail(detailRef.ref, events.slice(0, 3));
    const detailView = show(summary);
    expect(screen.getAllByTestId("activity-step")).toHaveLength(1);
    expect(screen.getByText(new RegExp(label))).toBeTruthy();
    expect(screen.getByText(/initial output/)).toBeTruthy();
    detailView.unmount();
  });

  it("retains legacy history and rejects malformed observation metadata at the wire edge", () => {
    const legacy: ToolProgressEvent = { phase: "end", call_id: "legacy", name: "exec", arguments: { command } };
    expect(normalizeToolProgressEvents([legacy])).toEqual([legacy]);
    const malformed = { ...observation("running", 1), execution: { state: "succeeded", observed_at: "not-a-time" } };
    expect(normalizeToolProgressEvents([malformed])).toEqual([]);
  });
});
