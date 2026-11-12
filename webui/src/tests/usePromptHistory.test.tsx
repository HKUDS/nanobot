import { act, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { createRef, type ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { usePromptHistory } from "@/hooks/usePromptHistory";
import * as api from "@/lib/api";
import { NanobotClient } from "@/lib/nanobot-client";
import { ClientProvider } from "@/providers/ClientProvider";
import { getSessionStore } from "@/lib/session-store";
import { PromptReadingPositionStore, type PromptPageQuery } from "@/lib/prompt-reading-position";
import type { PromptIndex, UIMessage, WebuiThreadPersistedPayload } from "@/lib/types";
import { ThreadViewport, type ThreadViewportHandle } from "@/components/thread/ThreadViewport";
import { projectThreadEvents } from "@/lib/thread-event-projection";
import { projectWebuiThreadMessages } from "@/lib/thread-display-projection";

vi.mock("@/lib/api", async (original) => ({ ...await original<typeof api>(), fetchPromptIndex: vi.fn(), fetchWebuiThread: vi.fn() }));
const index = Array.from({ length: 2000 }, (_, index) => ({ id: `u${index}`, preview: `question ${index}`,
  answerPreview: "answer", createdAt: index + 1, cursor: String(index), turnId: `turn${index}` }));
const latest: UIMessage[] = [{ id: "u1999", content: "question 1999", role: "user", createdAt: 2000 }];
function page(start: number): WebuiThreadPersistedPayload {
  return { schemaVersion: 3, projection: "events", events: [
    { event: "user_message", chat_id: "a", projection_id: `u${start}`, text: `question ${start}`, starts_turn: true },
    { event: "message", chat_id: "a", projection_id: `a${start}`, text: "answer" },
  ], page: { before_cursor: String(start), after_cursor: String(start + 1), user_message_offset: start,
    has_more_before: start > 0, has_more_after: start < 1999 } };
}
function wrapper(enabled = true, client = new NanobotClient({ url: "ws://localhost:8765", reconnect: false })) {
  return ({ children }: { children: ReactNode }) => <ClientProvider client={client} token="test"
    webuiCapabilities={enabled ? ["webui.prompt-navigation.v1"] : []}>{children}</ClientProvider>;
}
beforeEach(() => {
  vi.mocked(api.fetchPromptIndex).mockReset().mockResolvedValue({ prompts: index, revision: "first" });
  vi.mocked(api.fetchWebuiThread).mockReset().mockImplementation(async (_token, _key, options) => {
    if (typeof options === "string") throw new Error("expected page options");
    return page(Number(options?.after ?? Number(options?.before) - 1));
  });
});

it("loads the complete index without bodies, reads bounded windows and leaves live history alone", async () => {
  const { result, rerender } = renderHook(({ messages }) => usePromptHistory("a", 1, messages), {
    wrapper: wrapper(), initialProps: { messages: latest },
  });
  await waitFor(() => expect(result.current.prompts).toHaveLength(2000));
  expect(api.fetchWebuiThread).not.toHaveBeenCalled();
  await act(async () => result.current.jump("u500"));
  expect(result.current.window?.userMessageOffset).toBe(500);
  expect(result.current.target?.id).toBe("u500");
  rerender({ messages: [...latest, { id: "live", role: "assistant", content: "new output", createdAt: 2001 }] });
  expect(result.current.window?.messages).toHaveLength(2);
  for (let i = 0; i < 8; i++) await act(async () => result.current.newer());
  expect(result.current.window?.messages).toHaveLength(6);
  expect(result.current.window?.userMessageOffset).toBe(506);
  await act(async () => result.current.older());
  expect(result.current.window?.userMessageOffset).toBe(505);
  expect(result.current.window?.messages).toHaveLength(6);
  expect(api.fetchWebuiThread).toHaveBeenLastCalledWith("test", "a", expect.objectContaining({ before: "506", limit: 24 }));
  act(() => result.current.latest());
  expect(result.current.window).toBeNull();
  expect(latest).toHaveLength(1);
});

it("reprojects adjacent pages of a long turn when navigating forward", async () => {
  const events = [
    { event: "user_message" as const, chat_id: "a", projection_id: "u10", turn_id: "long", turn_seq: 1, text: "question", starts_turn: true },
    { event: "stream_end" as const, chat_id: "a", projection_id: "answer-1", turn_id: "long", turn_seq: 2, stream_id: "wire", text: "First", resuming: true, merge_next: true },
    { event: "message" as const, chat_id: "a", projection_id: "tool", turn_id: "long", turn_seq: 3, kind: "progress" as const, text: "tool()" },
    { event: "stream_end" as const, chat_id: "a", projection_id: "answer-2", turn_id: "long", turn_seq: 4, stream_id: "wire", text: "First second" },
    { event: "turn_end" as const, chat_id: "a", projection_id: "end", turn_id: "long", turn_seq: 5 },
  ];
  vi.mocked(api.fetchPromptIndex).mockResolvedValue({ prompts: [{ ...index[10], id: "u10", turnId: "long" }] });
  vi.mocked(api.fetchWebuiThread).mockImplementation(async (_token, _key, options) => {
    if (typeof options === "string") throw new Error("expected page options");
    const newer = options?.after === "next";
    return { schemaVersion: 3, projection: "events", events: newer ? events.slice(2) : events.slice(0, 2),
      page: { before_cursor: newer ? "next" : null, after_cursor: newer ? null : "next",
        has_more_before: newer, has_more_after: !newer, truncated_oversized_turn: true,
        record_range: { turn: 0, start: newer ? 2 : 0, end: newer ? 5 : 2 } } };
  });
  const { result } = renderHook(() => usePromptHistory("a", 1, latest), { wrapper: wrapper() });
  await waitFor(() => expect(result.current.prompts[0]?.id).toBe("u10"));
  await act(async () => result.current.jump("u10"));
  await act(async () => result.current.newer());
  const visible = (rows: UIMessage[]) => rows.map((row) => ({
    role: row.role, kind: row.kind, content: row.content, reasoning: row.reasoning, traces: row.traces,
  }));
  expect(visible(result.current.window!.messages)).toEqual(visible(projectWebuiThreadMessages(projectThreadEvents(events))));
  expect(result.current.window?.messages.filter((row) => row.role === "user")).toHaveLength(1);
});

it("continues through telemetry-only fragments until another message is visible", async () => {
  vi.mocked(api.fetchPromptIndex).mockResolvedValue({ prompts: [{ ...index[10], id: "u10", turnId: "long" }] });
  vi.mocked(api.fetchWebuiThread).mockImplementation(async (_token, _key, options) => {
    if (typeof options === "string") throw new Error("expected page options");
    const part = Number(options?.after === "10" ? 0 : options?.after);
    const events = part === 0
      ? [{ event: "user_message" as const, chat_id: "a", projection_id: "u10", turn_id: "long", turn_seq: 1, text: "question", starts_turn: true }]
      : part === 4
        ? [{ event: "message" as const, chat_id: "a", projection_id: "answer", turn_id: "long", turn_seq: 5, text: "Visible answer" }]
        : [{ event: "model_request" as const, chat_id: "a", projection_id: `request-${part}`, turn_id: "long", turn_seq: part + 1,
          request_id: `r${part}`, run_id: "run", sequence: part, phase: "started" as const }];
    return { schemaVersion: 3, projection: "events", events,
      page: { before_cursor: part ? String(part) : null, after_cursor: part < 4 ? String(part + 1) : null,
        has_more_before: part > 0, has_more_after: part < 4, truncated_oversized_turn: true,
        record_range: { turn: 0, start: part, end: part + 1 } } };
  });
  const { result } = renderHook(() => usePromptHistory("a", 1, latest), { wrapper: wrapper() });
  await waitFor(() => expect(result.current.prompts[0]?.id).toBe("u10"));
  await act(async () => result.current.jump("u10"));
  await act(async () => result.current.newer());
  await act(async () => result.current.newer());
  await act(async () => result.current.newer());
  await waitFor(() => expect(result.current.window?.messages.map((row) => row.content)).toContain("Visible answer"));
  expect(api.fetchWebuiThread).toHaveBeenCalledTimes(5);
});

it("does not mix navigation pages from a replaced session", async () => {
  vi.mocked(api.fetchWebuiThread).mockResolvedValueOnce({ ...page(10),
    page: { ...page(10).page, history_generation: "old" } });
  const { result } = renderHook(() => usePromptHistory("a", 1, latest), { wrapper: wrapper() });
  await waitFor(() => expect(result.current.prompts).toHaveLength(2000));
  await act(async () => result.current.jump("u10"));
  vi.mocked(api.fetchWebuiThread).mockResolvedValueOnce({ ...page(11),
    page: { ...page(11).page, history_generation: "new" } });
  await act(async () => result.current.newer());
  expect(result.current.error).toBe("History changed; select the message again");
  expect(result.current.window?.messages.map((message) => message.content)).toEqual(["question 10", "answer"]);
});

it.each(["older", "newer"] as const)("keeps one pending %s page when boundary inputs arrive before the next render", async (operation) => {
  const { result } = renderHook(() => usePromptHistory("a", 1, latest), { wrapper: wrapper() });
  await waitFor(() => expect(result.current.prompts).toHaveLength(2000));
  await act(async () => result.current.jump("u10"));
  let finish!: (body: WebuiThreadPersistedPayload) => void;
  vi.mocked(api.fetchWebuiThread).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  const load = result.current[operation];
  act(() => {
    load();
    load();
  });
  expect(api.fetchWebuiThread).toHaveBeenCalledTimes(2);
  const options = vi.mocked(api.fetchWebuiThread).mock.lastCall?.[2];
  if (typeof options !== "object") throw new Error("expected page options");
  expect(options.signal?.aborted).toBe(false);
  expect(result.current.loading).toBe(true);
  await act(async () => finish(page(operation === "older" ? 9 : 11)));
  expect(result.current.loading).toBe(false);
  expect(result.current.window?.messages).toHaveLength(4);
});

it("keeps the current page on failure and offers retry; superseded jumps and session reads cannot win", async () => {
  const { result, rerender } = renderHook(({ key }) => usePromptHistory(key, 1, latest), {
    wrapper: wrapper(), initialProps: { key: "a" },
  });
  await waitFor(() => expect(result.current.prompts).toHaveLength(2000));
  await act(async () => result.current.jump("u10"));
  vi.mocked(api.fetchWebuiThread).mockRejectedValueOnce(new Error("offline"));
  await act(async () => result.current.jump("u20"));
  expect(result.current.error).toBe("offline");
  expect(result.current.window?.userMessageOffset).toBe(10);
  await act(async () => result.current.retry());
  expect(result.current.window?.userMessageOffset).toBe(20);
  let resolve!: (body: WebuiThreadPersistedPayload) => void;
  vi.mocked(api.fetchWebuiThread).mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
  act(() => result.current.jump("u30"));
  await act(async () => result.current.jump("u40"));
  await act(async () => resolve(page(30)));
  expect(result.current.window?.userMessageOffset).toBe(40);
  vi.mocked(api.fetchWebuiThread).mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
  act(() => result.current.jump("u50"));
  rerender({ key: "b" });
  await act(async () => resolve(page(50)));
  expect(result.current.window).toBeNull();
  expect(result.current.loading).toBe(false);
});

it("does not request new endpoints from an older compatible host", () => {
  const { result } = renderHook(() => usePromptHistory("a", 1, latest), { wrapper: wrapper(false) });
  expect(result.current.prompts[0].id).toBe("u1999");
  expect(api.fetchPromptIndex).not.toHaveBeenCalled();
  expect(api.fetchWebuiThread).not.toHaveBeenCalled();
});

it.each([false, true])("a local jump supersedes a pending history read without discarding the current window (history=%s)", async (history) => {
  const viewport = createRef<ThreadViewportHandle>();
  function Conversation() {
    const navigation = usePromptHistory("a", 1, latest);
    return <ThreadViewport ref={viewport} messages={latest} navigation={navigation} isStreaming={false} />;
  }
  render(<Conversation />, { wrapper: wrapper() });
  await waitFor(() => expect(screen.getByTestId("prompt-rail-scroll")).toBeInTheDocument());
  if (history) {
    await act(async () => viewport.current?.jumpToUserPrompt("u10"));
  }
  const visible = history ? 10 : 1999;
  const body = within(screen.getByTestId("thread-message-region"));
  expect(body.getByText(`question ${visible}`)).toBeInTheDocument();
  let finish!: (body: WebuiThreadPersistedPayload) => void;
  vi.mocked(api.fetchWebuiThread).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  act(() => viewport.current?.jumpToUserPrompt("u20"));
  const options = vi.mocked(api.fetchWebuiThread).mock.lastCall?.[2];
  if (typeof options !== "object") throw new Error("expected history read");
  act(() => viewport.current?.jumpToUserPrompt(`u${visible}`));
  await act(async () => finish(page(20)));
  expect(body.getByText(`question ${visible}`)).toBeInTheDocument();
  expect(body.queryByText("question 20")).not.toBeInTheDocument();
  expect(options.signal?.aborted).toBe(true);
});

it("keeps legacy backfilled and newly sent prompts navigable without a transcript cursor", async () => {
  vi.mocked(api.fetchPromptIndex).mockResolvedValue({ prompts: [] });
  const { result, rerender } = renderHook(({ messages }) => usePromptHistory("a", 1, messages), {
    wrapper: wrapper(), initialProps: { messages: latest },
  });
  await waitFor(() => expect(result.current.prompts[0]?.id).toBe("u1999"));
  rerender({ messages: [...latest, { id: "live-user", role: "user", content: "new question", createdAt: 2001 }] });
  expect(result.current.prompts.map((prompt) => prompt.id)).toEqual(["u1999", "live-user"]);
  act(() => result.current.jump("live-user"));
  expect(api.fetchWebuiThread).not.toHaveBeenCalled();
});

it("reuses the full directory during token updates and conditional revalidation", async () => {
  const user: UIMessage = { id: "live", role: "user", content: "new question", createdAt: 2001 };
  const { result, rerender } = renderHook(({ version, messages }) => usePromptHistory("a", version, messages), {
    wrapper: wrapper(), initialProps: { version: 1, messages: [...latest, user] },
  });
  await waitFor(() => expect(result.current.prompts).toHaveLength(2001));
  const anchors = result.current.prompts;
  for (let chunk = 0; chunk < 100; chunk++) {
    rerender({ version: 1, messages: [...latest, user, { id: "answer", role: "assistant", content: String(chunk), createdAt: 2002 }] });
    expect(result.current.prompts).toBe(anchors);
  }
  expect(api.fetchPromptIndex).toHaveBeenCalledTimes(1);
  rerender({ version: 2, messages: [...latest, user] });
  await waitFor(() => expect(api.fetchPromptIndex).toHaveBeenCalledTimes(2));
  expect(api.fetchPromptIndex).toHaveBeenLastCalledWith("test", "a", expect.any(AbortSignal), { prompts: index, revision: "first" });
  expect(result.current.prompts).toBe(anchors);
});


it("merges a live input by transport identity without adding an anchor or reordering unknown-time prompts", async () => {
  const recovered = [
    { id: "old", preview: "older", answerPreview: "", createdAt: 1000, cursor: "0", turnId: "old-input" },
    { id: "persisted", preview: "same", answerPreview: "answer", createdAt: 0, cursor: "1", turnId: "input" },
  ];
  vi.mocked(api.fetchPromptIndex).mockResolvedValue({ prompts: recovered, revision: "recovered" });
  const users: UIMessage[] = [
    { id: "optimistic", role: "user", content: "same", createdAt: 2000, turnId: "input" },
    { id: "distinct", role: "user", content: "same", createdAt: 3000, turnId: "other-input" },
  ];
  const { result, rerender } = renderHook(({ key, version }) => usePromptHistory(key, version, users), {
    wrapper: wrapper(), initialProps: { key: "a", version: 1 },
  });
  await waitFor(() => expect(result.current.prompts.map((prompt) => prompt.id)).toEqual(["old", "persisted", "distinct"]));
  vi.mocked(api.fetchWebuiThread).mockResolvedValue({ schemaVersion: 3, projection: "events", events: [
    { event: "user_message", chat_id: "a", text: "same", starts_turn: true, projection_id: "persisted", turn_id: "input", created_at_ms: 0 },
    { event: "message", chat_id: "a", text: "answer", projection_id: "answer" },
  ] });
  await act(async () => result.current.jump("persisted"));
  expect(result.current.target?.id).toBe("persisted");
  expect(result.current.window?.messages[0].createdAt).toBe(0);
  rerender({ key: "a", version: 2 });
  await waitFor(() => expect(api.fetchPromptIndex).toHaveBeenCalledTimes(2));
  expect(result.current.prompts.map((prompt) => prompt.id)).toEqual(["old", "persisted", "distinct"]);
  rerender({ key: "b", version: 1 });
  await waitFor(() => expect(api.fetchPromptIndex).toHaveBeenCalledTimes(3));
  expect(result.current.prompts.map((prompt) => prompt.id)).toEqual(["old", "persisted", "distinct"]);
  expect(result.current.window).toBeNull();
  expect(result.current.target).toBeNull();
});


it("keeps the request operation with failures and retries", async () => {
  const { result } = renderHook(() => usePromptHistory("a", 1, latest), { wrapper: wrapper() });
  await waitFor(() => expect(result.current.prompts).toHaveLength(2000));
  let finish!: (body: WebuiThreadPersistedPayload) => void;
  vi.mocked(api.fetchWebuiThread).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  act(() => result.current.jump("u10"));
  expect(result.current.operation).toBe("jump");
  expect(result.current.loading).toBe(true);
  await act(async () => finish(page(10)));
  expect(result.current.operation).toBeNull();

  for (const operation of ["older", "newer"] as const) {
    vi.mocked(api.fetchWebuiThread).mockRejectedValueOnce(new Error("offline"));
    await act(async () => result.current[operation]());
    expect(result.current.operation).toBe(operation);
    expect(result.current.error).toBe("offline");
    await act(async () => result.current.retry());
    expect(result.current.operation).toBeNull();
    expect(result.current.error).toBeNull();
  }
  act(() => result.current.cancel());
  expect(result.current.operation).toBeNull();
});


it("associates live answers and merges the persisted directory by input ID across turns", async () => {
  vi.mocked(api.fetchPromptIndex).mockResolvedValue({ prompts: [], revision: "empty" });
  const users: UIMessage[] = [
    { id: "local-original", inputId: "user:original", role: "user", content: "same", createdAt: 1 },
    { id: "local-session", inputId: "session-message:received", role: "user", content: "same", createdAt: 2 },
  ];
  const { result, rerender } = renderHook(({ messages, version }) => usePromptHistory("a", version, messages), {
    wrapper: wrapper(), initialProps: { messages: users, version: 1 },
  });
  await waitFor(() => expect(result.current.prompts).toHaveLength(2));
  const messages: UIMessage[] = [...users,
    { id: "original-answer", role: "assistant", content: "Original answer", createdAt: 3, responseInputIds: ["user:original"] },
  ];
  rerender({ messages, version: 1 });
  expect(result.current.prompts.map((prompt) => prompt.answerPreview)).toEqual(["Original answer", ""]);
  messages.push({ id: "session-answer", role: "assistant", content: "Session answer", createdAt: 4,
    responseInputIds: ["session-message:received"] });
  rerender({ messages: [...messages], version: 1 });
  expect(result.current.prompts.map((prompt) => prompt.answerPreview)).toEqual(["Original answer", "Session answer"]);
  const persisted = result.current.prompts.map((prompt, index) => ({ ...prompt, id: `persisted-${index}`,
    cursor: String(index), turnId: `execution-${index}` }));
  vi.mocked(api.fetchPromptIndex).mockResolvedValue({ prompts: persisted, revision: "persisted" });
  rerender({ messages, version: 2 });
  await waitFor(() => expect(result.current.prompts.map((prompt) => prompt.id)).toEqual(["persisted-0", "persisted-1"]));
  expect(result.current.prompts.map((prompt) => prompt.answerPreview)).toEqual(["Original answer", "Session answer"]);
});

it("restores the browsing window and conditionally revalidates its own index after A-B-A", async () => {
  const snapshot = { prompts: index, revision: "index-a" };
  vi.mocked(api.fetchPromptIndex).mockResolvedValue(snapshot);
  const { result, rerender } = renderHook(({ key }) => usePromptHistory(key, 1, latest), {
    wrapper: wrapper(), initialProps: { key: "a" },
  });
  await waitFor(() => expect(result.current.prompts).toHaveLength(2000));
  await act(async () => result.current.jump("u500"));
  await act(async () => result.current.older());
  await act(async () => result.current.newer());
  const window = result.current.window?.messages;
  rerender({ key: "b" });
  await waitFor(() => expect(api.fetchPromptIndex).toHaveBeenCalledTimes(2));
  expect(result.current.window).toBeNull();
  await act(async () => rerender({ key: "a" }));
  expect(result.current.window?.messages).toEqual(window);
  expect(api.fetchPromptIndex).toHaveBeenLastCalledWith("test", "a", expect.any(AbortSignal), snapshot);
  expect(api.fetchWebuiThread).toHaveBeenCalledTimes(3);
});


it("refetches the exact last three queries after the heavy window is evicted, without rendering latest", async () => {
  const client = new NanobotClient({ url: "ws://localhost:8765", reconnect: false });
  const sessions = getSessionStore(client);
  const renders: { key: string; ids: string[] | null; loading: boolean }[] = [];
  const { result, rerender } = renderHook(({ key }) => {
    const navigation = usePromptHistory(key, 1, latest);
    renders.push({ key, ids: navigation.window?.messages.map((message) => message.id) ?? null, loading: navigation.loading });
    return navigation;
  }, { wrapper: wrapper(true, client), initialProps: { key: "websocket:a" } });
  await waitFor(() => expect(result.current.prompts).toHaveLength(2000));
  await act(async () => result.current.jump("u500"));
  for (let next = 0; next < 3; next++) await act(async () => result.current.newer());
  await act(async () => result.current.older());
  const original = result.current.window;
  const queries: PromptPageQuery[] = [
    { cursor: "501", direction: "before" },
    { cursor: "501", direction: "after" },
    { cursor: "502", direction: "after" },
  ];
  expect(sessions.navigationPositions.get("websocket:a")?.queries).toEqual(queries);
  for (let session = 1; session <= 13; session++) {
    rerender({ key: `websocket:other-${session}` });
    await waitFor(() => expect(result.current.prompts).toHaveLength(2000));
    await act(async () => result.current.jump("u10"));
  }
  expect(sessions.promptWindows.peek("websocket:a")).toBeUndefined();
  expect(sessions.navigationPositions.get("websocket:a")?.queries).toEqual(queries);
  let finish!: (body: WebuiThreadPersistedPayload) => void;
  vi.mocked(api.fetchWebuiThread).mockClear().mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  // The directory may have changed order while away. Recovery uses opaque GET cursors, not positions in it.
  vi.mocked(api.fetchPromptIndex).mockResolvedValue({ prompts: [...index].reverse(), revision: "reordered" });
  renders.length = 0;
  rerender({ key: "websocket:a" });
  expect(result.current.window?.messages).toEqual([]);
  expect(result.current.loading).toBe(true);
  expect(renders.filter((render) => render.key === "websocket:a").every((render) => render.ids?.length === 0 && render.loading)).toBe(true);
  await act(async () => finish(page(500)));
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.window).toEqual(original);
  expect(api.fetchWebuiThread).toHaveBeenCalledTimes(3);
  for (const [position, query] of queries.entries()) {
    expect(api.fetchWebuiThread).toHaveBeenNthCalledWith(position + 1, "test", "websocket:a",
      expect.objectContaining({ [query.direction]: query.cursor, limit: 24 }));
  }
});

it("recovers a reload-only descriptor, keeps failures empty and retries the original window", async () => {
  const beforeReload = new NanobotClient({ url: "ws://localhost:8765", reconnect: false });
  const source = renderHook(() => usePromptHistory("websocket:a", 1, latest), { wrapper: wrapper(true, beforeReload) });
  await waitFor(() => expect(source.result.current.prompts).toHaveLength(2000));
  await act(async () => source.result.current.jump("u500"));
  await act(async () => source.result.current.older());
  await act(async () => source.result.current.newer());
  const original = source.result.current.window;
  const serialized = JSON.stringify(getSessionStore(beforeReload).navigationPositions.entries());
  source.unmount();

  const client = new NanobotClient({ url: "ws://localhost:8765", reconnect: false });
  const sessions = getSessionStore(client);
  for (const [key, position] of new PromptReadingPositionStore(JSON.parse(serialized)).entries()) sessions.navigationPositions.set(key, position);
  expect(sessions.promptWindows.peek("websocket:a")).toBeUndefined();
  vi.mocked(api.fetchWebuiThread).mockClear().mockRejectedValueOnce(new Error("offline"));
  const { result, unmount } = renderHook(() => usePromptHistory("websocket:a", 1, latest), { wrapper: wrapper(true, client) });
  expect(result.current.window?.messages).toEqual([]);
  await waitFor(() => expect(result.current.error).toBe("offline"));
  expect(result.current.window?.messages).toEqual([]);
  expect(result.current.loading).toBe(false);
  expect(result.current.operation).toBe("jump");
  await act(async () => result.current.retry());
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.error).toBeNull();
  expect(result.current.window).toEqual(original);
  expect(api.fetchWebuiThread).toHaveBeenCalledTimes(4);
  act(() => result.current.latest());
  expect(result.current.window).toBeNull();
  expect(sessions.navigationPositions.get("websocket:a")).toBeUndefined();
  unmount();
  expect(sessions.promptWindows.peek("websocket:a")).toBeUndefined();
  expect(sessions.navigationPositions.get("websocket:a")).toBeUndefined();
});

