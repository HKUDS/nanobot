import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";

import App from "@/App";
import i18n from "@/i18n";
import { clearReloadCache } from "@/lib/reload-cache";
import type { InboundEvent, Outbound, ThreadProjectionEvent } from "@/lib/types";
import { webuiThreadCache } from "@/lib/webui-thread-cache";

vi.mock("@/lib/bootstrap", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/bootstrap")>(),
  fetchBootstrap: vi.fn(async () => ({ token: "test", api_token: "test", ws_path: "/" })),
  deriveWsUrl: () => "ws://test",
}));

const NATIVE_ID = "123:topic:5"; // Deliberately shares the raw address suffix of the first topic.
const NATIVE_KEY = `websocket:${NATIVE_ID}`;
const CATS = { key: "telegram:123:topic:5", id: "channel.dGVsZWdyYW06MTIzOnRvcGljOjU", handle: "cats" };
const DOGS = { key: "telegram:123:topic:6", id: "channel.dGVsZWdyYW06MTIzOnRvcGljOjY", handle: "dogs" };
const WORK = { key: "discord:123", id: "channel.ZGlzY29yZDoxMjM", handle: "work" };
const timestamp = "2026-09-01T00:00:00Z";

class TestSocket {
  static current: TestSocket;
  readyState = 0;
  sent: Outbound[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;

  constructor() { TestSocket.current = this; }
  open() { this.readyState = 1; this.onopen?.(); }
  close() { this.readyState = 3; this.onclose?.(); }
  receive(event: InboundEvent) {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(event) }));
  }
  send(data: string) {
    const frame = JSON.parse(data) as Outbound;
    this.sent.push(frame);
    if (frame.type === "attach") {
      queueMicrotask(() => this.receive({ event: "attached", chat_id: frame.chat_id }));
    }
  }
}

function channelTurn(chatId: string, id: string, input: string, answer: string, entryChannel?: string): ThreadProjectionEvent[] {
  // Channel history is built from stored input/output records, not live deltas.
  const web = entryChannel === "WebUI";
  const inputId = `user:${id}`;
  return [
    { chat_id: chatId, event: "user_message", text: input, starts_turn: true, input_id: inputId,
      projection_id: `${id}:input`, ...(web ? { turn_id: id, turn_phase: "user" } : {}), entry_channel: entryChannel },
    { chat_id: chatId, event: "message", text: answer, response_input_ids: [inputId],
      projection_id: `${id}:answer`, ...(web ? { turn_id: id, turn_phase: "answer" } : {}), entry_channel: entryChannel },
  ];
}

function post(...frames: InboundEvent[]) {
  act(() => { for (const frame of frames) TestSocket.current.receive(frame); });
}

const thread = () => within(screen.getByTestId("thread-message-region"));
const sidebar = () => within(screen.getByRole("navigation", { name: "Sidebar navigation" }));
const historyPath = (key: string) => `/api/sessions/${encodeURIComponent(key)}/webui-thread`;
let recorded: Map<string, ThreadProjectionEvent[]>;
let historyReads: string[];

