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

  it.each([
    ["failed", "succeeded", "Command failed", "Ran command"],
    ["succeeded", "running", "Ran command", "Running at last check"],
  ] as const)("keeps same-command %s and %s identities, states, output and counts in live, summary and detail", async (first, second, firstLabel, secondLabel) => {
    await setAppLanguage("en");
    const firstEvent = { ...observation(first, 1), call_id: "execution:first", result: "first output" };
    const secondEvent = { ...observation(second, 1), call_id: "execution:second", result: "second output" };
    const events = [wire(firstEvent, 1), wire(secondEvent, 2)];
    const assertRows = (thread: ThreadTranscript, output: boolean) => {
      const view = show(thread);
      const rows = screen.getAllByTestId("activity-step");
      expect(rows).toHaveLength(2);
      expect(rows[0].textContent).toContain(firstLabel);
      expect(rows[1].textContent).toContain(secondLabel);
      if (output) {
        expect(rows[0].closest("details")?.querySelector("pre")?.textContent).toBe("first output");
        expect(rows[1].closest("details")?.querySelector("pre")?.textContent).toBe("second output");
      }
      const messages = coalesceActivityMessages(thread.messages);
      expect(messages.flatMap((message) => message.toolEvents ?? []).map((event) => event.call_id))
        .toEqual(["execution:first", "execution:second"]);
      expect(messages.flatMap((message) => message.traces ?? [])).toHaveLength(2);
      view.unmount();
    };
    const live = new ThreadTranscript();
    for (const event of events) live.project(event, { createId: () => "same-command", now: 10 });
    assertRows(live, true);
    const ref = { ref: "same-command-detail", bytes: 40_000, traceCount: 2 };
    const summary = { ...wire(firstEvent, 1), trace_detail: ref,
      tool_events: [{ ...firstEvent, result: null }, { ...secondEvent, result: null }] };
    const refreshed = new ThreadTranscript();
    expect(refreshed.accept(history([summary]), refreshed.begin("initial"))).toBe(true);
    assertRows(refreshed, false);
    refreshed.expandDetail(ref.ref, events);
    assertRows(refreshed, true);
  });

  it("preserves the existing current-time presentation for an observed successful command", async () => {
    await setAppLanguage("en");
    const thread = new ThreadTranscript();
    thread.project(wire({ ...observation("succeeded", 1), arguments: { command: "date +%Y" } }, 1),
      { createId: () => "time", now: 10 });
    show(thread);
    expect(screen.getByText("Checked current time")).toBeTruthy();
  });

  it("retains legacy history and rejects malformed observation metadata at the wire edge", () => {
    const legacy: ToolProgressEvent = { phase: "end", call_id: "legacy", name: "exec", arguments: { command } };
    expect(normalizeToolProgressEvents([legacy])).toEqual([legacy]);
    const malformed = { ...observation("running", 1), execution: { state: "succeeded", observed_at: "not-a-time" } };
    expect(normalizeToolProgressEvents([malformed])).toEqual([]);
  });
});