it("cancels cold recovery visibly and never delivers a late page to another session", async () => {
  const client = new NanobotClient({ url: "ws://localhost:8765", reconnect: false });
  const sessions = getSessionStore(client);
  const position = { queries: [{ cursor: "500", direction: "after" as const }, { cursor: "501", direction: "after" as const }] };
  sessions.navigationPositions.set("a", position);
  let finishCancelled!: (body: WebuiThreadPersistedPayload) => void;
  let finishDetached!: (body: WebuiThreadPersistedPayload) => void;
  vi.mocked(api.fetchWebuiThread)
    .mockImplementationOnce(() => new Promise((resolve) => { finishCancelled = resolve; }))
    .mockImplementationOnce(() => new Promise((resolve) => { finishDetached = resolve; }));
  const { result, rerender } = renderHook(({ key }) => usePromptHistory(key, 1, latest), {
    wrapper: wrapper(true, client), initialProps: { key: "a" },
  });
  const options = vi.mocked(api.fetchWebuiThread).mock.lastCall?.[2];
  if (typeof options !== "object") throw new Error("expected page options");
  act(() => result.current.cancel());
  expect(options.signal?.aborted).toBe(true);
  expect(result.current.loading).toBe(false);
  expect(result.current.window?.messages).toEqual([]);
  expect(result.current.error).toBe("History loading cancelled");
  act(() => result.current.retry());
  expect(result.current.loading).toBe(true);
  rerender({ key: "b" });
  await waitFor(() => expect(result.current.prompts).toHaveLength(2000));
  await act(async () => result.current.jump("u20"));
  await act(async () => {
    finishCancelled(page(500));
    finishDetached(page(500));
  });
  expect(result.current.window?.userMessageOffset).toBe(20);
  expect(sessions.promptWindows.peek("a")).toBeUndefined();
  expect(sessions.navigationPositions.get("a")).toEqual(position);
  expect(sessions.navigationPositions.get("b")?.queries).toEqual([{ cursor: "20", direction: "after" }]);
  rerender({ key: "a" });
  await waitFor(() => expect(result.current.window?.userMessageOffset).toBe(500));
  expect(result.current.window?.messages.map((message) => message.id)).toEqual(["u500", "a500", "u501", "a501"]);
});