beforeAll(async () => { await import("@/components/thread/ThreadShell"); });
beforeEach(async () => {
  await i18n.changeLanguage("en");
  localStorage.clear();
  sessionStorage.clear();
  window.history.replaceState(null, "", `/#/chat/${encodeURIComponent(NATIVE_KEY)}`);
  vi.stubGlobal("WebSocket", TestSocket);
  historyReads = [];
  recorded = new Map([
    [NATIVE_KEY, [{ chat_id: NATIVE_ID, event: "message", text: "Native answer" }]],
    [CATS.key, [
      ...channelTurn(CATS.id, "legacy-turn", "An old prompt", "An old, unlabeled answer"),
      ...channelTurn(CATS.id, "cats-turn", "Cat topic prompt", "Cat topic answer", "Telegram"),
    ]],
    [DOGS.key, channelTurn(DOGS.id, "dogs-turn", "Dog topic prompt", "Dog topic answer", "Telegram")],
    [WORK.key, channelTurn(WORK.id, "work-turn", "Work prompt", "Work answer", "Discord")],
  ]);
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input).split("?")[0];
    if (path === "/api/sessions") return Response.json({ sessions: [
      { key: NATIVE_KEY, title: "Native topic", created_at: timestamp, updated_at: timestamp },
      ...[CATS, DOGS, WORK].map((session, index) => ({
        key: session.key, chat_id: session.id,
        title: session === WORK ? "Discord" : "Telegram",
        handle: { id: `handle_${String(index).padStart(32, "0")}`, name: session.handle },
        created_at: timestamp, updated_at: timestamp,
        workspace_scope: { project_path: "/workspace", access_mode: "restricted", restrict_to_workspace: true },
      })),
    ] });
    if (path === "/api/webui/sidebar-state") return Response.json({});
    for (const [key, events] of recorded) {
      if (path !== historyPath(key)) continue;
      historyReads.push(key);
      return Response.json({ schemaVersion: 3, projection: "events", sessionKey: key, events,
        has_pending_tool_calls: false,
        completed_turn_ids: events.flatMap((event) => event.event === "message" && event.turn_id ? [event.turn_id] : []),
      });
    }
    return new Response(null, { status: 404 });
  }));
});
afterEach(() => {
  cleanup();
  clearReloadCache();
  webuiThreadCache.clear();
  vi.unstubAllGlobals();
});

it("opens channel topics by canonical key, streams WebUI sends by alias, and reloads channel-origin turns", async () => {
  const app = render(<App />);
  await screen.findByText("Native answer");
  act(() => TestSocket.current.open());
  expect(sidebar().getByRole("button", { name: "@work Discord" })).toBeInTheDocument();
  await userEvent.click(sidebar().getByRole("button", { name: "@dogs Telegram" }));
  expect(await thread().findByText("Dog topic answer")).toBeInTheDocument();
  await userEvent.click(sidebar().getByRole("button", { name: "@cats Telegram" }));
  expect(await thread().findByText("Cat topic answer")).toBeInTheDocument();
  expect(thread().getByText("An old, unlabeled answer")).toBeInTheDocument();
  expect(thread().getAllByText("Telegram")).toHaveLength(2);
  expect(window.location.hash).toBe(`#/chat/${encodeURIComponent(CATS.key)}`);
  expect(historyReads).toEqual(expect.arrayContaining([NATIVE_KEY, CATS.key, DOGS.key]));
  expect(TestSocket.current.sent).toEqual(expect.arrayContaining([
    { type: "attach", chat_id: CATS.id }, { type: "attach", chat_id: DOGS.id },
  ]));

  const text = "Compare @dogs with @cats";
  fireEvent.change(screen.getByRole("textbox", { name: "Message input" }), { target: { value: text } });
  await userEvent.click(screen.getByRole("button", { name: "Send message" }));
  const sent = TestSocket.current.sent.find((frame) => frame.type === "message" && frame.content === text);
  expect(sent).toMatchObject({ type: "message", chat_id: CATS.id, content: text,
    session_mentions: [{ session_key: DOGS.key, title: "Telegram", name: "dogs" }] });
  expect(sent).not.toHaveProperty("workspace_scope");
  if (sent?.type !== "message" || !sent.turn_id) throw new Error("Missing WebUI turn");
  const web = { chat_id: CATS.id, turn_id: sent.turn_id };
  post(
    { ...web, event: "user_message", starts_turn: true, text, entry_channel: "WebUI", turn_seq: 0, input_id: `user:${sent.turn_id}` },
    { ...web, event: "delta", text: "Live WebUI answer", entry_channel: "WebUI", turn_seq: 1 },
  );
  expect(await thread().findByText("Live WebUI answer")).toBeInTheDocument();
  expect(thread().getAllByText("WebUI")).toHaveLength(2);
  post({ ...web, event: "turn_end", turn_seq: 2 });
  recorded.get(CATS.key)!.push(...channelTurn(CATS.id, sent.turn_id, text, "Live WebUI answer", "WebUI"));

  post({ event: "goal_status", chat_id: CATS.id, status: "running", started_at: Date.now() / 1000 });
  expect(await screen.findByRole("button", { name: "Stop response" })).toBeEnabled();
  recorded.get(CATS.key)!.push(...channelTurn(CATS.id, "from-telegram", "From Telegram", "Reloaded Telegram answer", "Telegram"));
  post(
    { event: "goal_status", chat_id: CATS.id, status: "idle" },
    { event: "session_updated", chat_id: CATS.id, scope: "thread" },
  );
  expect(await thread().findByText("Reloaded Telegram answer")).toBeInTheDocument();
  expect(thread().getAllByText("Live WebUI answer")).toHaveLength(1);

  post({ event: "goal_status", chat_id: CATS.id, status: "running", started_at: Date.now() / 1000 });
  await userEvent.click(await screen.findByRole("button", { name: "Stop response" }));
  expect(TestSocket.current.sent).toContainEqual({ type: "message", chat_id: CATS.id, content: "/stop", webui: true });

  app.unmount();
  const readsBeforeReload = historyReads.length;
  render(<App />);
  expect(await screen.findByText("Reloaded Telegram answer")).toBeInTheDocument();
  await waitFor(() => expect(historyReads.slice(readsBeforeReload)).toContain(CATS.key));
  expect(window.location.hash).toBe(`#/chat/${encodeURIComponent(CATS.key)}`);
});

