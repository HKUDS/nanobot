import { act, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { createRef, type ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { usePromptHistory } from "@/hooks/usePromptHistory";
import * as api from "@/lib/api";
import { NanobotClient } from "@/lib/nanobot-client";
import { ClientProvider } from "@/providers/ClientProvider";
import type { UIMessage, WebuiThreadPersistedPayload } from "@/lib/types";
import { ThreadViewport, type ThreadViewportHandle } from "@/components/thread/ThreadViewport";

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
function wrapper(enabled = true) {
  const client = new NanobotClient({ url: "ws://localhost:8765", reconnect: false });
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