it("aborts a cold recovery on a canonical generation change and ignores its late body", async () => {
  const client = new NanobotClient({ url: "ws://localhost:8765", reconnect: false });
  const sessions = getSessionStore(client);
  sessions.navigationPositions.set("a", { queries: [{ cursor: "500", direction: "after" }], generation: "old" });
  let finish!: (body: WebuiThreadPersistedPayload) => void;
  vi.mocked(api.fetchWebuiThread).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  const { result } = renderHook(() => usePromptHistory("a", 1, latest), { wrapper: wrapper(true, client) });
  const options = vi.mocked(api.fetchWebuiThread).mock.lastCall?.[2];
  if (typeof options !== "object") throw new Error("expected page options");
  act(() => sessions.publish("a", { ...page(1999), page: { ...page(1999).page, history_generation: "new" } }));
  expect(options.signal?.aborted).toBe(true);
  expect(result.current.error).toBe("History changed; select the message again");
  await act(async () => finish({ ...page(500), page: { ...page(500).page, history_generation: "old" } }));
  expect(result.current.window?.messages).toEqual([]);
  expect(sessions.navigationPositions.get("a")).toBeUndefined();
  await waitFor(() => expect(result.current.prompts).toHaveLength(2000));
  vi.mocked(api.fetchWebuiThread).mockResolvedValueOnce({ ...page(600), page: { ...page(600).page, history_generation: "new" } });
  await act(async () => result.current.jump("u600"));
  expect(result.current.window?.userMessageOffset).toBe(600);
  expect(result.current.error).toBeNull();
  expect(sessions.navigationPositions.get("a")?.generation).toBe("new");
});

