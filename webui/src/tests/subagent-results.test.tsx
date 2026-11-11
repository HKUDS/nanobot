import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SubagentTaskDock } from "@/components/thread/SubagentTaskDock";
import { SubagentThreadMessages, useHasSubagentResults } from "@/components/thread/SubagentTaskResults";
import { SubagentTasksProvider } from "@/components/thread/SubagentTasks";
import { setAppLanguage } from "@/i18n";
import { projectThreadEvents } from "@/lib/thread-event-projection";
import type { ThreadProjectionEvent } from "@/lib/types";
import { DEFAULT_LOCAL_PREFS, LOCAL_PREFS_STORAGE_KEY, writeLocalPreferences } from "@/lib/local-preferences";
import type { InboundEvent, SubagentTaskSnapshot, UIMessage } from "@/lib/types";

const requestMutation = vi.fn();
const chatHandlers = new Set<(event: InboundEvent) => void>();
const client = {
  requestMutation,
  onChat: vi.fn((_chatId: string, handler: (event: InboundEvent) => void) => {
    chatHandlers.add(handler);
    return () => { chatHandlers.delete(handler); };
  }),
  onStatus: vi.fn(() => () => {}),
};
const messages: UIMessage[] = [
  { id: "prompt-a", role: "user", content: "Inspect config", turnId: "turn-a", createdAt: 100_000 },
  { id: "anchor-a", role: "tool", content: "", turnId: "turn-a", createdAt: 100_500,
    subagentAnchor: { taskId: "task-1", callId: "call-1" } },
  { id: "answer-a", role: "assistant", content: "Main answer", turnId: "turn-a", createdAt: 101_000 },
];