it("offers only sidebar actions for a channel topic and excludes it from native bulk selection", async () => {
  const user = userEvent.setup();
  render(<App />);
  const catRow = (await screen.findByRole("button", { name: "@cats Telegram" })).closest("[data-chat-row]")!;
  await user.click(within(catRow as HTMLElement).getByRole("button", { name: "Topic actions for Telegram" }));
  expect((await screen.findAllByRole("menuitem")).map((item) => item.textContent)).toEqual(["Pin", "Archive"]);
  await user.keyboard("{Escape}");
  await user.click(sidebar().getByRole("button", { name: "Topic actions for Native topic" }));
  await user.click(await screen.findByRole("menuitem", { name: "Select" }));
  expect(sidebar().getByRole("button", { name: "@cats Telegram" })).toBeDisabled();
  expect(sidebar().getByRole("button", { name: "Native topic" })).toHaveAttribute("aria-pressed", "true");
});

it("reattaches an inactive channel by alias and reconciles its missed history under the canonical key", async () => {
  render(<App />);
  await screen.findByText("Native answer");
  act(() => TestSocket.current.open());
  await userEvent.click(sidebar().getByRole("button", { name: "@cats Telegram" }));
  await screen.findByText("Cat topic answer");
  post({ event: "goal_status", chat_id: CATS.id, status: "running", started_at: Date.now() / 1000 });
  await screen.findByRole("button", { name: "Stop response" });
  await userEvent.click(sidebar().getByRole("button", { name: "@dogs Telegram" }));
  await screen.findByText("Dog topic answer");

  const disconnected = TestSocket.current;
  act(() => disconnected.close());
  recorded.get(CATS.key)!.push(...channelTurn(CATS.id, "during-outage", "Outage prompt", "Outage answer", "Telegram"));
  const readsBeforeReconnect = historyReads.length;
  await waitFor(() => expect(TestSocket.current).not.toBe(disconnected));
  act(() => TestSocket.current.open());
  expect(TestSocket.current.sent).toContainEqual({ type: "attach", chat_id: CATS.id });
  await waitFor(() => expect(historyReads.slice(readsBeforeReconnect)).toContain(CATS.key));
  expect(thread().getByText("Dog topic answer")).toBeInTheDocument();
  await userEvent.click(sidebar().getByRole("button", { name: "@cats Telegram" }));
  expect(await thread().findByText("Outage answer")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Stop response" })).not.toBeInTheDocument();
});