it("does not publish a partially restored window when the saved generation has changed", async () => {
  const client = new NanobotClient({ url: "ws://localhost:8765", reconnect: false });
  getSessionStore(client).navigationPositions.set("a", {
    queries: [{ cursor: "500", direction: "after" }, { cursor: "501", direction: "after" }], generation: "old",
  });
  vi.mocked(api.fetchWebuiThread)
    .mockResolvedValueOnce({ ...page(500), page: { ...page(500).page, history_generation: "old" } })
    .mockResolvedValueOnce({ ...page(501), page: { ...page(501).page, history_generation: "new" } });
  const { result } = renderHook(() => usePromptHistory("a", 1, latest), { wrapper: wrapper(true, client) });
  await waitFor(() => expect(result.current.error).toBe("History changed; select the message again"));
  expect(result.current.window?.messages).toEqual([]);
  expect(result.current.loading).toBe(false);
});

it("validates reload descriptors, bounds session positions and exposes only copied lightweight data", () => {
  const source = { queries: [{ cursor: "opaque", direction: "after" as const }], generation: "g", body: page(5), token: "secret" };
  const positions = new PromptReadingPositionStore([
    ["websocket:a", source], ["bad", { queries: [{ cursor: 4, direction: "after" }] }],
    ["oversized", { queries: Array.from({ length: 4 }, () => source.queries[0]) }], ["empty", { queries: [] }],
  ]);
  expect(positions.entries()).toEqual([["websocket:a", { queries: source.queries, generation: "g" }]]);
  source.queries[0].cursor = "mutated";
  expect(positions.get("websocket:a")?.queries[0].cursor).toBe("opaque");
  const saved = positions.entries();
  saved[0][1].queries[0].cursor = "also mutated";
  expect(positions.get("websocket:a")?.queries[0].cursor).toBe("opaque");
  const changed = vi.fn();
  const unsubscribe = positions.subscribe(changed);
  for (let session = 0; session < 127; session++) positions.set(`websocket:${session}`, { queries: [{ cursor: String(session), direction: "before" }] });
  positions.get("websocket:a");
  positions.set("websocket:last", { queries: [{ cursor: "last", direction: "after" }] });
  expect(positions.entries()).toHaveLength(128);
  expect(positions.get("websocket:a")?.queries[0].cursor).toBe("opaque");
  expect(positions.get("websocket:0")).toBeUndefined();
  expect(positions.get("a")).toBeUndefined();
  positions.delete("websocket:last");
  expect(changed).toHaveBeenCalledTimes(129);
  unsubscribe();
  positions.clear();
  expect(positions.entries()).toEqual([]);
  expect(changed).toHaveBeenCalledTimes(129);
});


