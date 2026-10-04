import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SubagentTasksProvider } from "@/components/thread/SubagentTasks";
import { buildDisplayUnits, ThreadMessages, unitKeysForDisplay } from "@/components/thread/ThreadMessages";
import { ThreadVisibilityContext } from "@/hooks/useThreadVisibility";
import { setAppLanguage } from "@/i18n";
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
  { id: "prompt-a", role: "user", content: "Inspect config", turnId: "turn-a" },
  { id: "answer-a", role: "assistant", content: "Main answer", turnId: "turn-a" },
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
function layout({ enabled = true, liveEvents = true, sessionKey = "websocket:a", visible = true, threadMessages = messages } = {}) {
  return <ThreadVisibilityContext.Provider value={visible}>
    <SubagentTasksProvider client={client} sessionKey={sessionKey} token="tok" enabled={enabled} liveEvents={liveEvents}>
      <div data-testid="messages"><ThreadMessages messages={threadMessages} /></div>
      <div data-testid="composer"><textarea aria-label="Message" /></div>
    </SubagentTasksProvider>
  </ThreadVisibilityContext.Provider>;
}

describe("session-owned task UI", () => {
  beforeEach(async () => {
    await setAppLanguage("en");
    requestMutation.mockReset();
    client.onChat.mockClear();
    client.onStatus.mockClear();
    chatHandlers.clear();
    statusHandlers.clear();
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => response([task()])));
  });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  it("keeps the same work block under its prompt, folds completed work and restores it after refresh", async () => {
    const view = render(layout());
    const runningRow = await screen.findByRole("button", { name: /Config check Running/ });
    const work = runningRow.closest("section");
    const header = within(work!).getByRole("button", { name: /Delegated work/ });
    expect(screen.getByTestId("messages")).toContainElement(runningRow);
    expect(header).toHaveAttribute("aria-expanded", "true");
    vi.mocked(fetch).mockImplementation(async () => response([task({ revision: 2, state: "done", result: "Verified", completed_at: 102 })]));
    fireEvent(window, new Event("focus"));
    await waitFor(() => expect(header).toHaveAttribute("aria-expanded", "false"));
    fireEvent.click(header);
    const row = screen.getByRole("button", { name: /Config check Completed/ });
    expect(row).toBe(runningRow);
    expect(row.closest("section")).toBe(work);
    expect(within(screen.getByTestId("composer")).queryByText("Config check")).not.toBeInTheDocument();
    expect(work).toHaveAccessibleName("Delegated work");
    view.unmount();
    render(layout());
    fireEvent.click(await screen.findByRole("button", { name: /Delegated work Finished: 1/ }));
    expect(screen.getByRole("button", { name: /Config check Completed/ })).toBeVisible();
    expect(requestMutation).not.toHaveBeenCalled();
  });

  it("shows truthful partial output, interruption and receipts, and restores keyboard focus", async () => {
    vi.mocked(fetch).mockResolvedValue(response([task({
      state: "interrupted", partial: true, result: "Found a conflicting setting",
      stop_reason: "host_restarted", completed_at: 102, receipts: { a: "delivered", b: "undelivered" },
    })]));
    const user = userEvent.setup();
    render(layout());
    await user.click(await screen.findByRole("button", { name: /Delegated work/ }));
    const row = await screen.findByRole("button", { name: /Config check Interrupted/ });
    await user.click(row);
    const detail = screen.getByRole("dialog", { name: "Config check" });
    expect(within(detail).getByText(/has not been restarted automatically/)).toBeVisible();
    expect(within(detail).getByText("Partial result")).toBeVisible();
    expect(within(detail).getByText("Found a conflicting setting")).toBeVisible();
    await user.click(within(detail).getByText("Message delivery"));
    expect(within(detail).getByText("Delivered: 1")).toBeVisible();
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
    await user.click(await screen.findByRole("button", { name: /Config check Running/ }));
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "Stop Config check" }));
    vi.mocked(fetch).mockImplementationOnce(() => new Promise((resolve) => { resolveRefresh = resolve; }));
    fireEvent(window, new Event("focus"));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    await act(async () => { resolveStop(task({ revision: 3, state: "cancelled", completed_at: 102 })); });
    await user.click(screen.getByRole("button", { name: /Delegated work Finished: 1/ }));
    await screen.findByRole("button", { name: /Config check Cancelled/ });
    await act(async () => { resolveRefresh(response([task()])); });
    expect(screen.queryByRole("button", { name: "Stop Config check" })).not.toBeInTheDocument();
    expect(requestMutation).toHaveBeenCalledWith("subagent.cancel", { session_key: "websocket:a", task_id: "task-1" }, 20_000);
  });

  it("does not request an unsupported feature and detaches events in hidden panes", async () => {
    const view = render(layout({ enabled: false }));
    expect(fetch).not.toHaveBeenCalled();
    view.rerender(layout({ visible: false }));
    expect(fetch).not.toHaveBeenCalled();
    view.rerender(layout());
    fireEvent.click(await screen.findByRole("button", { name: /Config check Running/ }));
    expect(screen.getByRole("dialog", { name: "Config check" })).toBeVisible();
    view.rerender(layout({ visible: false }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent(window, new Event("focus"));
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(chatHandlers.get("a")?.size).toBe(0);
    expect(statusHandlers.size).toBe(0);
  });

  it("keeps load failures visible and keeps stop failures across a successful refresh", async () => {
    const user = userEvent.setup();
    requestMutation.mockRejectedValue(new Error("Cannot stop task"));
    render(layout());
    await user.click(await screen.findByRole("button", { name: "Stop Config check" }));
    await screen.findByText("Cannot stop task");
    fireEvent(window, new Event("focus"));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(screen.getByText("Cannot stop task")).toBeVisible();
    vi.mocked(fetch).mockRejectedValue(new Error("offline"));
    fireEvent(window, new Event("focus"));
    await screen.findByText("Could not load subtasks.");
    expect(screen.getByRole("button", { name: /Config check Running/ })).toBeVisible();
  });

  it("shows a read error for malformed or duplicate task records", async () => {
    vi.mocked(fetch).mockImplementation(async () => new Response(JSON.stringify({
      tasks: [{ ...task(), label: { unexpected: true } }],
    }), { headers: { "content-type": "application/json" } }));
    render(layout());
    await screen.findByText("Could not load subtasks.");
    expect(screen.queryByText("Config check")).not.toBeInTheDocument();
    vi.mocked(fetch).mockImplementation(async () => response([task(), task()]));
    fireEvent(window, new Event("focus"));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(screen.getByText("Could not load subtasks.")).toBeVisible();
    expect(screen.queryByText("Config check")).not.toBeInTheDocument();
  });

  it("discards reads from the previous session after switching", async () => {
    let resolveOld!: (value: Response) => void;
    vi.mocked(fetch).mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }));
    const view = render(layout());
    vi.mocked(fetch).mockResolvedValue(response([task({ task_id: "task-b", label: "Other work" })]));
    view.rerender(layout({ sessionKey: "websocket:b" }));
    await screen.findByRole("button", { name: /Other work Running/ });
    await act(async () => { resolveOld(response([task()])); });
    expect(screen.queryByText("Config check")).not.toBeInTheDocument();
  });

  it("keeps task details open through completion and renders Markdown results", async () => {
    const user = userEvent.setup();
    render(layout());
    const row = await screen.findByRole("button", { name: /Config check Running/ });
    await user.click(row);
    const detail = screen.getByRole("dialog", { name: "Config check" });
    vi.mocked(fetch).mockImplementation(async () => response([task({ revision: 2, state: "done", completed_at: 102,
      result: "## Findings\n\n- **Release** resources\n- Cover exceptions\n\n```python\nawait connection.close()\n```\n\n| Check | Result |\n| --- | --- |\n| Cancellation | Passed |\n\n[Evidence](https://example.com/review)",
    })]));
    fireEvent(window, new Event("focus"));
    expect(await within(detail).findByRole("heading", { name: "Findings" })).toBeVisible();
    expect(within(detail).getByRole("list")).toHaveTextContent("Release resources");
    expect(within(detail).getByRole("table")).toHaveTextContent("CancellationPassed");
    expect(await within(detail).findByText("await connection.close()", { exact: false })).toBeVisible();
    expect(within(detail).getByRole("link", { name: /Evidence/ })).toHaveAttribute("href", "https://example.com/review");
    expect(detail).toBeVisible();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.getByRole("button", { name: /Delegated work/ })).toHaveFocus());
    expect(requestMutation).not.toHaveBeenCalled();
  });

  it("anchors replay once when multiple prompts share a turn and preserves row order", async () => {
    const replay = [...messages, { id: "followup", role: "user", content: "Focus on errors", turnId: "turn-a" } satisfies UIMessage];
    const keys = unitKeysForDisplay(buildDisplayUnits(replay));
    expect(new Set(keys).size).toBe(keys.length);
    vi.mocked(fetch).mockImplementation(async () => response([
      task({ task_id: "second", label: "Second check", created_at: 101, origin_message_id: "old-prompt-id" }),
      task({ origin_message_id: "old-prompt-id" }),
    ]));
    render(layout({ threadMessages: replay }));
    await screen.findByRole("button", { name: /Config check Running/ });
    expect(screen.getAllByRole("region", { name: "Delegated work" })).toHaveLength(1);
    const rows = screen.getAllByRole("button", { name: /check Running/ });
    expect(rows.map((row) => row.dataset.subagentId)).toEqual(["task-1", "second"]);
    vi.mocked(fetch).mockImplementation(async () => response([
      task({ task_id: "second", revision: 2, label: "Second check", created_at: 101, origin_message_id: "old-prompt-id", state: "error", error: "Unreadable file" }),
      task({ origin_message_id: "old-prompt-id" }),
    ]));
    fireEvent(window, new Event("focus"));
    await screen.findByRole("button", { name: /Second check Failed/ });
    expect(screen.getAllByRole("button", { name: /check (Running|Failed)/ }).map((row) => row.dataset.subagentId)).toEqual(["task-1", "second"]);
    expect(screen.getByRole("button", { name: /Review needed: 1/ })).toBeVisible();
    expect(screen.getByText("Main answer").compareDocumentPosition(screen.getByText("Second check")) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
  });

  it("prefers the exact initiating follow-up over a turn fallback", async () => {
    vi.mocked(fetch).mockImplementation(async () => response([task({ origin_message_id: "followup" })]));
    render(layout({ threadMessages: [...messages, { id: "followup", role: "user", content: "Check more", turnId: "turn-a" }] }));
    await screen.findByRole("button", { name: /Config check Running/ });
    const group = screen.getByRole("region", { name: "Delegated work" });
    expect(screen.getByText("Check more").compareDocumentPosition(group) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("keeps legacy work with an unknown origin separate from the latest request after refresh", async () => {
    vi.mocked(fetch).mockImplementation(async () => response([
      task({ task_id: "legacy", revision: 0, label: "Nanjing weather", state: "done", completed_at: 102,
        origin_turn_id: "websocket:a:1791046873588004336", result: "## Nanjing\n\n- **Rain**" }),
      task({ created_at: 200 }),
    ]));
    const user = userEvent.setup();
    const view = render(layout());
    await screen.findByRole("button", { name: /Config check Running/ });
    const otherWork = screen.getByRole("region", { name: "Other delegated work" });
    const header = within(otherWork).getByRole("button", { name: /Other delegated work/ });
    expect(header).toHaveAttribute("aria-expanded", "false");
    expect(otherWork.compareDocumentPosition(screen.getByText("Inspect config")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(screen.getByRole("region", { name: "Delegated work" })).queryByText("Nanjing weather")).not.toBeInTheDocument();
    await user.click(header);
    expect(within(otherWork).getByText("These tasks have no matching request in the displayed messages.")).toBeVisible();
    await user.click(within(otherWork).getByRole("button", { name: /Nanjing weather Completed/ }));
    const detail = screen.getByRole("dialog", { name: "Nanjing weather" });
    expect(within(detail).getByRole("heading", { name: "Nanjing" })).toBeVisible();
    expect(within(detail).getByRole("list")).toHaveTextContent("Rain");
    await user.keyboard("{Escape}");
    view.unmount();
    render(layout());
    const restored = await screen.findByRole("region", { name: "Other delegated work" });
    expect(within(restored).getByRole("button", { name: /Other delegated work/ })).toHaveAttribute("aria-expanded", "false");
    expect(restored.compareDocumentPosition(screen.getByText("Inspect config")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(requestMutation).not.toHaveBeenCalled();
  });

  it("reattaches work when its initiating prompt is loaded without duplicating it or closing details", async () => {
    vi.mocked(fetch).mockImplementation(async () => response([
      task({ task_id: "older", label: "Earlier check", origin_turn_id: "older-turn", origin_message_id: "older-prompt" }),
      task({ created_at: 200 }),
    ]));
    const user = userEvent.setup();
    const view = render(layout());
    const otherWork = await screen.findByRole("region", { name: "Other delegated work" });
    await user.click(within(otherWork).getByRole("button", { name: /Earlier check Running/ }));
    const detail = screen.getByRole("dialog", { name: "Earlier check" });
    view.rerender(layout({ threadMessages: [
      { id: "older-prompt", role: "user", content: "Inspect earlier work", turnId: "older-turn" },
      ...messages,
    ] }));
    expect(detail).toBeVisible();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("region", { name: "Other delegated work" })).not.toBeInTheDocument();
    const row = screen.getByRole("button", { name: /Earlier check Running/ });
    expect(screen.getAllByRole("button", { name: /Earlier check Running/ })).toHaveLength(1);
    expect(screen.getByText("Inspect earlier work").compareDocumentPosition(row) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText("Inspect config").compareDocumentPosition(row) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
    await waitFor(() => expect(row).toHaveFocus());
  });

  it("merges live work before the initial read without polling or rolling back completed work", async () => {
    let resolveRead!: (value: Response) => void;
    vi.mocked(fetch).mockImplementationOnce(() => new Promise((resolve) => { resolveRead = resolve; }));
    render(layout());
    emitTask(task({ revision: 3, state: "done", result: "Verified", completed_at: 102 }));
    emitTask(task({ task_id: "task-2", label: "Sibling check", created_at: 101 }));
    await screen.findByRole("button", { name: /Sibling check Running/ });
    await act(async () => { resolveRead(response([task()])); });
    expect(screen.getByRole("button", { name: /Config check Completed/ })).toBeVisible();
    expect(screen.getAllByRole("region", { name: "Delegated work" })).toHaveLength(1);
    vi.useFakeTimers();
    await act(async () => { vi.advanceTimersByTime(10_000); });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(requestMutation).not.toHaveBeenCalled();
  });

  it("keeps elapsed time consistent when inspecting a task long after its last event", async () => {
    vi.useFakeTimers();
    vi.spyOn(performance, "now").mockImplementation(() => Date.now());
    render(layout());
    await act(async () => { await Promise.resolve(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    const row = screen.getByRole("button", { name: /Config check Running/ });
    expect(row).toHaveTextContent("12s");
    fireEvent.click(row);
    expect(screen.getByRole("dialog", { name: "Config check" })).toHaveTextContent("12s");
    expect(fetch).toHaveBeenCalledTimes(1);
    vi.mocked(performance.now).mockRestore();
  });

  it("recovers missed siblings after reconnect even when an older read is still pending", async () => {
    let resolveOld!: (value: Response) => void;
    render(layout());
    await screen.findByRole("button", { name: /Config check Running/ });
    vi.mocked(fetch).mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }));
    fireEvent(window, new Event("focus"));
    emitTask(task({ revision: 3, state: "cancelled", completed_at: 102 }));
    vi.mocked(fetch).mockImplementationOnce(async () => response([
      task({ revision: 2 }), task({ task_id: "task-2", label: "Recovered check", created_at: 101 }),
    ]));
    act(() => { statusHandlers.forEach((handler) => { handler("closed"); handler("open"); }); });
    await act(async () => { resolveOld(response([task()])); });
    await screen.findByRole("button", { name: /Recovered check Running/ });
    expect(screen.getByRole("button", { name: /Config check Cancelled/ })).toBeVisible();
    expect(fetch).toHaveBeenCalledTimes(3);
    emitTask({ ...task(), revision: -1 });
    expect(screen.getByText("Could not load subtasks.")).toBeVisible();
  });

  it("keeps protocol 1 task controls usable on a host without event support", async () => {
    vi.mocked(fetch).mockImplementation(async () => response([task({ revision: undefined })]));
    vi.useFakeTimers();
    const view = render(layout({ liveEvents: false }));
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByRole("button", { name: /Config check Running/ })).toBeVisible();
    vi.mocked(fetch).mockImplementation(async () => response([task({ revision: undefined, state: "done", completed_at: 102 })]));
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(screen.getByRole("button", { name: /Delegated work Finished: 1/ })).toBeVisible();
    expect(client.onChat).not.toHaveBeenCalled();
    view.rerender(layout({ liveEvents: false, visible: false }));
    const reads = vi.mocked(fetch).mock.calls.length;
    await act(async () => { vi.advanceTimersByTime(6000); });
    expect(fetch).toHaveBeenCalledTimes(reads);
  });
});
