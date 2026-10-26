import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { preloadMarkdownText } from "@/components/MarkdownText";
import { SubagentTasksProvider } from "@/components/thread/SubagentTasks";
import { SubagentTaskDock } from "@/components/thread/SubagentTaskDock";
import { SubagentThreadMessages } from "@/components/thread/SubagentTaskResults";
import { buildDisplayUnits, unitKeysForDisplay } from "@/components/thread/ThreadMessages";
import { ThreadVisibilityContext } from "@/hooks/useThreadVisibility";
import { setAppLanguage } from "@/i18n";
import { DEFAULT_LOCAL_PREFS, LOCAL_PREFS_STORAGE_KEY, writeLocalPreferences } from "@/lib/local-preferences";
import { latestSubagentInputKey } from "@/lib/subagent-tasks";
import type { ConnectionStatus, InboundEvent, SubagentTaskSnapshot, UIMessage } from "@/lib/types";

const requestMutation = vi.fn();
const chatHandlers = new Map<string, Set<(event: InboundEvent) => void>>();
const statusHandlers = new Set<(status: ConnectionStatus) => void>();
const client = {
  requestMutation,
  onChat: vi.fn((chatId: string, handler: (event: InboundEvent) => void) => {
    const handlers = chatHandlers.get(chatId) ?? new Set();
    chatHandlers.set(chatId, handlers);
    handlers.add(handler);
    return () => { handlers.delete(handler); };
  }),
  onStatus: vi.fn((handler: (status: ConnectionStatus) => void) => {
    statusHandlers.add(handler);
    handler("open");
    return () => { statusHandlers.delete(handler); };
  }),
};
function emitTask(snapshot: SubagentTaskSnapshot, chatId = "a") {
  act(() => { chatHandlers.get(chatId)?.forEach((handler) => handler({ event: "subagent_task", chat_id: chatId, task: snapshot })); });
}
const messages: UIMessage[] = [
  { id: "prompt-a", role: "user", content: "Inspect config", turnId: "turn-a", createdAt: 100_000 },
  { id: "answer-a", role: "assistant", content: "Main answer", turnId: "turn-a", createdAt: 101_000 },
];

function task(overrides: Partial<SubagentTaskSnapshot> = {}): SubagentTaskSnapshot {
  return {
    task_id: "task-1", revision: 1, label: "Config check", task_description: "Check configuration values",
    state: "running", phase: "awaiting_model", elapsed_seconds: 2, iteration: 1,
    tool_events: [], usage: null, receipts: {}, result: null, partial: false,
    stop_reason: null, error: null, origin_turn_id: "turn-a", origin_message_id: null,
    created_at: 100, completed_at: null, ...overrides,
  };
}
function response(tasks: SubagentTaskSnapshot[]): Response {
  return new Response(JSON.stringify({ tasks }), { headers: { "content-type": "application/json" } });
}
function childThread(answer: string, active = true): Response {
  return new Response(JSON.stringify({ schemaVersion: 3, projection: "events", active_turn_id: active ? "child-turn" : null,
    events: [
      { event: "user_message", chat_id: "task-1", starts_turn: true, projection_id: "child-prompt", turn_id: "child-turn", text: "Inspect configuration in the child session", created_at_ms: 100000 },
      { event: "message", chat_id: "task-1", projection_id: "child-tool", turn_id: "child-turn", kind: "tool_hint", text: 'read_file({"path":"config.py"})',
        tool_events: [{ call_id: "read-1", name: "read_file", arguments: { path: "config.py" }, phase: "end", result: "configuration values" }] },
      { event: "message", chat_id: "task-1", projection_id: "child-answer", turn_id: "child-turn", text: answer },
    ],
  }), { headers: { "content-type": "application/json" } });
}
interface LayoutOptions {
  enabled?: boolean;
  liveEvents?: boolean;
  historyEnabled?: boolean;
  sessionKey?: string;
  visible?: boolean;
  active?: boolean;
  inputKey?: string | null;
  threadMessages?: UIMessage[];
}
function layout({ enabled = true, liveEvents = true, historyEnabled = false, sessionKey = "websocket:a", visible = true, active = true, inputKey = null, threadMessages = messages }: LayoutOptions = {}) {
  return <ThreadVisibilityContext.Provider value={visible}>
    <SubagentTasksProvider client={client} sessionKey={sessionKey} token="tok" enabled={enabled} liveEvents={liveEvents} historyEnabled={historyEnabled} active={active}>
      <div data-testid="messages"><SubagentThreadMessages messages={threadMessages} /></div>
      <div data-testid="composer" className="thread-composer-stack"><SubagentTaskDock inputKey={inputKey ?? latestSubagentInputKey(threadMessages)} /><textarea aria-label="Message" /></div>
    </SubagentTasksProvider>
  </ThreadVisibilityContext.Provider>;
}
async function openTaskList(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByTestId("subagent-task-dock-trigger"));
  return screen.getByTestId("subagent-task-tree");
}
async function openArchive(user: ReturnType<typeof userEvent.setup>, name = "Subtasks") {
  const archive = await within(screen.getByTestId("messages")).findByRole("region", { name });
  const summary = within(archive).getByRole("button", { name: new RegExp(name) });
  if (summary.getAttribute("aria-expanded") !== "true") await user.click(summary);
  return archive;
}
function taskIds(container: HTMLElement) {
  return [...container.querySelectorAll("[data-subagent-id]")].map(row => row.getAttribute("data-subagent-id"));
}

