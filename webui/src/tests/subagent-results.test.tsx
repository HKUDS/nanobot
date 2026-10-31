import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SubagentTaskDock } from "@/components/thread/SubagentTaskDock";
import { SubagentThreadMessages, useHasSubagentResults } from "@/components/thread/SubagentTaskResults";
import { SubagentTasksProvider } from "@/components/thread/SubagentTasks";
import { setAppLanguage } from "@/i18n";
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
function ResultsPresence() {
  return <output data-testid="has-results">{useHasSubagentResults() ? "yes" : "no"}</output>;
}
function layout({ threadMessages = messages, liveEvents = true, historyEnabled = false, onActivityToggle }: {
  threadMessages?: UIMessage[];
  liveEvents?: boolean;
  historyEnabled?: boolean;
  onActivityToggle?: () => void;
} = {}) {
  return <SubagentTasksProvider client={client} sessionKey="websocket:a" token="tok" enabled liveEvents={liveEvents} historyEnabled={historyEnabled}>
    <ResultsPresence />
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
    expect(screen.getByTestId("has-results")).toHaveTextContent("no");
    expect(transcript).not.toHaveTextContent("Config check");
    expect(transcript).not.toHaveTextContent("Waiting check");
    expect(transcript).not.toHaveTextContent("Stopping check");

    emitTask(task({ revision: 2, result: "Full findings stay in details" }));
    const archive = screen.getByRole("region", { name: "Subtasks" });
    expect(screen.getByTestId("has-results")).toHaveTextContent("yes");
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

  it("keeps unmatched terminal work before the chat and preserves open details when its source is loaded", async () => {
    vi.mocked(fetch).mockImplementation(async () => response([
      task({ task_id: "older", label: "Earlier check", origin_turn_id: "older-turn", origin_message_id: "older-prompt",
        result: "## Earlier findings\n\nThe saved result remains available" }),
      task({ task_id: "unlinked-active", label: "Unlinked live check", state: "running", completed_at: null,
        origin_message_id: null, origin_turn_id: null, created_at: 200 }),
    ]));
    const user = userEvent.setup();
    const view = render(layout());
    const unlinked = await screen.findByRole("region", { name: "Other tasks" });
    expectBefore(unlinked, screen.getByText("Inspect config"));
    expect(summary(unlinked)).toHaveAttribute("aria-expanded", "false");
    await user.click(summary(unlinked));
    expect(within(unlinked).getByText("These tasks have no matching request in the displayed messages.")).toBeVisible();
    expect(unlinked).not.toHaveTextContent("Unlinked live check");
    await user.click(within(unlinked).getByRole("button", { name: "Earlier check Completed 4s" }));
    const detail = screen.getByRole("dialog", { name: "Earlier check" });
    expect(await within(detail).findByRole("heading", { name: "Earlier findings" })).toBeVisible();

    view.rerender(layout({ threadMessages: [
      { id: "older-prompt", role: "user", content: "Inspect earlier work", turnId: "older-turn", createdAt: 99_000 },
      ...messages,
    ] }));
    expect(screen.getByRole("dialog", { name: "Earlier check" })).toBe(detail);
    expect(within(detail).getByText("The saved result remains available")).toBeVisible();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("region", { name: "Other tasks" })).not.toBeInTheDocument();
    const linked = screen.getByRole("region", { name: "Subtasks" });
    const header = summary(linked);
    expect(header).toHaveAttribute("aria-expanded", "true");
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

  it("preserves each disclosure through other task outcomes, history prepends and Activity preference changes", async () => {
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
    const unlinked = screen.getByRole("region", { name: "Other tasks" });
    expect(summary(unlinked)).toHaveAttribute("aria-expanded", "false");
    await user.click(summary(unlinked));
    view.rerender(layout({ threadMessages: [
      { id: "prepended", role: "user", content: "Earlier request from this turn", turnId: "turn-a", createdAt: 99_000 },
      ...messages,
    ] }));
    const retained = screen.getByRole("region", { name: "Subtasks" });
    expect(summary(retained)).toHaveAttribute("aria-expanded", "true");
    expect(within(retained).getByRole("button", { name: "Config check Completed 4s" })).toBeVisible();
    expect([...retained.querySelectorAll("[data-subagent-id]")].map((row) => row.getAttribute("data-subagent-id")))
      .toEqual(["task-1", "second"]);
    expect(summary(screen.getByRole("region", { name: "Other tasks" }))).toHaveAttribute("aria-expanded", "true");
    await user.click(summary(retained));
    act(() => { writeLocalPreferences({ ...DEFAULT_LOCAL_PREFS, activityMode: "expanded" }); });
    expect(summary(retained)).toHaveAttribute("aria-expanded", "false");
    expect(within(retained).queryByRole("button", { name: "Config check Completed 4s" })).not.toBeInTheDocument();
  });
});
