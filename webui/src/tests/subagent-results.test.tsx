import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { StrictMode } from "react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SubagentTaskDock } from "@/components/thread/SubagentTaskDock";
import { SubagentThreadMessages } from "@/components/thread/SubagentTaskResults";
import { SubagentTasksProvider } from "@/components/thread/SubagentTasks";
import { setAppLanguage } from "@/i18n";
import { DEFAULT_LOCAL_PREFS, LOCAL_PREFS_STORAGE_KEY, writeLocalPreferences } from "@/lib/local-preferences";
import type { ConnectionStatus, InboundEvent, SubagentTaskSnapshot, UIMessage } from "@/lib/types";

const requestMutation = vi.fn();
const chatHandlers = new Set<(event: InboundEvent) => void>();
const statusHandlers = new Set<(status: ConnectionStatus) => void>();
const client = {
  requestMutation,
  onChat: vi.fn((_chatId: string, handler: (event: InboundEvent) => void) => {
    chatHandlers.add(handler);
    return () => { chatHandlers.delete(handler); };
  }),
  onStatus: vi.fn((handler: (status: ConnectionStatus) => void) => {
    statusHandlers.add(handler);
    handler("open");
    return () => { statusHandlers.delete(handler); };
  }),
};
const messages: UIMessage[] = [
  { id: "prompt-a", role: "user", content: "Inspect config", turnId: "turn-a", createdAt: 100_000 },
  { id: "answer-a", role: "assistant", content: "Main answer", turnId: "turn-a", createdAt: 101_000 },
];

