import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SubagentTaskDock } from "@/components/thread/SubagentTaskDock";
import { SubagentThreadMessages } from "@/components/thread/SubagentTaskResults";
import { SubagentTasksProvider } from "@/components/thread/SubagentTasks";
import { setAppLanguage } from "@/i18n";
import { createThreadProjectionState, projectThreadEvent, projectThreadEvents } from "@/lib/thread-event-projection";
import type { InboundEvent, SubagentTaskSnapshot, ThreadProjectionEvent } from "@/lib/types";

const handlers = new Set<(event: InboundEvent) => void>();
const client = {
  requestMutation: vi.fn(),
  onChat: vi.fn((_id: string, handler: (event: InboundEvent) => void) => {
    handlers.add(handler);
    return () => { handlers.delete(handler); };
  }),
  onStatus: vi.fn(() => () => {}),
};
function task(id: string, state: SubagentTaskSnapshot["state"] = "done"): SubagentTaskSnapshot {
  return {
    task_id: id, revision: 1, label: `Result ${id}`, task_description: "Inspect",
    state, phase: state === "done" ? "finished" : "awaiting_model", elapsed_seconds: 4,
    iteration: 1, tool_events: [], usage: null, receipts: {}, result: null, partial: false,
    stop_reason: null, error: null, origin_turn_id: "turn", origin_message_id: "prompt", origin_call_id: `call-${id}`,
    created_at: 100, completed_at: state === "done" ? 104 : null,
  };
}
// Use wire events, not hand-built UI messages: the anchor must survive the real
// projection pipeline before the transcript and task provider can consume it.
function transcript(ids: string[]) {
  const records: Record<string, unknown>[] = [
    { event: "user_message", projection_id: "prompt", starts_turn: true, text: "Prompt", turn_seq: 1 },
    { event: "message", projection_id: "before", text: "Before invocation", turn_seq: 2 },
  ];
  ids.forEach((id, index) => {
    records.push({ event: "subagent_anchor", projection_id: `anchor-${id}`, task_id: id,
      call_id: `call-${id}`, turn_seq: 3 + index * 2 });
    records.push({ event: "message", projection_id: `after-${id}`, text: `After ${id}`, turn_seq: 4 + index * 2 });
  });
  return projectThreadEvents(records.map((record) => ({ chat_id: "a", turn_id: "turn", ...record })) as ThreadProjectionEvent[]);
}
function view(ids: string[]) {
  const messages = transcript(ids);
  return <SubagentTasksProvider client={client} sessionKey="websocket:a" token="tok" enabled liveEvents historyEnabled messages={messages}>
    <div data-testid="transcript"><SubagentThreadMessages messages={messages} /></div>
    <div data-testid="composer" className="thread-composer-stack"><SubagentTaskDock /><textarea aria-label="Message" /></div>
  </SubagentTasksProvider>;
}
type Wire = Record<string, unknown>;
// Real transport order: create start, durable anchor, create end.
function createCall(id: string, turn = "turn"): Wire[] {
  const call = { call_id: `call-${id}`, name: "subagent", arguments: { action: "create" } };
  return [
    { event: "message", kind: "tool_hint", text: "Starting", projection_id: `start-${id}`, tool_events: [{ ...call, phase: "start" }], turn_id: turn },
    { event: "subagent_anchor", projection_id: `anchor-${id}`, task_id: id, call_id: `call-${id}`, turn_id: turn },
    { event: "message", kind: "progress", text: "Started", projection_id: `end-${id}`, tool_events: [{ ...call, phase: "end", result: "started" }], turn_id: turn },
  ];
}
function wireView(records: Wire[], mode: "live" | "replay" = "replay") {
  const events = records.map((record, index) => ({ chat_id: "a", turn_id: "turn", turn_seq: index + 1, ...record })) as ThreadProjectionEvent[];
  const messages = mode === "replay" ? projectThreadEvents(events) : events.reduce(
    (state, event, index) => projectThreadEvent(state, event, { createId: () => `live-${index}`, now: 1000 + index }),
    createThreadProjectionState(),
  ).messages;
  return <SubagentTasksProvider client={client} sessionKey="websocket:a" token="tok" enabled liveEvents historyEnabled messages={messages}>
    <div data-testid="transcript"><SubagentThreadMessages messages={messages} isStreaming={mode === "live"} activeTurnId="turn" /></div>
    <div data-testid="composer"><SubagentTaskDock /><textarea aria-label="Message" /></div>
  </SubagentTasksProvider>;
}
function summaries() { return within(screen.getByTestId("transcript")).queryAllByRole("button", { name: /Subtasks/ }); }
async function expectGroups(counts: number[]) {
  await waitFor(() => {
    const groups = summaries();
    expect(groups).toHaveLength(counts.length);
    counts.forEach((count, i) => expect(groups[i].textContent).toContain(`Completed: ${count}`));
  });
}
function expectVisibleTasks(ids: string[]) {
  for (const id of ids) expect(within(screen.getByTestId("transcript")).getByRole("button", { name: new RegExp(`Result ${id}`) })).not.toBeNull();
}
function before(a: Node, b: Node) {
  expect(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
}
function response(tasks: SubagentTaskSnapshot[]) {
  return new Response(JSON.stringify({ tasks }), { headers: { "content-type": "application/json" } });
}

describe("independent subagent anchors", () => {
  beforeEach(async () => {
    handlers.clear();
    await setAppLanguage("en");
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it("keeps running work in the composer only, then places its terminal result at the anchor", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response([task("one", "running")])));
    render(view(["one"]));
    expect((await screen.findByTestId("subagent-task-dock-trigger")).textContent).toContain("Running: 1");
    expect(screen.getByTestId("transcript").querySelector('[data-subagent-id="one"]')).toBeNull();
    act(() => { handlers.forEach((handler) => handler({ event: "subagent_task", chat_id: "a", task: { ...task("one"), revision: 2 } })); });
    await waitFor(() => expect(screen.getByTestId("transcript").querySelector('[data-subagent-id="one"]')).not.toBeNull());
    const result = screen.getByTestId("transcript").querySelector('[data-subagent-id="one"]')!;
    before(screen.getByText("Before invocation"), result);
    before(result, screen.getByText("After one"));
  });

  it("refreshes the anchored terminal snapshot on a settlement notice", async () => {
    let finished = false;
    vi.stubGlobal("fetch", vi.fn(async () => response([task("one", finished ? "done" : "running")])));
    render(view(["one"]));
    await screen.findByTestId("subagent-task-dock-trigger");
    finished = true;
    act(() => { handlers.forEach((handler) => handler({ event: "subagent_task_settled", chat_id: "a",
      task_id: "one", state: "done", revision: 2, completed_at: 104 })); });
    await waitFor(() => expect(screen.getByTestId("transcript").querySelector('[data-subagent-id="one"]')).not.toBeNull());
    expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThan(1);
  });

  it("does not attach old terminal snapshots by prompt or turn without an anchor", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response([task("legacy")])));
    render(view([]));
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(screen.getByTestId("transcript").querySelector('[data-subagent-id="legacy"]')).toBeNull();
    expect(screen.getByTestId("composer").querySelector('[data-subagent-id="legacy"]')).toBeNull();
  });

  it("places an anchor after an injected follow-up within the same run", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response([task("one")])));
    const events = [
      { event: "user_message", projection_id: "first", starts_turn: true, text: "Initial question", turn_seq: 1 },
      { event: "message", projection_id: "thinking", text: "Working", turn_seq: 2 },
      { event: "user_message", projection_id: "followup", starts_turn: false, text: "Injected follow-up", turn_id: "followup-turn", turn_seq: 1 },
      { event: "subagent_anchor", projection_id: "anchor", task_id: "one", call_id: "call-one", turn_seq: 4 },
      { event: "message", projection_id: "answer", text: "Final answer", turn_seq: 5 },
    ].map((event) => ({ chat_id: "a", turn_id: "turn", ...event })) as ThreadProjectionEvent[];
    const messages = projectThreadEvents(events);
    render(<SubagentTasksProvider client={client} sessionKey="websocket:a" token="tok" enabled liveEvents messages={messages}>
      <div data-testid="transcript"><SubagentThreadMessages messages={messages} /></div>
    </SubagentTasksProvider>);
    await waitFor(() => expect(screen.getByTestId("transcript").querySelector('[data-subagent-id="one"]')).not.toBeNull());
    const result = screen.getByTestId("transcript").querySelector('[data-subagent-id="one"]')!;
    before(screen.getByText("Injected follow-up"), result);
    before(result, screen.getByText("Final answer"));
  });

  it("queries only loaded anchor task IDs and renders multiple anchors independently in event order", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      expect(String(input)).toContain("/subagents?");
      return response([task("one"), task("two"), task("off-page")]);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(view(["one", "two"]));
    await waitFor(() => {
      const urls = fetchMock.mock.calls.map(([input]) => new URL(String(input), "http://localhost"));
      expect(urls.some((url) => url.searchParams.getAll("task_id").sort().join(",") === "one,two")).toBe(true);
      expect(urls.every((url) => !url.searchParams.has("message_id") && !url.searchParams.has("turn_id"))).toBe(true);
    });
    await waitFor(() => expect(screen.getByTestId("transcript").querySelector('[data-subagent-id="two"]')).not.toBeNull());
    const transcriptNode = screen.getByTestId("transcript");
    const first = transcriptNode.querySelector('[data-subagent-id="one"]')!;
    const second = transcriptNode.querySelector('[data-subagent-id="two"]')!;
    expect(first).not.toBeNull();
    before(screen.getByText("Before invocation"), first);
    before(first, screen.getByText("After one"));
    before(screen.getByText("After one"), second);
    before(second, screen.getByText("After two"));
    expect(transcriptNode.querySelector('[data-subagent-id="off-page"]')).toBeNull();
  });
  it.each(["live", "replay"] as const)("hides successful create activity but retains dock and anchored results (%s)", async (mode) => {
    vi.stubGlobal("fetch", vi.fn(async () => response([task("one", "running"), task("two")] )));
    render(wireView([...createCall("one"), ...createCall("two")], mode));
    expect((await screen.findByTestId("subagent-task-dock-trigger")).textContent).toContain("Running: 1");
    await expectGroups([1]);
    const transcript = within(screen.getByTestId("transcript"));
    expect(transcript.queryByText(/creating subtask|subtask created/i)).toBeNull();
    expect(transcript.queryByRole("button", { name: /^worked/i })).toBeNull();
    act(() => { handlers.forEach((handler) => handler({ event: "subagent_task", chat_id: "a", task: { ...task("one"), revision: 2 } })); });
    await expectGroups([2]);
    fireEvent.click(summaries()[0]);
    expectVisibleTasks(["one", "two"]);
    expect(transcript.queryByText(/creating subtask|subtask created/i)).toBeNull();
    expect(transcript.queryByRole("button", { name: /^worked/i })).toBeNull();
  });

  it.each(["live", "replay"] as const)("retains mixed tools, failed create and other subagent operations (%s)", async (mode) => {
    vi.stubGlobal("fetch", vi.fn(async () => response([task("one"), task("two")])));
    const mixed: Wire = { event: "message", kind: "tool_hint", projection_id: "mixed", text: "Tool activity", tool_events: [
      { call_id: "call-two", name: "subagent", phase: "start", arguments: { action: "create" } },
      { call_id: "exec", name: "exec", phase: "start", arguments: { command: "pwd" } },
      { call_id: "failed", name: "subagent", phase: "error", arguments: { action: "create" }, result: "creation failed" },
      { call_id: "check", name: "subagent", phase: "start", arguments: { action: "check" } },
    ] };
    render(wireView([...createCall("one"), mixed, ...createCall("two").slice(1)], mode));
    await expectGroups([1, 1]);
    const transcript = within(screen.getByTestId("transcript"));
    // Expand the ordinary activity, not the independent subtask groups.
    const activity = transcript.getAllByRole("button").find((button) => /worked|working/i.test(button.textContent ?? ""));
    expect(activity).toBeDefined();
    fireEvent.click(activity!);
    expect(transcript.getByText(/running command/i)).not.toBeNull();
    expect(transcript.getByText(/could not create subtask/i)).not.toBeNull();
    expect(transcript.getByText(/checking subtask|subtask status retrieved/i)).not.toBeNull();
    expect(transcript.queryByText(/^creating subtask/i)).toBeNull();
    summaries().forEach((summary) => fireEvent.click(summary));
    expectVisibleTasks(["one", "two"]);
  });

  it("groups four consecutive create calls and exposes every task", async () => {
    const ids = ["one", "two", "three", "four"];
    vi.stubGlobal("fetch", vi.fn(async () => response(ids.map((id) => task(id)))));
    render(wireView(ids.flatMap((id) => createCall(id))));
    await expectGroups([4]);
    fireEvent.click(summaries()[0]);
    expectVisibleTasks(ids);
  });

  it("keeps active work in the dock and updates the group when it finishes", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response([task("one"), task("two", "running")])));
    render(wireView([...createCall("one"), ...createCall("two")]));
    expect((await screen.findByTestId("subagent-task-dock-trigger")).textContent).toContain("Running: 1");
    await expectGroups([1]);
    fireEvent.click(summaries()[0]);
    expect(within(screen.getByTestId("transcript")).queryByRole("button", { name: /Result two/ })).toBeNull();
    act(() => { handlers.forEach((handler) => handler({ event: "subagent_task", chat_id: "a", task: { ...task("two"), revision: 2 } })); });
    await expectGroups([2]);
    expectVisibleTasks(["one", "two"]);
  });

  it.each([
    ["user message", { event: "user_message", projection_id: "boundary-user", starts_turn: false, text: "Follow-up" }],
    ["assistant text", { event: "message", projection_id: "boundary-answer", text: "Intervening answer" }],
    ["file edit", { event: "file_edit", projection_id: "boundary-edit", edits: [{ version: 1, call_id: "edit", tool: "edit_file", path: "a.txt", phase: "end", added: 1, deleted: 0, status: "done" }] }],
    ["another tool", { event: "message", kind: "tool_hint", projection_id: "boundary-tool", text: "Running command", tool_events: [{ call_id: "exec", name: "exec", phase: "start", arguments: { command: "pwd" } }] }],
  ])("splits groups around %s", async (_name, boundary) => {
    const ids = ["one", "two", "three", "four"];
    vi.stubGlobal("fetch", vi.fn(async () => response(ids.map((id) => task(id)))));
    render(wireView([...createCall("one"), ...createCall("two"), boundary, ...createCall("three"), ...createCall("four")]));
    await expectGroups([2, 2]);
    fireEvent.click(summaries()[0]);
    fireEvent.click(summaries()[1]);
    expectVisibleTasks(ids);
  });

  it.each([
    ["mixed tool batch", [
      { call_id: "call-two", name: "subagent", phase: "start", arguments: { action: "create" } },
      { call_id: "other", name: "exec", phase: "start", arguments: { command: "pwd" } },
    ]],
    ["another subagent operation", [
      { call_id: "check", name: "subagent", phase: "start", arguments: { action: "check" } },
    ]],
    ["a create call without a loaded anchor", [
      { call_id: "unknown", name: "subagent", phase: "start", arguments: { action: "create" } },
    ]],
  ])("does not merge across %s", async (_name, toolEvents) => {
    vi.stubGlobal("fetch", vi.fn(async () => response([task("one"), task("two")])));
    render(wireView([...createCall("one"), { event: "message", kind: "tool_hint", projection_id: "boundary",
      text: "Tool activity", tool_events: toolEvents }, ...createCall("two")]));
    await expectGroups([1, 1]);
  });

  it("does not merge calls from different turns", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response([task("one"), task("two")])));
    render(wireView([...createCall("one", "turn-1"), ...createCall("two", "turn-2")]));
    await expectGroups([1, 1]);
  });

  it("merges earlier loaded anchors while preserving expansion and excluding unloaded tasks", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response(["one", "two", "three", "four", "off-page"].map((id) => task(id)))));
    const { rerender } = render(wireView([...createCall("three"), ...createCall("four")]));
    await expectGroups([2]);
    fireEvent.click(summaries()[0]);
    expectVisibleTasks(["three", "four"]);
    expect(within(screen.getByTestId("transcript")).queryByRole("button", { name: /Result off-page/ })).toBeNull();
    rerender(wireView(["one", "two", "three", "four"].flatMap((id) => createCall(id))));
    await expectGroups([4]);
    expect(summaries()[0].getAttribute("aria-expanded")).toBe("true");
    expectVisibleTasks(["one", "two", "three", "four"]);
    expect(within(screen.getByTestId("transcript")).queryByRole("button", { name: /Result off-page/ })).toBeNull();
  });

});