it.each(["delete", "clear"] as const)("does not resurrect cached state after %s from pending index/page reads or cleanup", async (operation) => {
  const client = new NanobotClient({ url: "ws://localhost:8765", reconnect: false });
  const sessions = getSessionStore(client);
  const { result, rerender, unmount } = renderHook(({ version }) => usePromptHistory("a", version, latest), {
    wrapper: wrapper(true, client), initialProps: { version: 1 },
  });
  await waitFor(() => expect(result.current.prompts).toHaveLength(2000));
  await act(async () => result.current.jump("u500"));
  let finishPage!: (body: WebuiThreadPersistedPayload) => void;
  let finishIndex!: (snapshot: PromptIndex) => void;
  vi.mocked(api.fetchWebuiThread).mockImplementationOnce(() => new Promise((resolve) => { finishPage = resolve; }));
  vi.mocked(api.fetchPromptIndex).mockImplementationOnce(() => new Promise((resolve) => { finishIndex = resolve; }));
  act(() => result.current.newer());
  rerender({ version: 2 });
  act(() => { if (operation === "delete") sessions.delete("a"); else sessions.clear(); });
  await act(async () => {
    finishPage(page(501));
    finishIndex({ prompts: index, revision: "late" });
  });
  expect(result.current.window?.userMessageOffset).toBe(500);
  expect(sessions.promptIndexes.peek("a")?.revision).toBeUndefined();
  expect(sessions.navigationPositions.get("a")).toBeUndefined();
  unmount();
  expect(sessions.promptWindows.peek("a")).toBeUndefined();
  expect(sessions.navigationPositions.get("a")).toBeUndefined();
});