function task(overrides: Partial<SubagentTaskSnapshot> = {}): SubagentTaskSnapshot {
  return {
    task_id: "task-1", revision: 1, label: "Config check", task_description: "Check configuration values",
    state: "done", phase: "finished", elapsed_seconds: 4, iteration: 1,
    tool_events: [], usage: null, receipts: {}, result: null, partial: false,
    stop_reason: null, error: null, origin_turn_id: "turn-a", origin_message_id: "prompt-a",
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
function layout({ threadMessages = messages, sessionKey = "websocket:a", liveEvents = true, historyEnabled = false, active = true, onActivityToggle }: {
  threadMessages?: UIMessage[];
  sessionKey?: string;
  liveEvents?: boolean;
  historyEnabled?: boolean;
  active?: boolean;
  onActivityToggle?: () => void;
} = {}) {
  return <SubagentTasksProvider client={client} sessionKey={sessionKey} token="tok" enabled liveEvents={liveEvents} historyEnabled={historyEnabled} active={active}
    turnIds={[...new Set(threadMessages.filter((message) => message.role === "user" && message.turnId)
      .map((message) => message.turnId as string))]}>
    <div data-testid="messages"><SubagentThreadMessages messages={threadMessages} onActivityToggle={onActivityToggle} /></div>
    <div data-testid="composer" className="thread-composer-stack"><SubagentTaskDock /><textarea aria-label="Message" /></div>
  </SubagentTasksProvider>;
}
function summary(region: HTMLElement) {
  return within(region).getByRole("button", { name: /^Subtasks (Completed|Finished):/ });
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
    statusHandlers.clear();
    vi.stubGlobal("fetch", vi.fn(async () => response([task()])));
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    localStorage.removeItem(LOCAL_PREFS_STORAGE_KEY);
  });

  it("keeps queued, running and stopping work out of chat until a terminal result arrives", async () => {
    vi.mocked(fetch).mockImplementation(async () => response([
      task({ state: "running", phase: "awaiting_model", completed_at: null }),
      task({ task_id: "queued", label: "Waiting check", state: "queued", completed_at: null, created_at: 101 }),
      task({ task_id: "stopping", label: "Stopping check", state: "stopping", completed_at: null,
        origin_message_id: null, origin_turn_id: null, created_at: 102 }),
    ]));
    const user = userEvent.setup();
    render(layout());
    expect(await screen.findByTestId("subagent-task-dock-trigger")).toHaveTextContent("Running: 3");
    const transcript = screen.getByTestId("messages");
    expect(transcript.querySelector("[data-subagent-results]")).toBeNull();
    expect(transcript).not.toHaveTextContent("Config check");
    expect(transcript).not.toHaveTextContent("Waiting check");
    expect(transcript).not.toHaveTextContent("Stopping check");

    emitTask(task({ revision: 2, result: "Full findings stay in details" }));
    const archive = screen.getByRole("region", { name: "Subtasks" });
    expect(summary(archive)).toHaveTextContent("Completed: 1");
    expect(summary(archive).querySelector("img")).toHaveAttribute("src", "/brand/nanobot_mark.svg");
    expect(summary(archive).querySelector("img")).toHaveAttribute("alt", "");
    expect(summary(archive)).toHaveAttribute("aria-expanded", "false");
    await user.click(summary(archive));
    expect(within(archive).getByRole("button", { name: "Config check Completed 4s" })).toBeVisible();
    expect(within(archive).getAllByRole("listitem")).toHaveLength(1);
    expect(transcript).not.toHaveTextContent("Waiting check");
    expect(transcript).not.toHaveTextContent("Stopping check");
    expect(transcript).not.toHaveTextContent("Full findings stay in details");
  });

  it("counts finished work truthfully and keeps cancellation distinct from failures", async () => {
    vi.mocked(fetch).mockImplementation(async () => response([
      task({ task_id: "cancelled", label: "Cancelled check", state: "cancelled", created_at: 102 }),
      task({ task_id: "interrupted", label: "Interrupted check", state: "interrupted", created_at: 104 }),
      task({ task_id: "incomplete", label: "Incomplete check", state: "incomplete", created_at: 103 }),
      task({ task_id: "failed", label: "Failed check", state: "error", error: "Unreadable file", created_at: 101 }),
      task(),
    ]));
    const user = userEvent.setup();
    render(layout());
    const archive = await screen.findByRole("region", { name: "Subtasks" });
    const header = summary(archive);
    expect(header).toHaveTextContent("Finished: 5");
    expect(header).toHaveTextContent("Review needed: 3");
    expect(header).not.toHaveTextContent("Completed: 5");
    await user.click(header);
    expect(within(archive).getByRole("button", { name: "Cancelled check Cancelled 4s" })).toBeVisible();
    expect(within(archive).getByRole("button", { name: "Failed check Failed 4s" })).toBeVisible();
    expect(within(archive).getByRole("button", { name: "Incomplete check Incomplete 4s" })).toBeVisible();
    expect(within(archive).getByRole("button", { name: "Interrupted check Interrupted 4s" })).toBeVisible();
    expect([...archive.querySelectorAll("[data-subagent-id]")].map((row) => row.getAttribute("data-subagent-id")))
      .toEqual(["task-1", "failed", "cancelled", "incomplete", "interrupted"]);
    await user.click(within(archive).getByRole("button", { name: "Failed check Failed 4s" }));
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

  it("resets task disclosures across sessions without remounting the outgoing transcript", async () => {
    vi.mocked(fetch).mockImplementation(async (input) => response([
      task(String(input).includes("websocket%3Ab") ? { task_id: "task-b", label: "Other check" } : {}),
    ]));
    const user = userEvent.setup();
    const view = render(layout());
    const archive = await screen.findByRole("region", { name: "Subtasks" });
    await user.click(summary(archive));
    expect(summary(archive)).toHaveAttribute("aria-expanded", "true");
    const outgoingPrompt = screen.getByText("Inspect config");

    // The selected session changes before useNanobotStream hands over its messages.
    view.rerender(layout({ sessionKey: "websocket:b" }));
    expect(screen.getByText("Inspect config")).toBe(outgoingPrompt);
    const other = await screen.findByRole("region", { name: "Subtasks" });
    expect(summary(other)).toHaveAttribute("aria-expanded", "false");
    await user.click(summary(other));
    expect(within(other).getByRole("button", { name: "Other check Completed 4s" })).toBeVisible();

    view.rerender(layout({ sessionKey: "websocket:b", threadMessages: [
      { ...messages[0], id: "prompt-b", content: "Other request" },
      { ...messages[1], id: "answer-b", content: "Other answer" },
    ] }));
    expect(await screen.findByText("Other answer")).toBeVisible();
    expect(summary(screen.getByRole("region", { name: "Subtasks" }))).toHaveAttribute("aria-expanded", "true");

    view.rerender(layout());
    const restored = await screen.findByRole("region", { name: "Subtasks" });
    expect(summary(restored)).toHaveAttribute("aria-expanded", "false");
    await user.click(summary(restored));
    expect(within(restored).getByRole("button", { name: "Config check Completed 4s" })).toBeVisible();
    view.rerender(layout({ sessionKey: "websocket:b" }));
    expect(summary(await screen.findByRole("region", { name: "Subtasks" }))).toHaveAttribute("aria-expanded", "false");
    view.rerender(layout());
    expect(summary(await screen.findByRole("region", { name: "Subtasks" }))).toHaveAttribute("aria-expanded", "false");
  });

  it("prefers the exact initiating prompt and falls back once to the first user message of its turn", async () => {
    vi.mocked(fetch).mockImplementation(async () => response([
      task({ task_id: "exact", label: "Exact check", origin_message_id: "followup", created_at: 101 }),
      task({ task_id: "fallback", label: "Turn fallback", origin_message_id: "replayed-original-id" }),
    ]));
    const user = userEvent.setup();
    render(layout({ threadMessages: [
      ...messages,
      { id: "followup", role: "user", content: "Check the follow-up", turnId: "turn-a", createdAt: 102_000 },
      { id: "followup-answer", role: "assistant", content: "Follow-up answer", turnId: "turn-a", createdAt: 103_000 },
    ] }));
    const archives = await screen.findAllByRole("region", { name: "Subtasks" });
    expect(archives).toHaveLength(2);
    expectBefore(screen.getByText("Inspect config"), archives[0]);
    expectBefore(archives[0], screen.getByText("Main answer"));
    expectBefore(screen.getByText("Check the follow-up"), archives[1]);
    expectBefore(archives[1], screen.getByText("Follow-up answer"));
    await user.click(summary(archives[0]));
    await user.click(summary(archives[1]));
    expect(within(archives[0]).getByRole("button", { name: "Turn fallback Completed 4s" })).toBeVisible();
    expect(within(archives[1]).getByRole("button", { name: "Exact check Completed 4s" })).toBeVisible();
    expect(screen.getByTestId("messages").querySelectorAll("[data-subagent-id]")).toHaveLength(2);
  });

  it.each([
    { name: "loaded", threadMessages: [messages[0]], turnIds: ["turn-a"] },
    { name: "empty", threadMessages: [], turnIds: [] },
  ])("reads the $name history window while keeping active tasks available", async ({ threadMessages, turnIds }) => {
    const old: UIMessage = { id: "old", role: "user", content: "Earlier prompt", turnId: "old", createdAt: 99_000 };
    const seen: URL[] = [];
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = new URL(String(input), "http://localhost");
      seen.push(url);
      return response([
        task({ task_id: "live", label: "Live", state: "running", completed_at: null, origin_message_id: "elsewhere", origin_turn_id: "elsewhere" }),
        ...(url.searchParams.getAll("turn_id").includes("old")
          ? [task({ task_id: "old", label: "Earlier check", origin_message_id: "old", origin_turn_id: "old" })] : []),
      ]);
    });
    const user = userEvent.setup();
    const view = render(layout({ threadMessages }));
    expect(await screen.findByTestId("subagent-task-dock-trigger")).toHaveTextContent("Running: 1");
    expect(screen.getByTestId("messages").querySelector("[data-subagent-results]")).toBeNull();
    expect(seen[0].searchParams.get("scope")).toBe("window");
    expect(seen[0].searchParams.getAll("turn_id")).toEqual(turnIds);
    view.rerender(layout({ threadMessages: [old, messages[0]] }));
    const archive = await screen.findByRole("region", { name: "Subtasks" });
    await user.click(summary(archive));
    expect(within(archive).getByRole("button", { name: /Earlier check/ })).toBeVisible();
    expect(seen.some((url) => url.searchParams.getAll("turn_id").includes("old"))).toBe(true);
    expect(screen.getByTestId("subagent-task-dock-trigger")).toHaveTextContent("Running: 1");
  });

  it("coalesces window changes and refreshes while reads are in flight, retaining the newest task revision", async () => {
    const first = messages[0];
    const second: UIMessage = { id: "second", role: "user", content: "Second prompt", turnId: "turn-second", createdAt: 1 };
    const seen: URL[] = [];
    let resolveFirst!: (response: Response) => void;
    let resolveSecond!: (response: Response) => void;
    const running = task({ state: "running", completed_at: null, origin_message_id: "elsewhere", origin_turn_id: "elsewhere" });
    vi.mocked(fetch).mockImplementation((input) => {
      seen.push(new URL(String(input), "http://localhost"));
      if (seen.length === 1) return new Promise<Response>((resolve) => { resolveFirst = resolve; });
      if (seen.length === 2) return new Promise<Response>((resolve) => { resolveSecond = resolve; });
      return Promise.resolve(response([task({ revision: 3, label: "Live revision 3", origin_message_id: "elsewhere", origin_turn_id: "elsewhere" })]));
    });
    const tree = (threadMessages: UIMessage[], active = true) => <StrictMode>{layout({ threadMessages, active })}</StrictMode>;
    const view = render(tree([first]));
    await waitFor(() => expect(seen).toHaveLength(1));
    view.rerender(tree([second]));
    fireEvent(window, new Event("focus"));
    expect(seen).toHaveLength(1);
    emitTask({ ...running, revision: 2, label: "Live revision 2" });
    await act(async () => resolveFirst(response([running])));
    await waitFor(() => expect(seen).toHaveLength(2));
    expect(seen[1].searchParams.getAll("turn_id")).toEqual(["turn-second"]);
    expect(seen[1].searchParams.getAll("track")).toEqual(["task-1"]);
    const user = userEvent.setup();
    await user.click(screen.getByTestId("subagent-task-dock-trigger"));
    expect(screen.getByRole("button", { name: /Live revision 2 Running/ })).toBeVisible();
    view.rerender(tree([first]));
    await act(async () => resolveSecond(response([running])));
    // Focus invalidated the first page while its original read was in flight;
    // revisiting it must not treat that old response as fresh.
    await waitFor(() => expect(seen).toHaveLength(3));
    expect(seen[2].searchParams.getAll("turn_id")).toEqual(["turn-a"]);
    expect(seen[2].searchParams.getAll("track")).toEqual(["task-1"]);
    expect(await screen.findByRole("button", { name: /Live revision 3 Completed/ })).toBeVisible();
    act(() => statusHandlers.forEach((handler) => handler("open")));
    await waitFor(() => expect(seen).toHaveLength(4));
    expect(seen[3].searchParams.getAll("turn_id")).toEqual(["turn-a"]);
    expect(seen[3].searchParams.getAll("track")).toEqual([]);
    fireEvent(window, new Event("focus"));
    await waitFor(() => expect(seen).toHaveLength(5));
    expect(seen[4].searchParams.getAll("turn_id")).toEqual(["turn-a"]);
    view.rerender(tree([first], false));
    view.rerender(tree([first]));
    await waitFor(() => expect(seen).toHaveLength(6));
    expect(seen[5].searchParams.getAll("turn_id")).toEqual(["turn-a"]);
  });

  it("retries a failed history page when revisited without rereading a cached page", async () => {
    const first = messages[0];
    const second: UIMessage = { id: "second", role: "user", content: "Second prompt", turnId: "turn-second", createdAt: 1 };
    const seen: URL[] = [];
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = new URL(String(input), "http://localhost");
      seen.push(url);
      if (seen.length === 2) return new Response("unavailable", { status: 503 });
      return response(url.searchParams.getAll("turn_id").includes("turn-second")
        ? [task({ origin_message_id: "second", origin_turn_id: "turn-second", label: "Recovered result" })] : []);
    });
    const view = render(layout({ threadMessages: [first] }));
    await waitFor(() => expect(seen).toHaveLength(1));
    view.rerender(layout({ threadMessages: [second] }));
    await waitFor(() => expect(seen).toHaveLength(2));
    view.rerender(layout({ threadMessages: [first] }));
    await act(async () => { await Promise.resolve(); });
    expect(seen).toHaveLength(2);
    view.rerender(layout({ threadMessages: [second] }));
    const archive = await screen.findByRole("region", { name: "Subtasks" });
    await userEvent.setup().click(summary(archive));
    expect(within(archive).getByRole("button", { name: /Recovered result/ })).toBeVisible();
    expect(seen).toHaveLength(3);
    expect(seen[2].searchParams.getAll("turn_id")).toEqual(["turn-second"]);
  });

  it("revalidates a cached off-window page after reconnect misses a completed task", async () => {
    const first = messages[0];
    const second: UIMessage = { id: "second", role: "user", content: "Second prompt", turnId: "turn-second", createdAt: 1 };
    const seen: URL[] = [];
    let completedWhileOffline = false;
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = new URL(String(input), "http://localhost");
      seen.push(url);
      return response(completedWhileOffline && url.searchParams.getAll("turn_id").includes("turn-a")
        ? [task({ origin_message_id: "prompt-a", label: "Completed while offline" })] : []);
    });
    const view = render(layout({ threadMessages: [first] }));
    await waitFor(() => expect(seen).toHaveLength(1));
    view.rerender(layout({ threadMessages: [second] }));
    await waitFor(() => expect(seen).toHaveLength(2));
    completedWhileOffline = true;
    act(() => statusHandlers.forEach((handler) => handler("open")));
    await waitFor(() => expect(seen).toHaveLength(3));
    expect(seen[2].searchParams.getAll("turn_id")).toEqual(["turn-second"]);
    view.rerender(layout({ threadMessages: [first] }));
    const archive = await screen.findByRole("region", { name: "Subtasks" });
    await userEvent.setup().click(summary(archive));
    expect(within(archive).getByRole("button", { name: /Completed while offline/ })).toBeVisible();
    expect(seen[3].searchParams.getAll("turn_id")).toEqual(["turn-a"]);
  });

  it("does not let an old session's delayed scoped read contaminate the new session", async () => {
    let resolveOld!: (response: Response) => void;
    const seen: URL[] = [];
    vi.mocked(fetch).mockImplementation((input) => {
      const url = new URL(String(input), "http://localhost");
      seen.push(url);
      if (url.pathname.includes("websocket%3Aa")) return new Promise<Response>((resolve) => { resolveOld = resolve; });
      return Promise.resolve(response([task({ task_id: "new", label: "New session", state: "running", completed_at: null })]));
    });
    const view = render(layout());
    await waitFor(() => expect(resolveOld).toBeTypeOf("function"));
    view.rerender(layout({ sessionKey: "websocket:b" }));
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("subagent-task-dock-trigger"));
    expect(await screen.findByRole("button", { name: /New session Running/ })).toBeVisible();
    await act(async () => resolveOld(response([task({ label: "Old session", state: "running", completed_at: null })])));
    expect(screen.queryByRole("button", { name: /Old session/ })).not.toBeInTheDocument();
    expect(seen).toHaveLength(2);
  });

  it("reconciles a previously active off-window task after focus", async () => {
    const seen: URL[] = [];
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = new URL(String(input), "http://localhost");
      seen.push(url);
      return response(url.searchParams.getAll("track").includes("task-1")
        ? [task({ revision: 2, origin_message_id: "other", origin_turn_id: "other" })]
        : [task({ state: "running", completed_at: null, origin_message_id: "other", origin_turn_id: "other" })]);
    });
    render(layout({ threadMessages: [messages[0]] }));
    expect(await screen.findByTestId("subagent-task-dock-trigger")).toHaveTextContent("Running: 1");
    act(() => { window.dispatchEvent(new Event("focus")); });
    await waitFor(() => expect(seen.some((url) => url.searchParams.getAll("track").includes("task-1"))).toBe(true));
    await waitFor(() => expect(screen.getByTestId("subagent-task-dock-trigger")).toHaveTextContent("Completed: 1"));
    expect(screen.getByTestId("messages").querySelector("[data-subagent-results]")).toBeNull();
  });

  it("shows older results only with their loaded prompt and preserves details through history navigation", async () => {
    vi.mocked(fetch).mockImplementation(async () => response([
      task({ task_id: "older", label: "Earlier check", origin_turn_id: "older-turn", origin_message_id: "older-prompt",
        result: "## Earlier findings\n\nThe saved result remains available" }),
      task({ task_id: "unlinked-active", label: "Unlinked live check", state: "running", completed_at: null,
        origin_message_id: null, origin_turn_id: null, created_at: 200 }),
    ]));
    const user = userEvent.setup();
    const view = render(layout());
    expect(await screen.findByTestId("subagent-task-dock-trigger")).toHaveTextContent("Running: 1");
    expect(screen.getByTestId("messages").querySelector("[data-subagent-results]")).toBeNull();
    const olderMessages: UIMessage[] = [
      { id: "older-prompt", role: "user", content: "Inspect earlier work", turnId: "older-turn", createdAt: 99_000 },
      ...messages,
    ];
    view.rerender(layout({ threadMessages: olderMessages }));
    let linked = screen.getByRole("region", { name: "Subtasks" });
    expect(summary(linked)).toHaveAttribute("aria-expanded", "false");
    await user.click(summary(linked));
    await user.click(within(linked).getByRole("button", { name: "Earlier check Completed 4s" }));
    const detail = screen.getByRole("dialog", { name: "Earlier check" });
    expect(await within(detail).findByRole("heading", { name: "Earlier findings" })).toBeVisible();
    view.rerender(layout());
    expect(screen.getByTestId("messages").querySelector("[data-subagent-results]")).toBeNull();
    expect(within(detail).getByText("The saved result remains available")).toBeVisible();
    view.rerender(layout({ threadMessages: olderMessages }));
    await user.keyboard("{Escape}");
    linked = screen.getByRole("region", { name: "Subtasks" });
    expect(summary(linked)).toHaveAttribute("aria-expanded", "true");
    await waitFor(() => expect(within(linked).getByRole("button", { name: "Earlier check Completed 4s" })).toHaveFocus());
    expect(screen.getByTestId("messages").querySelectorAll('[data-subagent-id="older"]')).toHaveLength(1);
    expectBefore(screen.getByText("Inspect earlier work"), linked);
    expectBefore(linked, screen.getByText("Inspect config"));
    expect(within(linked).getByRole("button", { name: "Earlier check Completed 4s" })).toBeVisible();
    expect(requestMutation).not.toHaveBeenCalled();
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

  it("preserves disclosure through off-page task outcomes, history prepends and Activity preference changes", async () => {
    act(() => { writeLocalPreferences({ ...DEFAULT_LOCAL_PREFS, activityMode: "expanded" }); });
    vi.mocked(fetch).mockImplementation(async () => response([
      task(),
      task({ task_id: "second", label: "Second check", created_at: 101 }),
      task({ task_id: "other", label: "Other check", state: "running", completed_at: null, origin_message_id: null, origin_turn_id: null, created_at: 102 }),
    ]));
    const user = userEvent.setup();
    const view = render(layout());
    const archive = await screen.findByRole("region", { name: "Subtasks" });
    expect(summary(archive)).toHaveAttribute("aria-expanded", "false");
    await user.click(summary(archive));
    act(() => { writeLocalPreferences(DEFAULT_LOCAL_PREFS); });
    expect(summary(archive)).toHaveAttribute("aria-expanded", "true");

    emitTask(task({ task_id: "other", label: "Other check", revision: 2, state: "error", error: "Other work failed",
      origin_message_id: null, origin_turn_id: null, created_at: 102 }));
    expect(summary(archive)).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("messages").querySelector('[data-subagent-id="other"]')).toBeNull();
    view.rerender(layout({ threadMessages: [
      { id: "prepended", role: "user", content: "Earlier request from this turn", turnId: "turn-a", createdAt: 99_000 },
      ...messages,
    ] }));
    const retained = screen.getByRole("region", { name: "Subtasks" });
    expect(summary(retained)).toHaveAttribute("aria-expanded", "true");
    expect(within(retained).getByRole("button", { name: "Config check Completed 4s" })).toBeVisible();
    expect([...retained.querySelectorAll("[data-subagent-id]")].map((row) => row.getAttribute("data-subagent-id")))
      .toEqual(["task-1", "second"]);
    await user.click(summary(retained));
    act(() => { writeLocalPreferences({ ...DEFAULT_LOCAL_PREFS, activityMode: "expanded" }); });
    expect(summary(retained)).toHaveAttribute("aria-expanded", "false");
    expect(within(retained).queryByRole("button", { name: "Config check Completed 4s" })).not.toBeInTheDocument();
  });
});