function task(overrides: Partial<SubagentTaskSnapshot> = {}): SubagentTaskSnapshot {
  return {
    task_id: "task-1", revision: 1, label: "Config check", task_description: "Check configuration values",
    state: "done", phase: "finished", elapsed_seconds: 4, iteration: 1,
    tool_events: [], usage: null, receipts: {}, result: null, partial: false,
    stop_reason: null, error: null, origin_turn_id: "turn-a", origin_message_id: "prompt-a", origin_call_id: "call-1",
    created_at: 100, completed_at: 104, ...overrides,
  };
}
function response(tasks: SubagentTaskSnapshot[]): Response {
  return new Response(JSON.stringify({ tasks }), { headers: { "content-type": "application/json" } });
}
function childThread(answer: string): Response {
  return new Response(JSON.stringify({ schemaVersion: 3, projection: "events", active_turn_id: null, events: [
    { event: "user_message", chat_id: "task-1", starts_turn: true, projection_id: "child-prompt", turn_id: "child-turn", text: "Inspect the saved child session", created_at_ms: 100_000 },
    { event: "message", chat_id: "task-1", projection_id: "child-answer", turn_id: "child-turn", text: answer },
  ] }), { headers: { "content-type": "application/json" } });
}
function emitTask(snapshot: SubagentTaskSnapshot) {
  act(() => {
    chatHandlers.forEach((handler) => handler({ event: "subagent_task", chat_id: "a", task: snapshot }));
  });
}
function ResultsPresence({ threadMessages }: { threadMessages: UIMessage[] }) {
  return <output data-testid="has-results">{useHasSubagentResults(threadMessages) ? "yes" : "no"}</output>;
}
function layout({ threadMessages = messages, sessionKey = "websocket:a", liveEvents = true, historyEnabled = false, onActivityToggle }: {
  threadMessages?: UIMessage[];
  sessionKey?: string;
  liveEvents?: boolean;
  historyEnabled?: boolean;
  onActivityToggle?: () => void;
} = {}) {
  return <SubagentTasksProvider client={client} sessionKey={sessionKey} token="tok" enabled liveEvents={liveEvents} historyEnabled={historyEnabled} messages={threadMessages}>
    <ResultsPresence threadMessages={threadMessages} />
    <div data-testid="messages"><SubagentThreadMessages messages={threadMessages} onActivityToggle={onActivityToggle} /></div>
    <div data-testid="composer" className="thread-composer-stack"><SubagentTaskDock /><textarea aria-label="Message" /></div>
  </SubagentTasksProvider>;
}
function summary(region: HTMLElement) {
  return within(region).getByRole("button", { name: /^(Subtasks|Other tasks) (Completed|Finished):/ });
}
function expectBefore(first: Node, second: Node) {
  expect(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
}

describe("subagent result archives", () => {
  beforeEach(async () => {
    localStorage.removeItem(LOCAL_PREFS_STORAGE_KEY);
    await setAppLanguage("en");
    requestMutation.mockReset();
    client.onChat.mockClear();
    client.onStatus.mockClear();
    chatHandlers.clear();
    vi.stubGlobal("fetch", vi.fn(async () => response([task()])));
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    localStorage.removeItem(LOCAL_PREFS_STORAGE_KEY);
  });

  it("does not count an unanchored legacy completion as a visible history result", async () => {
    vi.mocked(fetch).mockImplementation(async () => response([]));
    render(layout({ threadMessages: [] }));
    emitTask(task({ origin_call_id: undefined, origin_turn_id: null, origin_message_id: null }));
    expect(screen.getByTestId("has-results")).toHaveTextContent("no");
  });

  it("shows active work in the dock and its terminal result at the independent anchor", async () => {
    const anchoredMessages = projectThreadEvents([
      { event: "user_message", chat_id: "a", projection_id: "prompt-a", turn_id: "turn-a", starts_turn: true, text: "Inspect config", turn_seq: 1 },
      { event: "subagent_anchor", chat_id: "a", projection_id: "anchor-a", turn_id: "turn-a", task_id: "task-1", call_id: "call-1", turn_seq: 2 },
      { event: "message", chat_id: "a", projection_id: "answer-a", turn_id: "turn-a", text: "Main answer", turn_seq: 3 },
    ] as ThreadProjectionEvent[]);
    vi.mocked(fetch).mockImplementation(async () => response([
      task({ origin_call_id: "call-1", state: "running", phase: "awaiting_model", completed_at: null }),
      task({ task_id: "queued", label: "Waiting check", state: "queued", completed_at: null }),
    ]));
    render(layout({ threadMessages: anchoredMessages }));
    expect(await screen.findByTestId("subagent-task-dock-trigger")).toHaveTextContent("Running: 2");
    const transcript = screen.getByTestId("messages");
    expect(transcript.querySelector('[data-subagent-id="task-1"]')).toBeNull();
    emitTask(task({ origin_call_id: "call-1", revision: 2, result: "Full findings stay in details" }));
    await waitFor(() => expect(transcript.querySelector('[data-subagent-id="task-1"]')).not.toBeNull());
    const result = transcript.querySelector('[data-subagent-id="task-1"]')!;
    expectBefore(screen.getByText("Inspect config"), result);
    expectBefore(result, screen.getByText("Main answer"));
    expect(screen.getByTestId("subagent-task-dock-trigger")).toHaveTextContent("Running: 1");
    expect(transcript).not.toHaveTextContent("Waiting check");
    expect(transcript).not.toHaveTextContent("Full findings stay in details");
  });

  it("groups consecutive terminal states and keeps cancellation distinct from failures", async () => {
    const states = [task(), task({ task_id: "cancelled", label: "Cancelled check", state: "cancelled" }),
      task({ task_id: "failed", label: "Failed check", state: "error", error: "Unreadable file" })];
    vi.mocked(fetch).mockImplementation(async () => response(states));
    const user = userEvent.setup();
    render(layout({ threadMessages: [messages[0], ...states.map((t) => ({
      id: `anchor-${t.task_id}`, role: "tool" as const, content: "", turnId: "turn-a", createdAt: 100_500,
      subagentAnchor: { taskId: t.task_id, callId: "call-1" },
    })), messages[2]] }));
    const archives = await screen.findAllByRole("region", { name: "Subtasks" });
    expect(archives).toHaveLength(1);
    expect(summary(archives[0])).toHaveTextContent("Finished: 3");
    expect(summary(archives[0])).toHaveTextContent("Review needed: 1");
    await user.click(summary(archives[0]));
    expect(within(archives[0]).getByRole("button", { name: "Cancelled check Cancelled 4s" })).toBeVisible();
    await user.click(within(archives[0]).getByRole("button", { name: "Failed check Failed 4s" }));
    expect(within(screen.getByRole("dialog", { name: "Failed check" })).getByRole("alert")).toHaveTextContent("Unreadable file");
    expect(requestMutation).not.toHaveBeenCalled();
  });

  it("restores completed work only in collapsed history and leaves full Markdown in the shared details", async () => {
    const result = "## Saved findings\n\n- **Verified** the configuration\n\n[Evidence](https://example.com/evidence)";
    vi.mocked(fetch).mockImplementation(async (url) => String(url).endsWith("/webui-thread")
      ? childThread(result) : response([task({ result: "A snapshot summary, not a chat panel" })]));
    const user = userEvent.setup();
    const view = render(layout({ liveEvents: false, historyEnabled: true }));
    const archive = await screen.findByRole("region", { name: "Subtasks" });
    expect(screen.getByTestId("composer")).not.toHaveTextContent("Config check");
    expect(screen.queryByTestId("subagent-task-dock-trigger")).not.toBeInTheDocument();
    expect(summary(archive)).toHaveAttribute("aria-expanded", "false");
    await user.click(summary(archive));
    expect(screen.getByTestId("messages")).not.toHaveTextContent("A snapshot summary, not a chat panel");
    expect(within(archive).queryByRole("link")).not.toBeInTheDocument();
    expect(within(archive).queryByRole("heading", { name: "Saved findings" })).not.toBeInTheDocument();
    await user.click(within(archive).getByRole("button", { name: "Config check Completed 4s" }));
    const detail = screen.getByRole("dialog", { name: "Config check" });
    expect(await within(detail).findByRole("heading", { name: "Saved findings" })).toBeVisible();
    expect(within(detail).getByRole("link", { name: "Evidence" })).toHaveAttribute("href", "https://example.com/evidence");
    view.unmount();

    render(layout({ liveEvents: false, historyEnabled: true }));
    const restored = await screen.findByRole("region", { name: "Subtasks" });
    expect(summary(restored)).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("subagent-task-dock-trigger")).not.toBeInTheDocument();
    await user.click(summary(restored));
    await user.click(within(restored).getByRole("button", { name: "Config check Completed 4s" }));
    expect(await within(screen.getByRole("dialog", { name: "Config check" })).findByRole("heading", { name: "Saved findings" })).toBeVisible();
    expect(requestMutation).not.toHaveBeenCalled();
  });

  it("keeps the outgoing transcript until the new session anchors arrive", async () => {
    vi.mocked(fetch).mockImplementation(async (input) => response([
      task(String(input).includes("websocket%3Ab") ? { task_id: "task-b", label: "Other check" } : {}),
    ]));
    const user = userEvent.setup();
    const view = render(layout());
    const archive = await screen.findByRole("region", { name: "Subtasks" });
    await user.click(summary(archive));
    const outgoingPrompt = screen.getByText("Inspect config");
    view.rerender(layout({ sessionKey: "websocket:b" }));
    expect(screen.getByText("Inspect config")).toBe(outgoingPrompt);
    await waitFor(() => expect(screen.queryByRole("region", { name: "Subtasks" })).not.toBeInTheDocument());
    const otherMessages: UIMessage[] = [
      { ...messages[0], id: "prompt-b", content: "Other request" },
      { ...messages[1], id: "anchor-b", subagentAnchor: { taskId: "task-b", callId: "call-1" } },
      { ...messages[2], id: "answer-b", content: "Other answer" },
    ];
    view.rerender(layout({ sessionKey: "websocket:b", threadMessages: otherMessages }));
    const other = await screen.findByRole("region", { name: "Subtasks" });
    expect(summary(other)).toHaveAttribute("aria-expanded", "false");
    await user.click(summary(other));
    expect(within(other).getByRole("button", { name: "Other check Completed 4s" })).toBeVisible();
    expectBefore(screen.getByText("Other request"), other);
    expectBefore(other, screen.getByText("Other answer"));
    view.rerender(layout());
    const restored = await screen.findByRole("region", { name: "Subtasks" });
    expect(summary(restored)).toHaveAttribute("aria-expanded", "false");
    await user.click(summary(restored));
    expect(within(restored).getByRole("button", { name: "Config check Completed 4s" })).toBeVisible();
  });

  it("places multiple independent anchors at their exact transcript positions", async () => {
    vi.mocked(fetch).mockImplementation(async () => response([task(), task({ task_id: "second", label: "Second check" })]));
    const user = userEvent.setup();
    render(layout({ threadMessages: [...messages, { ...messages[1], id: "anchor-second", subagentAnchor: { taskId: "second", callId: "call-1" } },
      { ...messages[2], id: "answer-second", content: "Second answer" }] }));
    const archives = await screen.findAllByRole("region", { name: "Subtasks" });
    expect(archives).toHaveLength(2);
    expectBefore(screen.getByText("Inspect config"), archives[0]);
    expectBefore(archives[0], screen.getByText("Main answer"));
    expectBefore(screen.getByText("Main answer"), archives[1]);
    expectBefore(archives[1], screen.getByText("Second answer"));
    await user.click(summary(archives[0]));
    expect(summary(archives[1])).toHaveAttribute("aria-expanded", "false");
    await user.click(summary(archives[1]));
    expect(within(archives[0]).getByRole("button", { name: "Config check Completed 4s" })).toBeVisible();
    expect(within(archives[1]).getByRole("button", { name: "Second check Completed 4s" })).toBeVisible();
  });

  it("queries stable anchor task IDs after the prompt display ID changes on replay", async () => {
    const user = userEvent.setup();
    const view = render(layout({ liveEvents: false, historyEnabled: true }));
    let archive = await screen.findByRole("region", { name: "Subtasks" });
    await user.click(summary(archive));
    view.unmount();
    render(layout({ threadMessages: [{ ...messages[0], id: "persisted-projection-42" }, messages[1], messages[2]], liveEvents: false, historyEnabled: true }));
    archive = await screen.findByRole("region", { name: "Subtasks" });
    await user.click(summary(archive));
    expect(within(archive).getByRole("button", { name: "Config check Completed 4s" })).toBeVisible();
    const queries = vi.mocked(fetch).mock.calls.map(([url]) => new URL(String(url), "http://localhost").searchParams);
    expect(queries.some((query) => query.getAll("task_id").includes("task-1"))).toBe(true);
    expect(queries.every((query) => !query.has("message_id") && !query.has("turn_id"))).toBe(true);
  });

  it("loads older tasks only when their history page is loaded, and never treats a cached page as unlinked", async () => {
    const older = task({ task_id: "older", label: "Earlier check", origin_turn_id: "older-turn", origin_message_id: "older-prompt" });
    const active = task({ task_id: "active", label: "Live check", state: "running", completed_at: null,
      origin_message_id: "different-prompt", origin_turn_id: "different-turn" });
    vi.mocked(fetch).mockImplementation(async (input) => {
      const query = new URL(String(input), "http://localhost").searchParams;
      return response(query.getAll("task_id").includes("older") ? [active, older] : [active]);
    });
    const user = userEvent.setup();
    const view = render(layout());
    expect(await screen.findByTestId("subagent-task-dock-trigger")).toHaveTextContent("Running: 1");
    expect(screen.queryByRole("region", { name: "Other tasks" })).not.toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.every(([url]) => !String(url).includes("older"))).toBe(true);

    const olderMessages: UIMessage[] = [
      { id: "older-prompt", role: "user", content: "Inspect earlier work", turnId: "older-turn", createdAt: 99_000 },
      { ...messages[1], id: "older-anchor", subagentAnchor: { taskId: "older", callId: "call-1" } },
      ...messages,
    ];
    view.rerender(layout({ threadMessages: olderMessages }));
    const linked = await screen.findByRole("region", { name: "Subtasks" });
    expectBefore(screen.getByText("Inspect earlier work"), linked);
    await user.click(summary(linked));
    expect(within(linked).getByRole("button", { name: "Earlier check Completed 4s" })).toBeVisible();

    view.rerender(layout());
    expect(screen.queryByRole("region", { name: "Other tasks" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Subtasks" })).not.toBeInTheDocument();
    expect(screen.getByTestId("subagent-task-dock-trigger")).toHaveTextContent("Running: 1");
  });

  it("ignores a late response from a history page that was left", async () => {
    const older: UIMessage[] = [{ id: "older-prompt", role: "user", content: "Older request", turnId: "older-turn", createdAt: 99_000 }, { ...messages[1], id: "older-anchor", subagentAnchor: { taskId: "older", callId: "call-1" } }];
    let finishOlder!: (value: Response) => void;
    vi.mocked(fetch).mockImplementationOnce(() => new Promise((resolve) => { finishOlder = resolve; }));
    vi.mocked(fetch).mockImplementation(async () => response([]));
    const view = render(layout({ threadMessages: older }));
    await waitFor(() => expect(finishOlder).toBeDefined());
    view.rerender(layout());
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThan(1));
    await act(async () => { finishOlder(response([task({ task_id: "older", origin_message_id: "older-prompt", origin_turn_id: "older-turn" })])); });
    view.rerender(layout({ threadMessages: older }));
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThan(2));
    expect(screen.queryByRole("region", { name: "Subtasks" })).not.toBeInTheDocument();
  });

  it("yields reading control before expanding and keeps the archive open when its prompt display id changes", async () => {
    const user = userEvent.setup();
    const onActivityToggle = vi.fn(() => {
      expect(summary(screen.getByRole("region", { name: "Subtasks" }))).toHaveAttribute("aria-expanded", "false");
    });
    const view = render(layout({ onActivityToggle }));
    const archive = await screen.findByRole("region", { name: "Subtasks" });
    await user.click(summary(archive));
    expect(onActivityToggle).toHaveBeenCalledTimes(1);
    expect(summary(archive)).toHaveAttribute("data-thread-disclosure");
    view.rerender(layout({ threadMessages: [{ ...messages[0], id: "canonical-input" }, messages[1]], onActivityToggle }));
    const replayed = screen.getByRole("region", { name: "Subtasks" });
    expect(summary(replayed)).toHaveAttribute("aria-expanded", "true");
    expect(within(replayed).getByRole("button", { name: "Config check Completed 4s" })).toBeVisible();
  });

  it("preserves independent disclosures through task outcomes, history prepends and Activity preference changes", async () => {
    act(() => { writeLocalPreferences({ ...DEFAULT_LOCAL_PREFS, activityMode: "expanded" }); });
    vi.mocked(fetch).mockImplementation(async () => response([task(), task({ task_id: "second", label: "Second check", state: "running", completed_at: null })]));
    const user = userEvent.setup();
    const threadMessages: UIMessage[] = [...messages, { ...messages[1], id: "second-anchor", subagentAnchor: { taskId: "second", callId: "call-1" } }];
    const view = render(layout({ threadMessages }));
    const first = await screen.findByRole("region", { name: "Subtasks" });
    await user.click(summary(first));
    act(() => { writeLocalPreferences(DEFAULT_LOCAL_PREFS); });
    emitTask(task({ task_id: "second", label: "Second check", revision: 2, state: "error", error: "Other work failed" }));
    const archives = await screen.findAllByRole("region", { name: "Subtasks" });
    expect(summary(archives[0])).toHaveAttribute("aria-expanded", "true");
    expect(summary(archives[1])).toHaveAttribute("aria-expanded", "false");
    await user.click(summary(archives[1]));
    view.rerender(layout({ threadMessages: [{ id: "prepended", role: "user", content: "Earlier request", turnId: "older", createdAt: 90_000 }, ...threadMessages] }));
    const retained = screen.getAllByRole("region", { name: "Subtasks" });
    expect(summary(retained[0])).toHaveAttribute("aria-expanded", "true");
    expect(summary(retained[1])).toHaveAttribute("aria-expanded", "true");
    expect(within(retained[0]).getByRole("button", { name: "Config check Completed 4s" })).toBeVisible();
    expect(within(retained[1]).getByRole("button", { name: "Second check Failed 4s" })).toBeVisible();
    await user.click(summary(retained[0]));
    act(() => { writeLocalPreferences({ ...DEFAULT_LOCAL_PREFS, activityMode: "expanded" }); });
    expect(summary(retained[0])).toHaveAttribute("aria-expanded", "false");
    expect(summary(retained[1])).toHaveAttribute("aria-expanded", "true");
  });
});
