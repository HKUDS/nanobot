import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ActiveSubagentTasks, SubagentHistory, SubagentTasksProvider } from "@/components/thread/SubagentTasks";
import { ThreadMessages } from "@/components/thread/ThreadMessages";
import { ThreadVisibilityContext } from "@/hooks/useThreadVisibility";
import { setAppLanguage } from "@/i18n";
import type { SubagentTaskSnapshot, UIMessage } from "@/lib/types";

const requestMutation = vi.fn();
const client = { requestMutation };
const messages: UIMessage[] = [
  { id: "prompt-a", role: "user", content: "Inspect config", turnId: "turn-a" },
  { id: "answer-a", role: "assistant", content: "Main answer", turnId: "turn-a" },
];

function task(overrides: Partial<SubagentTaskSnapshot> = {}): SubagentTaskSnapshot {
  return {
    task_id: "task-1", label: "Config check", task_description: "Check configuration values",
    state: "running", phase: "awaiting_model", elapsed_seconds: 2, iteration: 1,
    tool_events: [], usage: null, receipts: {}, result: null, partial: false,
    stop_reason: null, error: null, origin_turn_id: "turn-a", origin_message_id: null,
    created_at: 100, completed_at: null, ...overrides,
  };
}
function response(tasks: SubagentTaskSnapshot[]): Response {
  return new Response(JSON.stringify({ tasks }), { headers: { "content-type": "application/json" } });
}
function layout({ enabled = true, sessionKey = "websocket:a", visible = true } = {}) {
  return <ThreadVisibilityContext.Provider value={visible}>
    <SubagentTasksProvider client={client} sessionKey={sessionKey} token="tok" enabled={enabled}>
      <div data-testid="messages"><ThreadMessages messages={messages} /><SubagentHistory turnId="other-turn" /></div>
      <div data-testid="composer"><ActiveSubagentTasks /><textarea aria-label="Message" /></div>
    </SubagentTasksProvider>
  </ThreadVisibilityContext.Provider>;
}

describe("session-owned task UI", () => {
  beforeEach(async () => {
    await setAppLanguage("en");
    requestMutation.mockReset();
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => response([task()])));
  });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  it("moves a completed task from the composer to its initiating message without duplicating it", async () => {
    const view = render(layout());
    await screen.findByRole("button", { name: /Config check Running/ });
    expect(within(screen.getByTestId("messages")).queryByText("Config check")).not.toBeInTheDocument();
    vi.mocked(fetch).mockImplementation(async () => response([task({ state: "done", result: "Verified", completed_at: 102 })]));
    fireEvent(window, new Event("focus"));
    const row = await screen.findByRole("button", { name: /Config check Completed/ });
    expect(screen.getAllByRole("button", { name: /Config check/ })).toHaveLength(1);
    expect(within(screen.getByTestId("composer")).queryByText("Config check")).not.toBeInTheDocument();
    expect(screen.getByTestId("messages")).toContainElement(row);
    expect(row.closest("section")).toHaveAccessibleName("Task results");
    view.unmount();
    render(layout());
    await screen.findByRole("button", { name: /Config check Completed/ });
    expect(requestMutation).not.toHaveBeenCalled();
  });

  it("shows truthful partial output, interruption and receipts, and restores keyboard focus", async () => {
    vi.mocked(fetch).mockResolvedValue(response([task({
      state: "interrupted", partial: true, result: "Found a conflicting setting",
      stop_reason: "host_restarted", completed_at: 102, receipts: { a: "delivered", b: "undelivered" },
    })]));
    const user = userEvent.setup();
    render(layout());
    const row = await screen.findByRole("button", { name: /Config check Interrupted/ });
    await user.click(row);
    const detail = screen.getByRole("dialog", { name: "Config check" });
    expect(within(detail).getByText(/has not been restarted automatically/)).toBeVisible();
    expect(within(detail).getByText("Partial result")).toBeVisible();
    expect(within(detail).getByText("Found a conflicting setting")).toBeVisible();
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
    await act(async () => { resolveStop(task({ state: "cancelled", completed_at: 102 })); });
    await screen.findByRole("button", { name: /Config check Cancelled/ });
    await act(async () => { resolveRefresh(response([task()])); });
    expect(screen.queryByRole("button", { name: "Stop Config check" })).not.toBeInTheDocument();
    expect(requestMutation).toHaveBeenCalledWith("subagent.cancel", { session_key: "websocket:a", task_id: "task-1" }, 20_000);
  });

  it("does not request an unsupported feature and pauses polling in hidden panes", async () => {
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
    await screen.findByText("Could not load subagent tasks.");
    expect(screen.getByRole("button", { name: /Config check Running/ })).toBeVisible();
  });

  it("shows a read error for malformed or duplicate task records", async () => {
    vi.mocked(fetch).mockImplementation(async () => new Response(JSON.stringify({
      tasks: [{ ...task(), label: { unexpected: true } }],
    }), { headers: { "content-type": "application/json" } }));
    render(layout());
    await screen.findByText("Could not load subagent tasks.");
    expect(screen.queryByText("Config check")).not.toBeInTheDocument();
    vi.mocked(fetch).mockImplementation(async () => response([task(), task()]));
    fireEvent(window, new Event("focus"));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(screen.getByText("Could not load subagent tasks.")).toBeVisible();
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
});