describe("session-owned task UI", () => {
  beforeEach(async () => {
    localStorage.removeItem(LOCAL_PREFS_STORAGE_KEY);
    await setAppLanguage("en");
    requestMutation.mockReset();
    client.onChat.mockClear();
    client.onStatus.mockClear();
    chatHandlers.clear();
    statusHandlers.clear();
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => response([task()])));
  });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.removeItem(LOCAL_PREFS_STORAGE_KEY); });

  it("keeps active work in one composer entry without mixing in a large terminal archive", async () => {
    const older = Array.from({ length: 40 }, (_, index) => task({
      task_id: `older-${index}`, label: `Archived check ${index}`, created_at: index + 1,
      state: "done", completed_at: 90, result: `Saved finding ${index}`,
    }));
    vi.mocked(fetch).mockImplementation(async () => response([
      ...older, task(),
      task({ task_id: "legacy", label: "Earlier check", created_at: 91, origin_turn_id: null, origin_message_id: "missing-prompt", state: "done", completed_at: 92, result: "Saved result" }),
    ]));
    const user = userEvent.setup();
    render(layout());
    const trigger = await screen.findByTestId("subagent-task-dock-trigger");
    expect(fetch).toHaveBeenCalledWith("/api/sessions/websocket%3Aa/subagents", expect.any(Object));
    expect(screen.getAllByTestId("subagent-task-dock-trigger")).toEqual([trigger]);
    expect(screen.getByTestId("composer")).toContainElement(trigger);
    expect(trigger).toHaveTextContent("Running: 1");
    expect(trigger).not.toHaveTextContent("Completed:");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("subagent-task-tree")).not.toBeInTheDocument();
    expect(screen.getByTestId("messages")).toHaveTextContent("Inspect config");
    expect(screen.getByTestId("messages")).toHaveTextContent("Main answer");
    expect(screen.getByTestId("messages")).not.toHaveTextContent("Config check");
    expect(screen.getByTestId("messages")).not.toHaveTextContent("Saved result");

    const list = await openTaskList(user);
    expect(within(list).getByRole("button", { name: /Config check Running/ })).toBeVisible();
    expect(taskIds(list)).toEqual(["task-1"]);
    expect(within(list).queryByText(/Archived check|Earlier check|Saved finding|Saved result/)).not.toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByTestId("subagent-task-tree")).not.toBeInTheDocument();
    const archive = await openArchive(user);
    expect(taskIds(archive)).toEqual(older.map(saved => saved.task_id));
    expect(within(archive).queryByRole("button", { name: /Config check Running/ })).not.toBeInTheDocument();
    const other = await openArchive(user, "Other tasks");
    await user.click(within(other).getByRole("button", { name: /Earlier check Completed/ }));
    expect(within(screen.getByRole("dialog", { name: "Earlier check" })).getByText("Saved result")).toBeVisible();
    expect(requestMutation).not.toHaveBeenCalled();
  });

  it("keeps collapsed task controls out of Tab order and allows typing without closing the drawer", async () => {
    const user = userEvent.setup();
    render(layout());
    const trigger = await screen.findByTestId("subagent-task-dock-trigger");
    const input = screen.getByRole("textbox", { name: "Message" });
    expect(trigger).toHaveAccessibleName("Subtasks · Running: 1");
    act(() => { trigger.focus(); });
    await user.tab();
    expect(input).toHaveFocus();
    await user.tab({ shift: true });
    expect(trigger).toHaveFocus();
    await user.keyboard("{Enter}");
    const list = screen.getByTestId("subagent-task-tree");
    await user.tab();
    expect(within(list).getByRole("button", { name: /Config check Running/ })).toHaveFocus();
    await user.click(input);
    await user.type(input, "Keep working in the conversation");
    expect(input).toHaveValue("Keep working in the conversation");
    const cancelComposition = new KeyboardEvent("keydown", { key: "Escape", isComposing: true, bubbles: true, cancelable: true });
    fireEvent(input, cancelComposition);
    expect(cancelComposition.defaultPrevented).toBe(false);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    await user.click(trigger);
    expect(trigger).toHaveFocus();
    expect(screen.queryByTestId("subagent-task-tree")).not.toBeInTheDocument();
    await user.tab();
    expect(input).toHaveFocus();
    expect(requestMutation).not.toHaveBeenCalled();
  });

  it("removes a finished task from the closed dock while a sibling is still active", async () => {
    vi.mocked(fetch).mockImplementation(async () => response([
      task(), task({ task_id: "sibling", label: "Waiting check", state: "queued", created_at: 101 }),
    ]));
    const user = userEvent.setup();
    render(layout());
    const trigger = await screen.findByTestId("subagent-task-dock-trigger");
    expect(trigger).toHaveTextContent("Running: 2");
    emitTask(task({ revision: 2, state: "done", completed_at: 102, result: "Verified" }));
    expect(trigger).toHaveTextContent("Running: 1");
    expect(trigger).not.toHaveTextContent("Completed:");
    const list = await openTaskList(user);
    expect(taskIds(list)).toEqual(["sibling"]);
    expect(within(list).getByRole("button", { name: /Waiting check Queued/ })).toBeVisible();
    expect(within(list).queryByRole("button", { name: /Config check Completed/ })).not.toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(trigger).toHaveFocus());
    const archive = await openArchive(user);
    expect(within(archive).getByRole("button", { name: /Config check Completed/ })).toBeVisible();
    expect(taskIds(archive)).toEqual(["task-1"]);
    expect(requestMutation).not.toHaveBeenCalled();
  });

  it.each([
    { state: "done", status: "Completed", summary: "Completed: 1", error: null },
    { state: "error", status: "Failed", summary: "Finished: 1", error: "Cannot read the file" },
    { state: "cancelled", status: "Cancelled", summary: "Finished: 1", error: null },
  ] as const)("expires observed $state feedback after four seconds without inventing success", async ({ state, status, summary, error }) => {
    vi.useFakeTimers();
    render(layout());
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByTestId("subagent-task-dock-trigger")).toHaveTextContent("Running: 1");
    emitTask(task({ revision: 2, state, error, completed_at: 102, result: state === "done" ? "Verified" : null }));
    const trigger = screen.getByTestId("subagent-task-dock-trigger");
    expect(trigger).toHaveTextContent(summary);
    if (state !== "done") expect(trigger).not.toHaveTextContent("Completed:");
    if (state === "error") expect(trigger).toHaveTextContent("Review needed: 1");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("subagent-task-tree")).not.toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(3999); });
    expect(trigger).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(screen.queryByTestId("subagent-task-dock")).not.toBeInTheDocument();
    const archive = screen.getByRole("region", { name: "Subtasks" });
    fireEvent.click(within(archive).getByRole("button", { name: /Subtasks/ }));
    expect(within(archive).getByRole("button", { name: new RegExp(`Config check ${status}`) })).toBeVisible();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(requestMutation).not.toHaveBeenCalled();
  });

  it.each(["hover", "focus", "detail"] as const)("pauses completion feedback expiry during %s interaction", async interaction => {
    vi.useFakeTimers();
    render(layout());
    await act(async () => { await Promise.resolve(); });
    emitTask(task({ revision: 2, state: "done", completed_at: 102, result: "Verified" }));
    const trigger = screen.getByTestId("subagent-task-dock-trigger");
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    if (interaction === "hover") fireEvent.pointerEnter(trigger, { pointerType: "mouse" });
    else if (interaction === "focus") act(() => { trigger.focus(); });
    else {
      const archive = screen.getByRole("region", { name: "Subtasks" });
      fireEvent.click(within(archive).getByRole("button", { name: /Subtasks/ }));
      fireEvent.click(within(archive).getByRole("button", { name: /Config check Completed/ }));
      expect(within(screen.getByRole("dialog", { name: "Config check" })).getByText("Verified")).toBeVisible();
    }
    await act(async () => { await vi.advanceTimersByTimeAsync(8000); });
    expect(trigger).toBeInTheDocument();
    if (interaction === "hover") fireEvent.pointerLeave(trigger, { pointerType: "mouse" });
    else if (interaction === "focus") act(() => { screen.getByRole("textbox", { name: "Message" }).focus(); });
    else fireEvent.keyDown(screen.getByRole("dialog", { name: "Config check" }), { key: "Escape" });
    await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
    expect(screen.queryByTestId("subagent-task-dock")).not.toBeInTheDocument();
    expect(requestMutation).not.toHaveBeenCalled();
  });

  it("retains completed rows while reading and appends newly active work without forcing the list closed", async () => {
    vi.useFakeTimers();
    render(layout());
    await act(async () => { await Promise.resolve(); });
    fireEvent.click(screen.getByTestId("subagent-task-dock-trigger"));
    const list = screen.getByTestId("subagent-task-tree");
    const row = within(list).getByRole("button", { name: /Config check Running/ });
    emitTask(task({ revision: 2, state: "done", completed_at: 102, result: "Verified" }));
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(list).toBeVisible();
    expect(within(list).getByRole("button", { name: /Config check Completed/ })).toBe(row);
    emitTask(task({ task_id: "sibling", label: "Follow-up check", state: "queued", created_at: 103 }));
    expect(taskIds(list)).toEqual(["task-1", "sibling"]);
    expect(within(list).getByRole("button", { name: /Follow-up check Queued/ })).toBeVisible();
    emitTask(task({ task_id: "sibling", revision: 2, label: "Follow-up check", state: "cancelled", created_at: 103, completed_at: 104 }));
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(within(list).getByRole("button", { name: /Config check Completed/ })).toBe(row);
    expect(within(list).getByRole("button", { name: /Follow-up check Cancelled/ })).toBeVisible();
    fireEvent.keyDown(list, { key: "Escape" });
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(screen.queryByTestId("subagent-task-tree")).not.toBeInTheDocument();
    expect(screen.queryByTestId("subagent-task-dock")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveFocus();
    const archive = screen.getByRole("region", { name: "Subtasks" });
    fireEvent.click(within(archive).getByRole("button", { name: /Subtasks/ }));
    expect(taskIds(archive)).toEqual(["task-1", "sibling"]);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(requestMutation).not.toHaveBeenCalled();
  });

  it("appends a reconnect's earlier-created active task without moving an open row", async () => {
    vi.mocked(fetch).mockImplementation(async () => response([task({ created_at: 102 })]));
    const user = userEvent.setup();
    render(layout());
    const list = await openTaskList(user);
    const row = within(list).getByRole("button", { name: /Config check Running/ });
    vi.mocked(fetch).mockImplementation(async () => response([
      task({ task_id: "earlier", label: "Earlier check", created_at: 100 }), task({ created_at: 102 }),
    ]));
    fireEvent(window, new Event("focus"));
    await within(list).findByRole("button", { name: /Earlier check Running/ });
    expect(taskIds(list)).toEqual(["task-1", "earlier"]);
    expect(within(list).getByRole("button", { name: /Config check Running/ })).toBe(row);
  });

  it("keeps completion feedback when the same input is replayed with a different display id", async () => {
    const view = render(layout());
    await screen.findByTestId("subagent-task-dock-trigger");
    emitTask(task({ revision: 2, state: "done", completed_at: 102, result: "Verified" }));
    expect(screen.getByTestId("subagent-task-dock-trigger")).toHaveTextContent("Completed: 1");
    view.rerender(layout({ threadMessages: [{ ...messages[0], id: "canonical-input" }, messages[1]] }));
    expect(screen.getByTestId("subagent-task-dock-trigger")).toHaveTextContent("Completed: 1");
  });

  it("preserves an open reading view across new input, then reopens with only cross-turn active work", async () => {
    vi.mocked(fetch).mockImplementation(async () => response([
      task(), task({ task_id: "cross-turn", label: "Cross-turn check", state: "stopping", created_at: 101 }),
      task({ task_id: "old", label: "Old check", state: "cancelled", created_at: 90, completed_at: 91 }),
    ]));
    const user = userEvent.setup();
    const view = render(layout({ inputKey: "prompt-a" }));
    const list = await openTaskList(user);
    const crossTurn = within(list).getByRole("button", { name: /Cross-turn check Stopping/ });
    expect(taskIds(list)).toEqual(["task-1", "cross-turn"]);
    emitTask(task({ revision: 2, state: "done", completed_at: 102, result: "Earlier finding" }));
    expect(within(list).getByRole("button", { name: /Config check Completed/ })).toBeVisible();
    const nextMessages: UIMessage[] = [...messages, { id: "prompt-b", role: "user", content: "Inspect the next setting", turnId: "turn-b", createdAt: 103_000 }];
    view.rerender(layout({ inputKey: "prompt-b", threadMessages: nextMessages }));
    expect(screen.getByTestId("subagent-task-tree")).toBe(list);
    expect(taskIds(list)).toEqual(["task-1", "cross-turn"]);
    expect(within(list).getByRole("button", { name: /Cross-turn check Stopping/ })).toBe(crossTurn);
    expect(screen.getByTestId("subagent-task-dock-trigger")).toHaveTextContent("Running: 1");
    emitTask(task({ task_id: "next", label: "Next check", created_at: 104, origin_turn_id: "turn-b", origin_message_id: "prompt-b" }));
    expect(taskIds(list)).toEqual(["task-1", "cross-turn", "next"]);
    await user.keyboard("{Escape}");
    expect(screen.getByTestId("subagent-task-dock-trigger")).not.toHaveTextContent("Completed:");
    const reopened = await openTaskList(user);
    expect(taskIds(reopened)).toEqual(["cross-turn", "next"]);
    await user.keyboard("{Escape}");
    const archive = await openArchive(user);
    expect(taskIds(archive)).toEqual(["old", "task-1"]);
    expect(within(archive).getByRole("button", { name: /Config check Completed/ })).toBeVisible();
    expect(within(archive).queryByRole("button", { name: /Cross-turn check|Next check/ })).not.toBeInTheDocument();
    expect(requestMutation).not.toHaveBeenCalled();
  });

  it("clears previous-turn completion feedback on new input without deleting its archive", async () => {
    const user = userEvent.setup();
    const view = render(layout({ inputKey: "prompt-a" }));
    await screen.findByTestId("subagent-task-dock-trigger");
    emitTask(task({ revision: 2, state: "done", completed_at: 102, result: "Earlier finding" }));
    expect(screen.getByTestId("subagent-task-dock-trigger")).toHaveTextContent("Completed: 1");
    view.rerender(layout({ inputKey: "prompt-b" }));
    expect(screen.queryByTestId("subagent-task-dock")).not.toBeInTheDocument();
    const archive = await openArchive(user);
    expect(within(archive).getByRole("button", { name: /Config check Completed/ })).toBeVisible();
    emitTask(task({ task_id: "next", label: "Next check", created_at: 103 }));
    expect(screen.getByTestId("subagent-task-dock-trigger")).toHaveTextContent("Running: 1");
    const list = await openTaskList(user);
    expect(taskIds(list)).toEqual(["next"]);
    expect(requestMutation).not.toHaveBeenCalled();
  });

  it("treats an initial terminal-only snapshot and a cold refresh as history, never completion feedback", async () => {
    vi.mocked(fetch).mockImplementation(async () => response([
      task({ state: "done", completed_at: 102, result: "Saved finding" }),
      task({ task_id: "failed", label: "Failed check", state: "error", created_at: 101, completed_at: 103, error: "Saved failure" }),
      task({ task_id: "cancelled", label: "Cancelled check", state: "cancelled", created_at: 102, completed_at: 104 }),
    ]));
    const user = userEvent.setup();
    const view = render(layout());
    const archive = await screen.findByRole("region", { name: "Subtasks" });
    expect(within(archive).getByRole("button", { name: /Subtasks/ })).toHaveAttribute("aria-expanded", "false");
    expect(within(archive).queryByRole("button", { name: /Config check Completed/ })).not.toBeInTheDocument();
    expect(screen.queryByTestId("subagent-task-dock")).not.toBeInTheDocument();
    expect(screen.queryByTestId("subagent-task-tree")).not.toBeInTheDocument();
    await openArchive(user);
    expect(taskIds(archive)).toEqual(["task-1", "failed", "cancelled"]);
    await user.click(within(archive).getByRole("button", { name: /Config check Completed/ }));
    expect(within(screen.getByRole("dialog", { name: "Config check" })).getByText("Saved finding")).toBeVisible();
    view.unmount();
    render(layout());
    const restored = await screen.findByRole("region", { name: "Subtasks" });
    expect(within(restored).getByRole("button", { name: /Subtasks/ })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("subagent-task-dock")).not.toBeInTheDocument();
    vi.useFakeTimers();
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(screen.queryByTestId("subagent-task-dock")).not.toBeInTheDocument();
    expect(restored).toBeVisible();
    expect(requestMutation).not.toHaveBeenCalled();
  });

  it("keeps a completed task readable until the list is closed, then focuses the composer and archives it", async () => {
    const user = userEvent.setup();
    render(layout());
    const trigger = await screen.findByTestId("subagent-task-dock-trigger");
    expect(screen.getByTestId("composer")).toContainElement(trigger);
    expect(screen.getByTestId("messages")).not.toContainElement(trigger);
    expect(trigger).toHaveTextContent("Running: 1");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    await user.click(trigger);
    const list = screen.getByTestId("subagent-task-tree");
    const row = within(list).getByRole("button", { name: /Config check Running/ });
    expect(row.querySelectorAll(".loading-ring-arc")).toHaveLength(1);
    await user.click(row);
    expect(screen.getByRole("dialog", { name: "Config check" })).toBeVisible();
    emitTask(task({ revision: 2, state: "done", completed_at: 102, result: "Verified the configuration" }));
    expect(screen.getByRole("dialog", { name: "Config check" })).toBeVisible();
    await user.keyboard("{Escape}");
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(within(list).getByRole("button", { name: /Config check Completed/ })).toBe(row);
    expect(row.querySelectorAll("svg")).toHaveLength(0);
    expect(row.firstElementChild?.firstElementChild).toHaveAttribute("aria-hidden", "true");
    await waitFor(() => expect(row).toHaveFocus());
    expect(await within(list).findByText("Verified the configuration")).toBeVisible();
    await user.keyboard("{Escape}");
    expect(screen.queryByTestId("subagent-task-tree")).not.toBeInTheDocument();
    expect(screen.queryByTestId("subagent-task-dock-trigger")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Message" })).toHaveFocus());
    const archive = await openArchive(user);
    const archivedRow = within(archive).getByRole("button", { name: /Config check Completed/ });
    await user.click(archivedRow);
    expect(within(screen.getByRole("dialog", { name: "Config check" })).getByText("Verified the configuration")).toBeVisible();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(archivedRow).toHaveFocus());
    expect(requestMutation).not.toHaveBeenCalled();
  });

  it("renders the full result as Markdown in the drawer and keeps task details available", async () => {
    const result = "## Findings\n\n**Verified** the configuration.\n\n" + "Verified the configuration. ".repeat(30)
      + "\n\n[Full evidence](https://example.com/evidence)\n\n[Unsafe link](javascript:alert(1))\n\n```ts\nconst verified = true;\n```\n\nFinal finding after the long result.";
    const user = userEvent.setup();
    render(layout());
    const tree = await openTaskList(user);
    emitTask(task({ revision: 2, state: "done", completed_at: 102, result }));
    expect(await within(tree).findByRole("heading", { name: "Findings", level: 2 })).toBeVisible();
    expect(within(tree).getByText("Verified", { selector: "strong" })).toBeVisible();
    expect(within(tree).getByText("Final finding after the long result.")).toBeVisible();
    const evidence = within(tree).getByRole("link", { name: "Full evidence" });
    expect(evidence).toHaveAttribute("href", "https://example.com/evidence");
    expect(evidence).toHaveAttribute("rel", "noreferrer noopener");
    expect(within(tree).queryByRole("link", { name: "Unsafe link" })).not.toBeInTheDocument();
    expect(tree.querySelector("pre")?.textContent).toContain("const verified = true;");
    await user.click(within(tree).getByRole("button", { name: /Config check Completed/ }));
    expect(await within(screen.getByRole("dialog", { name: "Config check" })).findByRole("link", { name: /Full evidence/ })).toHaveAttribute("href", "https://example.com/evidence");
  });

  it("keeps result-owned image portals inside the drawer interaction boundary", async () => {
    await preloadMarkdownText();
    const user = userEvent.setup();
    render(layout());
    const tree = await openTaskList(user);
    emitTask(task({ revision: 2, state: "done", completed_at: 102, result: "![Result image](https://example.com/result.png)" }));
    await user.click(await within(tree).findByRole("button", { name: "View image: Result image" }));
    const viewer = screen.getByRole("dialog", { name: "Result image" });
    fireEvent.pointerDown(within(viewer).getByRole("img", { name: "Result image" }));
    expect(viewer).toBeInTheDocument();
    expect(screen.getByTestId("subagent-task-dock-trigger")).toHaveAttribute("aria-expanded", "true");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByTestId("subagent-task-tree")).toBe(tree);
    fireEvent.pointerDown(screen.getByTestId("messages"));
    expect(screen.queryByTestId("subagent-task-dock-trigger")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveFocus();
  });

  it("keeps task order, actual tool activity and cancellation outcomes in the dock", async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockImplementation(async () => response([
      task({ task_id: "queued", label: "Waiting check", state: "queued", created_at: 101 }),
      task({ tool_events: [{ name: "read_file", status: "running" }, { name: "exec", status: "running" }, { name: "web_fetch", status: "error" }] }),
    ]));
    requestMutation.mockResolvedValue(task({ revision: 2, state: "cancelled", completed_at: 102 }));
    render(layout());
    const trigger = await screen.findByTestId("subagent-task-dock-trigger");
    expect(trigger).toHaveTextContent("Running: 2");
    await user.click(trigger);
    const list = screen.getByTestId("subagent-task-tree");
    expect(within(list).getByText("read_file")).toBeVisible();
    expect(within(list).getByText("exec")).toBeVisible();
    const runningTask = within(list).getByRole("button", { name: /Config check Running/ }).closest("li")!;
    expect(runningTask.querySelectorAll(".loading-ring-arc")).toHaveLength(1);
    expect(runningTask.querySelector('[data-product-icon="task-error"]')).toHaveClass("text-destructive");
    expect([...list.querySelectorAll("[data-subagent-id]")].map(row => row.getAttribute("data-subagent-id"))).toEqual(["task-1", "queued"]);
    await user.click(within(list).getByRole("button", { name: "Stop Config check" }));
    await within(list).findByRole("button", { name: /Config check Cancelled/ });
    emitTask(task({ task_id: "queued", label: "Waiting check", created_at: 101, revision: 2, state: "error", error: "Cannot read the file", completed_at: 103 }));
    expect(trigger).toHaveTextContent("Finished: 2");
    expect(trigger).toHaveTextContent("Review needed: 1");
    expect(within(list).getByText("Cannot read the file")).toBeVisible();
    expect([...list.querySelectorAll("[data-subagent-id]")].map(row => row.getAttribute("data-subagent-id"))).toEqual(["task-1", "queued"]);
    expect(requestMutation).toHaveBeenCalledTimes(1);
    expect(requestMutation).toHaveBeenCalledWith("subagent.cancel", { session_key: "websocket:a", task_id: "task-1" }, 20_000);
    expect(list).toBeVisible();
    await user.keyboard("{Escape}");
    expect(screen.queryByTestId("subagent-task-dock")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Message" })).toHaveFocus());
    const archive = await openArchive(user);
    expect(within(archive).getByRole("button", { name: /Config check Cancelled/ })).toBeVisible();
    expect(within(archive).getByRole("button", { name: /Waiting check Failed/ })).toBeVisible();
  });

  it.each(["inactive", "hidden", "session"])("closes the task drawer when its scope becomes %s", async change => {
    const user = userEvent.setup();
    const view = render(layout());
    expect(await openTaskList(user)).toBeVisible();
    view.rerender(layout({ active: change !== "inactive", visible: change !== "hidden", sessionKey: change === "session" ? "websocket:b" : "websocket:a" }));
    await waitFor(() => expect(screen.queryByTestId("subagent-task-tree")).not.toBeInTheDocument());
    if (change !== "session") expect(screen.queryByTestId("subagent-task-dock")).not.toBeInTheDocument();
    view.rerender(layout());
    expect(await screen.findByTestId("subagent-task-dock-trigger")).toHaveAttribute("aria-expanded", "false");
    expect(requestMutation).not.toHaveBeenCalled();
  });

  it("applies the browser activity preference to the child chat without auto-opening archived results", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => url.endsWith("/webui-thread")
      ? childThread("Configuration verified", false)
      : response([task({ state: "done", completed_at: 102 })])));
    const user = userEvent.setup();
    const view = render(layout({ historyEnabled: true }));
    const archive = await screen.findByRole("region", { name: "Subtasks" });
    const summary = within(archive).getByRole("button", { name: /Subtasks/ });
    expect(summary).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("subagent-task-dock")).not.toBeInTheDocument();

    act(() => { writeLocalPreferences({ ...DEFAULT_LOCAL_PREFS, activityMode: "expanded" }); });
    expect(summary).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("subagent-task-tree")).not.toBeInTheDocument();
    await openArchive(user);
    await user.click(within(archive).getByRole("button", { name: /Config check Completed/ }));
    const detail = screen.getByRole("dialog", { name: "Config check" });
    expect(await within(detail).findByText("Configuration verified")).toBeVisible();
    expect(within(detail).getByTestId("agent-activity-content")).toBeVisible();
    await user.click(within(detail).getByRole("button", { name: /Collapse activity details/ }));
    expect(within(detail).queryByTestId("agent-activity-content")).not.toBeInTheDocument();

    act(() => { writeLocalPreferences(DEFAULT_LOCAL_PREFS); });
    expect(summary).toHaveAttribute("aria-expanded", "true");
    expect(within(detail).queryByTestId("agent-activity-content")).not.toBeInTheDocument();
    act(() => { writeLocalPreferences({ ...DEFAULT_LOCAL_PREFS, activityMode: "expanded" }); });
    expect(within(detail).getByTestId("agent-activity-content")).toBeVisible();
    view.unmount();

    render(layout({ historyEnabled: true }));
    const restoredArchive = await screen.findByRole("region", { name: "Subtasks" });
    expect(within(restoredArchive).getByRole("button", { name: /Subtasks/ })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("subagent-task-dock")).not.toBeInTheDocument();
    await openArchive(user);
    await user.click(within(restoredArchive).getByRole("button", { name: /Config check Completed/ }));
    expect(await within(screen.getByRole("dialog")).findByTestId("agent-activity-content")).toBeVisible();
  });

  it("renders the child Session in the shared chat view and refreshes it from task events", async () => {
    let completed = false;
    const fetcher = vi.fn(async (url: string) => url.endsWith("/webui-thread")
      ? childThread(completed ? "## Findings\n\n- **Verified** the full session\n\n| Check | Result |\n| --- | --- |\n| Configuration | Passed |" : "Checking the configuration", !completed)
      : response([task()]));
    vi.stubGlobal("fetch", fetcher);
    const user = userEvent.setup();
    const view = render(layout({ historyEnabled: true }));
    const list = await openTaskList(user);
    await user.click(within(list).getByRole("button", { name: /Config check Running/ }));
    const detail = screen.getByRole("dialog", { name: "Config check" });
    expect(await within(detail).findByText("Inspect configuration in the child session")).toBeVisible();
    expect(within(detail).getByText("Checking the configuration")).toBeVisible();
    expect(fetcher).toHaveBeenCalledWith(
      "/api/sessions/websocket%3Aa/subagents/task-1/webui-thread", expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    completed = true;
    emitTask(task({ revision: 2, state: "done", completed_at: 102, result: "Bounded task summary" }));
    expect(await within(detail).findByRole("heading", { name: "Findings" })).toBeVisible();
    expect(within(detail).getByRole("table")).toHaveTextContent("ConfigurationPassed");
    expect(within(detail).getByText("Inspect configuration in the child session")).toBeVisible();
    // Opening and reading details never mutates execution; a fresh view reads the same saved child.
    expect(requestMutation).not.toHaveBeenCalled();
    view.unmount();
    fetcher.mockImplementation(async (url) => url.endsWith("/webui-thread") ? childThread("## Findings\n\nVerified the full session", false)
      : response([task({ revision: 2, state: "done", completed_at: 102 })]));
    render(layout({ historyEnabled: true }));
    const restoredArchive = await openArchive(user);
    expect(screen.queryByTestId("subagent-task-dock")).not.toBeInTheDocument();
    await user.click(within(restoredArchive).getByRole("button", { name: /Config check Completed/ }));
    expect(await within(screen.getByRole("dialog")).findByRole("heading", { name: "Findings" })).toBeVisible();
  });

  it("coalesces history reads and discards an outstanding read when the session changes", async () => {
    let resolveFirst!: (value: Response) => void;
    let resolveOld!: (value: Response) => void;
    let reads = 0;
    const readSignals: AbortSignal[] = [];
    const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
      if (!url.endsWith("/webui-thread")) return response([task()]);
      if (init?.signal) readSignals.push(init.signal);
      reads += 1;
      if (reads === 1) return new Promise<Response>((resolve) => { resolveFirst = resolve; });
      if (reads === 3) return new Promise<Response>((resolve) => { resolveOld = resolve; });
      return childThread("Latest child response", false);
    });
    vi.stubGlobal("fetch", fetcher);
    const user = userEvent.setup();
    const view = render(layout({ historyEnabled: true }));
    const list = await openTaskList(user);
    await user.click(within(list).getByRole("button", { name: /Config check Running/ }));
    await waitFor(() => expect(reads).toBe(1));
    emitTask(task({ revision: 2, iteration: 2 }));
    emitTask(task({ revision: 3, iteration: 3 }));
    expect(reads).toBe(1);
    await act(async () => { resolveFirst(childThread("Earlier checkpoint")); });
    expect(await within(screen.getByRole("dialog")).findByText("Latest child response")).toBeVisible();
    expect(reads).toBe(2);
    emitTask(task({ revision: 4, iteration: 4 }));
    await waitFor(() => expect(reads).toBe(3));
    const oldSignal = readSignals.at(-1);
    view.rerender(layout({ historyEnabled: true, sessionKey: "websocket:b" }));
    expect(await screen.findByTestId("subagent-task-dock-trigger")).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(oldSignal?.aborted).toBe(true);
    await act(async () => { resolveOld(childThread("Old session response")); });
    const nextList = await openTaskList(user);
    await user.click(within(nextList).getByRole("button", { name: /Config check Running/ }));
    const nextDetail = screen.getByRole("dialog");
    expect(await within(nextDetail).findByText("Latest child response")).toBeVisible();
    expect(within(nextDetail).queryByText("Old session response")).not.toBeInTheDocument();
  });

  it("shares history loading, actual failure details and keyboard retry with the main thread", async () => {
    let rejectRead!: (reason: Error) => void;
    let resolveRead!: (value: Response) => void;
    let reads = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (!url.endsWith("/webui-thread")) return response([task()]);
      reads += 1;
      return new Promise<Response>((resolve, reject) => { resolveRead = resolve; rejectRead = reject; });
    }));
    const user = userEvent.setup();
    render(layout({ historyEnabled: true }));
    const list = await openTaskList(user);
    await user.click(within(list).getByRole("button", { name: /Config check Running/ }));
    const detail = screen.getByRole("dialog");
    const loading = within(detail).getByRole("status");
    expect(loading.querySelectorAll(".thread-history-blocks > span")).toHaveLength(9);
    expect(loading.closest(".thread-history-status")).toHaveAttribute("data-state", "loading");
    await act(async () => { rejectRead(new Error("offline")); });
    const retry = await within(detail).findByRole("button", { name: "Loading failed. Retry" });
    expect(retry.closest(".thread-history-status")).toHaveAttribute("data-state", "error");
    expect(retry.querySelectorAll(".thread-history-blocks > span")).toHaveLength(9);
    act(() => { retry.focus(); });
    expect(screen.getByRole("tooltip")).toHaveTextContent("offline");
    await user.keyboard("{Enter}");
    expect(reads).toBe(2);
    expect(within(detail).getByRole("status").closest(".thread-history-status")).toHaveAttribute("data-state", "loading");
    await act(async () => { resolveRead(childThread("Recovered child response")); });
    expect(await within(detail).findByText("Recovered child response")).toBeVisible();
    expect(within(detail).queryByRole("status")).not.toBeInTheDocument();
  });

  it("keeps the dock list open through an HTTP completion and restores saved results only in history", async () => {
    const user = userEvent.setup();
    const view = render(layout());
    const list = await openTaskList(user);
    const runningRow = within(list).getByRole("button", { name: /Config check Running/ });
    const trigger = screen.getByTestId("subagent-task-dock-trigger");
    vi.mocked(fetch).mockImplementation(async () => response([task({ revision: 2, state: "done", result: "Verified", completed_at: 102 })]));
    fireEvent(window, new Event("focus"));
    const row = await within(list).findByRole("button", { name: /Config check Completed/ });
    expect(row).toBe(runningRow);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(within(list).getByText("Verified")).toBeVisible();
    expect(screen.getByTestId("messages")).not.toContainElement(row);
    expect(screen.getByTestId("messages")).not.toHaveTextContent("Verified");
    view.unmount();

    render(layout());
    const restoredArchive = await openArchive(user);
    expect(screen.queryByTestId("subagent-task-dock-trigger")).not.toBeInTheDocument();
    expect(screen.queryByTestId("subagent-task-tree")).not.toBeInTheDocument();
    await user.click(within(restoredArchive).getByRole("button", { name: /Config check Completed/ }));
    expect(within(screen.getByRole("dialog", { name: "Config check" })).getByText("Verified")).toBeVisible();
    expect(requestMutation).not.toHaveBeenCalled();
  });

  it("shows truthful partial output and interruption, and restores keyboard focus", async () => {
    vi.mocked(fetch).mockResolvedValue(response([task({
      state: "interrupted", partial: true, result: "Found a conflicting setting",
      stop_reason: "host_restarted", completed_at: 102,
    })]));
    const user = userEvent.setup();
    render(layout());
    const archive = await openArchive(user);
    expect(screen.queryByTestId("subagent-task-dock")).not.toBeInTheDocument();
    const row = within(archive).getByRole("button", { name: /Config check Interrupted/ });
    await user.click(row);
    const detail = screen.getByRole("dialog", { name: "Config check" });
    expect(within(detail).getByText(/has not been restarted automatically/)).toBeVisible();
    expect(detail).toHaveFocus();
    expect(within(detail).getByText("Interrupted")).toBeVisible();
    expect(within(detail).getByText("Found a conflicting setting")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Stop Config check" })).not.toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(row).toHaveFocus());
  });

  it("keeps cancellation and an open detail consistent when an older read completes later", async () => {
    let resolveRefresh!: (value: Response) => void;
    let resolveStop!: (value: SubagentTaskSnapshot) => void;
    requestMutation.mockImplementation(() => new Promise((resolve) => { resolveStop = resolve; }));
    const user = userEvent.setup();
    render(layout());
    const list = await openTaskList(user);
    const activityStop = within(list).getByRole("button", { name: "Stop Config check" });
    const row = within(list).getByRole("button", { name: /Config check Running/ });
    await user.click(row);
    const detail = screen.getByRole("dialog", { name: "Config check" });
    const stop = within(detail).getByRole("button", { name: "Stop Config check" });
    expect(within(detail).getByRole("heading", { name: "Config check" }).parentElement).toContainElement(stop);
    expect(detail).toHaveAccessibleDescription("Running");
    expect(within(detail).getByText("Running").parentElement).toHaveClass("sr-only");
    expect(stop.querySelector('[data-action-icon="stop"][data-active] .loading-ring-arc')).toBeInTheDocument();
    await user.click(stop);
    expect(stop).toBeDisabled();
    expect(stop).toHaveAttribute("aria-busy", "true");
    expect(activityStop).toBeDisabled();
    expect(activityStop).toHaveAttribute("aria-busy", "true");
    vi.mocked(fetch).mockImplementationOnce(() => new Promise((resolve) => { resolveRefresh = resolve; }));
    fireEvent(window, new Event("focus"));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    await act(async () => { resolveStop(task({ revision: 3, state: "cancelled", completed_at: 102 })); });
    expect(screen.getByRole("dialog", { name: "Config check" })).toBe(detail);
    expect(detail).toHaveTextContent("Cancelled");
    await act(async () => { resolveRefresh(response([task()])); });
    expect(detail).toHaveTextContent("Cancelled");
    expect(within(detail).queryByRole("button", { name: "Stop Config check" })).not.toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(within(list).getByRole("button", { name: /Config check Cancelled/ })).toBe(row);
    expect(within(list).queryByRole("button", { name: "Stop Config check" })).not.toBeInTheDocument();
    await waitFor(() => expect(row).toHaveFocus());
    expect(requestMutation).toHaveBeenCalledTimes(1);
    expect(requestMutation).toHaveBeenCalledWith("subagent.cancel", { session_key: "websocket:a", task_id: "task-1" }, 20_000);
  });

  it("does not request an unsupported feature and detaches events in hidden panes", async () => {
    const user = userEvent.setup();
    const view = render(layout({ enabled: false }));
    expect(fetch).not.toHaveBeenCalled();
    view.rerender(layout({ visible: false }));
    expect(fetch).not.toHaveBeenCalled();
    view.rerender(layout());
    const list = await openTaskList(user);
    await user.click(within(list).getByRole("button", { name: /Config check Running/ }));
    expect(screen.getByRole("dialog", { name: "Config check" })).toBeVisible();
    view.rerender(layout({ visible: false }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent(window, new Event("focus"));
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(chatHandlers.get("a")?.size).toBe(0);
    expect(statusHandlers.size).toBe(0);
  });

  it("reports a failed header stop and lets the user retry without closing details", async () => {
    const user = userEvent.setup();
    requestMutation.mockRejectedValueOnce(new Error("Cannot stop task"));
    render(layout());
    const list = await openTaskList(user);
    await user.click(within(list).getByRole("button", { name: /Config check Running/ }));
    const detail = screen.getByRole("dialog", { name: "Config check" });
    const stop = within(detail).getByRole("button", { name: "Stop Config check" });
    expect(within(detail).getByRole("heading", { name: "Config check" }).parentElement).toContainElement(stop);
    await user.click(stop);
    expect(await within(detail).findByRole("alert")).toHaveTextContent("Cannot stop task");
    expect(stop).toBeEnabled();
    requestMutation.mockResolvedValueOnce(task({ revision: 2, state: "cancelled", completed_at: 102 }));
    await user.click(stop);
    expect(screen.getByRole("dialog", { name: "Config check" })).toBe(detail);
    expect(detail).toHaveTextContent("Cancelled");
    expect(requestMutation).toHaveBeenCalledTimes(2);
  });

  it("preserves loaded tasks and stop errors across background snapshot failures", async () => {
    const user = userEvent.setup();
    requestMutation.mockRejectedValue(new Error("Cannot stop task"));
    render(layout());
    const list = await openTaskList(user);
    await user.click(within(list).getByRole("button", { name: "Stop Config check" }));
    await within(list).findByText("Cannot stop task");
    fireEvent(window, new Event("focus"));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(within(list).getByText("Cannot stop task")).toBeVisible();
    vi.mocked(fetch).mockRejectedValue(new Error("offline"));
    await act(async () => { fireEvent(window, new Event("focus")); });
    expect(within(list).getByRole("button", { name: /Config check Running/ })).toBeVisible();
    expect(within(list).getByText("Cannot stop task")).toBeVisible();
  });

  it("retains the last valid snapshot after malformed reads and recovers on refresh", async () => {
    const user = userEvent.setup();
    render(layout());
    const list = await openTaskList(user);
    vi.mocked(fetch).mockImplementation(async () => new Response(JSON.stringify({
      tasks: [{ ...task(), label: { unexpected: true } }],
    }), { headers: { "content-type": "application/json" } }));
    await act(async () => { fireEvent(window, new Event("focus")); });
    expect(screen.getByRole("button", { name: /Config check Running/ })).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    vi.mocked(fetch).mockImplementation(async () => response([task(), task()]));
    await act(async () => { fireEvent(window, new Event("focus")); });
    expect(screen.getByRole("button", { name: /Config check Running/ })).toBeVisible();
    vi.mocked(fetch).mockResolvedValue(response([task({ revision: 2, state: "done", completed_at: 102 })]));
    await act(async () => { fireEvent(window, new Event("focus")); });
    expect(within(list).getByRole("button", { name: /Config check Completed/ })).toBeVisible();
    expect(screen.getByTestId("subagent-task-dock-trigger")).toHaveTextContent("Completed: 1");
  });

  it("discards reads from the previous session after switching", async () => {
    let resolveOld!: (value: Response) => void;
    vi.mocked(fetch).mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }));
    const user = userEvent.setup();
    const view = render(layout());
    vi.mocked(fetch).mockResolvedValue(response([task({ task_id: "task-b", label: "Other work" })]));
    view.rerender(layout({ sessionKey: "websocket:b" }));
    const list = await openTaskList(user);
    expect(within(list).getByRole("button", { name: /Other work Running/ })).toBeVisible();
    await act(async () => { resolveOld(response([task()])); });
    expect(screen.queryByText("Config check")).not.toBeInTheDocument();
  });

  it("keeps task details open through completion and renders Markdown results", async () => {
    const user = userEvent.setup();
    render(layout());
    const list = await openTaskList(user);
    const row = within(list).getByRole("button", { name: /Config check Running/ });
    await user.click(row);
    const detail = screen.getByRole("dialog", { name: "Config check" });
    vi.mocked(fetch).mockImplementation(async () => response([task({ revision: 2, state: "done", completed_at: 102,
      result: "## Findings\n\n- **Release** resources\n- Cover exceptions\n\n```python\nawait connection.close()\n```\n\n| Check | Result |\n| --- | --- |\n| Cancellation | Passed |\n\n[Evidence](https://example.com/review)",
    })]));
    fireEvent(window, new Event("focus"));
    expect(await within(detail).findByRole("heading", { name: "Findings" })).toBeVisible();
    expect(within(detail).getByRole("list")).toHaveTextContent("Release resources");
    expect(within(detail).getByRole("table")).toHaveTextContent("CancellationPassed");
    await waitFor(() => expect(detail.querySelector("code")).toHaveTextContent("await connection.close()"));
    expect(detail.querySelector("code")).toBeVisible();
    expect(within(detail).getByRole("link", { name: /Evidence/ })).toHaveAttribute("href", "https://example.com/review");
    expect(detail).toBeVisible();
    await user.keyboard("{Escape}");
    expect(list).toBeVisible();
    await waitFor(() => expect(row).toHaveFocus());
    await user.keyboard("{Escape}");
    expect(screen.queryByTestId("subagent-task-dock")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Message" })).toHaveFocus());
    expect(await screen.findByRole("region", { name: "Subtasks" })).toBeVisible();
    expect(requestMutation).not.toHaveBeenCalled();
  });

  it("anchors terminal replay once when multiple prompts share a turn and preserves archive order", async () => {
    const replay = [...messages, { id: "followup", role: "user", content: "Focus on errors", turnId: "turn-a", createdAt: 102_000 } satisfies UIMessage];
    const keys = unitKeysForDisplay(buildDisplayUnits(replay));
    expect(new Set(keys).size).toBe(keys.length);
    vi.mocked(fetch).mockImplementation(async () => response([
      task({ task_id: "second", label: "Second check", created_at: 101, origin_message_id: "old-prompt-id" }),
      task({ origin_message_id: "old-prompt-id", state: "done", completed_at: 102 }),
    ]));
    const user = userEvent.setup();
    render(layout({ threadMessages: replay }));
    const archive = await openArchive(user);
    expect(screen.getAllByRole("region", { name: "Subtasks" })).toHaveLength(1);
    expect(taskIds(archive)).toEqual(["task-1"]);
    expect(within(archive).getByRole("button", { name: /Config check Completed/ })).toBeVisible();
    expect(within(archive).queryByRole("button", { name: /Second check Running/ })).not.toBeInTheDocument();
    vi.mocked(fetch).mockImplementation(async () => response([
      task({ task_id: "second", revision: 2, label: "Second check", created_at: 101, origin_message_id: "old-prompt-id", state: "error", error: "Unreadable file", completed_at: 103 }),
      task({ origin_message_id: "old-prompt-id", state: "done", completed_at: 102 }),
    ]));
    fireEvent(window, new Event("focus"));
    await within(archive).findByRole("button", { name: /Second check Failed/ });
    expect(taskIds(archive)).toEqual(["task-1", "second"]);
    expect(screen.getAllByRole("region", { name: "Subtasks" })).toHaveLength(1);
    expect(within(archive).getByRole("button", { name: /Review needed: 1/ })).toBeVisible();
    expect(screen.getByText("Main answer").compareDocumentPosition(archive) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
    expect(archive.compareDocumentPosition(screen.getByText("Focus on errors")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("prefers the exact initiating follow-up over a turn fallback for archived results", async () => {
    vi.mocked(fetch).mockImplementation(async () => response([task({ origin_message_id: "followup", state: "done", completed_at: 102 })]));
    const user = userEvent.setup();
    render(layout({ threadMessages: [...messages, { id: "followup", role: "user", content: "Check more", turnId: "turn-a", createdAt: 102_000 }] }));
    const archive = await openArchive(user);
    expect(within(archive).getByRole("button", { name: /Config check Completed/ })).toBeVisible();
    expect(screen.getAllByRole("region", { name: "Subtasks" })).toHaveLength(1);
    expect(screen.getByText("Check more").compareDocumentPosition(archive) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByTestId("subagent-task-dock")).not.toBeInTheDocument();
  });

  it("keeps legacy work separate after refresh and preserves its disclosure through local history prepends", async () => {
    vi.mocked(fetch).mockImplementation(async () => response([
      task({ task_id: "legacy", revision: 0, label: "Nanjing weather", state: "done", completed_at: 102,
        origin_turn_id: "websocket:a:1791046873588004336", result: "## Nanjing\n\n- **Rain**" }),
      task({ created_at: 200 }),
    ]));
    const user = userEvent.setup();
    const view = render(layout());
    await screen.findByTestId("subagent-task-dock-trigger");
    const otherWork = screen.getByRole("region", { name: "Other tasks" });
    const header = within(otherWork).getByRole("button", { name: /Other tasks/ });
    expect(header).toHaveAttribute("aria-expanded", "false");
    expect(otherWork.compareDocumentPosition(screen.getByText("Inspect config")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Subtasks" })).not.toBeInTheDocument();
    expect(screen.getByTestId("messages")).not.toHaveTextContent("Config check");
    await user.click(header);
    expect(within(otherWork).getByText("These tasks have no matching request in the displayed messages.")).toBeVisible();
    await user.click(within(otherWork).getByRole("button", { name: /Nanjing weather Completed/ }));
    const detail = screen.getByRole("dialog", { name: "Nanjing weather" });
    expect(within(detail).getByRole("heading", { name: "Nanjing" })).toBeVisible();
    expect(within(detail).getByRole("list")).toHaveTextContent("Rain");
    await user.keyboard("{Escape}");
    view.rerender(layout({ threadMessages: [
      { id: "cached-prompt", role: "user", content: "Earlier cached prompt", createdAt: 99_000 },
      ...messages,
    ] }));
    const expanded = screen.getByRole("region", { name: "Other tasks" });
    expect(within(expanded).getByRole("button", { name: /Other tasks/ })).toHaveAttribute("aria-expanded", "true");
    expect(within(expanded).getByRole("button", { name: /Nanjing weather Completed/ })).toBeVisible();
    view.unmount();
    render(layout());
    const restored = await screen.findByRole("region", { name: "Other tasks" });
    expect(within(restored).getByRole("button", { name: /Other tasks/ })).toHaveAttribute("aria-expanded", "false");
    expect(restored.compareDocumentPosition(screen.getByText("Inspect config")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(requestMutation).not.toHaveBeenCalled();
  });

  it("reattaches archived work when its prompt loads without duplicating it, closing details or losing focus", async () => {
    vi.mocked(fetch).mockImplementation(async () => response([
      task({ task_id: "older", label: "Earlier check", state: "done", completed_at: 102, result: "Earlier finding", origin_turn_id: "older-turn", origin_message_id: "older-prompt" }),
      task({ created_at: 200 }),
    ]));
    const user = userEvent.setup();
    const view = render(layout());
    const otherWork = await openArchive(user, "Other tasks");
    await user.click(within(otherWork).getByRole("button", { name: /Earlier check Completed/ }));
    const detail = screen.getByRole("dialog", { name: "Earlier check" });
    view.rerender(layout({ threadMessages: [
      { id: "older-prompt", role: "user", content: "Inspect earlier work", turnId: "older-turn", createdAt: 99_000 },
      ...messages,
    ] }));
    expect(detail).toBeVisible();
    expect(within(detail).getByText("Earlier finding")).toBeVisible();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("region", { name: "Other tasks" })).not.toBeInTheDocument();
    const archive = screen.getByRole("region", { name: "Subtasks" });
    const summary = within(archive).getByRole("button", { name: /Subtasks/ });
    expect(summary).toHaveAttribute("aria-expanded", "true");
    expect(taskIds(screen.getByTestId("messages"))).toEqual(["older"]);
    expect(screen.getByText("Inspect earlier work").compareDocumentPosition(archive) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText("Inspect config").compareDocumentPosition(archive) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
    const row = within(archive).getByRole("button", { name: /Earlier check Completed/ });
    await waitFor(() => expect(row).toHaveFocus());
    expect(row).toBeVisible();
  });

  it("merges live work before the initial read without polling or rolling back completed work", async () => {
    let resolveRead!: (value: Response) => void;
    vi.mocked(fetch).mockImplementationOnce(() => new Promise((resolve) => { resolveRead = resolve; }));
    const user = userEvent.setup();
    render(layout());
    emitTask(task({ revision: 3, state: "done", result: "Verified", completed_at: 102 }));
    emitTask(task({ task_id: "task-2", label: "Sibling check", created_at: 101 }));
    const list = await openTaskList(user);
    expect(within(list).getByRole("button", { name: /Sibling check Running/ })).toBeVisible();
    await act(async () => { resolveRead(response([task()])); });
    expect(taskIds(list)).toEqual(["task-2"]);
    expect(screen.getByTestId("subagent-task-dock-trigger")).toHaveTextContent("Running: 1");
    expect(screen.getByTestId("subagent-task-dock-trigger")).not.toHaveTextContent("Completed:");
    const archive = await openArchive(user);
    expect(within(archive).getByRole("button", { name: /Config check Completed/ })).toBeVisible();
    expect(screen.getAllByRole("region", { name: "Subtasks" })).toHaveLength(1);
    vi.useFakeTimers();
    await act(async () => { vi.advanceTimersByTime(10_000); });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(requestMutation).not.toHaveBeenCalled();
  });

  it("keeps elapsed time in task rows without repeating it in details", async () => {
    vi.useFakeTimers();
    vi.spyOn(performance, "now").mockImplementation(() => Date.now());
    render(layout());
    await act(async () => { await Promise.resolve(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    fireEvent.click(screen.getByTestId("subagent-task-dock-trigger"));
    const row = within(screen.getByTestId("subagent-task-tree")).getByRole("button", { name: /Config check Running/ });
    expect(row).toHaveTextContent("12s");
    fireEvent.click(row);
    const detail = screen.getByRole("dialog", { name: "Config check" });
    expect(detail).toHaveAccessibleDescription("Running");
    expect(detail).not.toHaveTextContent("12s");
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(row).toHaveTextContent("13s");
    expect(fetch).toHaveBeenCalledTimes(1);
    vi.mocked(performance.now).mockRestore();
  });

  it("recovers missed siblings after reconnect even when an older read is still pending", async () => {
    let resolveOld!: (value: Response) => void;
    const user = userEvent.setup();
    render(layout());
    const list = await openTaskList(user);
    vi.mocked(fetch).mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }));
    fireEvent(window, new Event("focus"));
    emitTask(task({ revision: 3, state: "cancelled", completed_at: 102 }));
    vi.mocked(fetch).mockImplementationOnce(async () => response([
      task({ revision: 2 }), task({ task_id: "task-2", label: "Recovered check", created_at: 101 }),
    ]));
    act(() => { statusHandlers.forEach((handler) => { handler("closed"); handler("open"); }); });
    await act(async () => { resolveOld(response([task()])); });
    await within(list).findByRole("button", { name: /Recovered check Running/ });
    expect(within(list).getByRole("button", { name: /Config check Cancelled/ })).toBeVisible();
    expect(taskIds(list)).toEqual(["task-1", "task-2"]);
    expect(fetch).toHaveBeenCalledTimes(3);
    emitTask({ ...task(), revision: -1 });
    expect(within(list).getByRole("button", { name: /Config check Cancelled/ })).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("reads snapshots without polling on a host without task events", async () => {
    vi.mocked(fetch).mockImplementation(async () => response([task({ revision: undefined })]));
    vi.useFakeTimers();
    const view = render(layout({ liveEvents: false }));
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByTestId("subagent-task-dock-trigger")).toHaveTextContent("Running: 1");
    fireEvent.click(screen.getByTestId("subagent-task-dock-trigger"));
    const list = screen.getByTestId("subagent-task-tree");
    expect(within(list).getByRole("button", { name: /Config check Running/ })).toBeVisible();
    vi.mocked(fetch).mockImplementation(async () => response([task({ revision: undefined, state: "done", completed_at: 102 })]));
    await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: /Config check Running/ })).toBeVisible();
    await act(async () => { fireEvent(window, new Event("focus")); });
    expect(screen.getByTestId("subagent-task-dock-trigger")).toHaveTextContent("Completed: 1");
    expect(within(list).getByRole("button", { name: /Config check Completed/ })).toBeVisible();
    expect(client.onChat).not.toHaveBeenCalled();
    view.rerender(layout({ liveEvents: false, visible: false }));
    const reads = vi.mocked(fetch).mock.calls.length;
    await act(async () => { vi.advanceTimersByTime(6000); });
    expect(fetch).toHaveBeenCalledTimes(reads);
  });
});
