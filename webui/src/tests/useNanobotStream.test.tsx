import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { useNanobotStream } from "@/hooks/useNanobotStream";
import { normalizeActivityTimeline } from "@/lib/activity-timeline";
import type { StreamError } from "@/lib/nanobot-client";
import type {
  ConnectionStatus,
  GoalStateWsPayload,
  InboundEvent,
  UIMessage,
} from "@/lib/types";
import { ClientProvider } from "@/providers/ClientProvider";
import projectionFixture from "./fixtures/live-replay-event-projection.json";

const EMPTY_MESSAGES: UIMessage[] = [];

interface ProjectionFixtureCase {
  name: string;
  chat_id: string;
  initial_messages: UIMessage[];
  live_events: InboundEvent[];
  expected: Array<Record<string, unknown>>;
}

const PROJECTION_FIXTURE_CASES = (
  projectionFixture as unknown as { cases: ProjectionFixtureCase[] }
).cases;
const SEMANTIC_MESSAGE_FIELDS = [
  "role",
  "content",
  "kind",
  "traces",
  "toolEvents",
  "fileEdits",
  "images",
  "media",
  "cliApps",
  "mcpPresets",
  "sessionMentions",
  "reasoning",
  "latencyMs",
  "source",
  "turnId",
  "turnPhase",
  "turnSeq",
] as const satisfies ReadonlyArray<keyof UIMessage>;

function normalizeProjection(messages: UIMessage[]): Array<Record<string, unknown>> {
  const segmentAliases = new Map<string, string>();
  return messages.map((message) => {
    const row: Record<string, unknown> = {};
    for (const field of SEMANTIC_MESSAGE_FIELDS) {
      const value = message[field];
      if (value !== undefined && value !== null) row[field] = value;
    }
    if (message.activitySegmentId) {
      let alias = segmentAliases.get(message.activitySegmentId);
      if (!alias) {
        alias = `segment-${segmentAliases.size + 1}`;
        segmentAliases.set(message.activitySegmentId, alias);
      }
      row.activitySegmentId = alias;
    }
    return row;
  });
}

function fakeClient() {
  const handlers = new Map<string, Set<(ev: InboundEvent) => void>>();
  const statusHandlers = new Set<(status: ConnectionStatus) => void>();
  const runStatusHandlers = new Set<(chatId: string, startedAt: number | null) => void>();
  const errorHandlers = new Set<(error: StreamError) => void>();
  const runStartedAtByChatId = new Map<string, number>();
  const unsettledRunByChatId = new Map<string, boolean>();
  const goalStateByChatId = new Map<string, GoalStateWsPayload>();
  const requestMutation = vi.fn().mockResolvedValue({});
  let status: ConnectionStatus = "open";

  function recordGoalStatusForRunStrip(chatId: string, ev: InboundEvent) {
    if (ev.event === "turn_end") {
      runStartedAtByChatId.delete(chatId);
      return;
    }
    if (ev.event !== "goal_status") return;
    if (ev.status === "running" && typeof ev.started_at === "number") {
      runStartedAtByChatId.set(chatId, ev.started_at);
    } else {
      runStartedAtByChatId.delete(chatId);
    }
  }

  function recordGoalStateSnapshot(chatId: string, ev: InboundEvent) {
    if (ev.event === "goal_state") {
      goalStateByChatId.set(chatId, ev.goal_state);
      return;
    }
    if (ev.event === "turn_end" && ev.goal_state != null && typeof ev.goal_state === "object") {
      goalStateByChatId.set(chatId, ev.goal_state);
    }
  }

  return {
    client: {
      get status() {
        return status;
      },
      defaultChatId: null as string | null,
      onStatus(handler: (nextStatus: ConnectionStatus) => void) {
        statusHandlers.add(handler);
        handler(status);
        return () => statusHandlers.delete(handler);
      },
      onRunStatus(handler: (chatId: string, startedAt: number | null) => void) {
        runStatusHandlers.add(handler);
        for (const [chatId, startedAt] of runStartedAtByChatId) handler(chatId, startedAt);
        return () => runStatusHandlers.delete(handler);
      },
      onError(handler: (error: StreamError) => void) {
        errorHandlers.add(handler);
        return () => errorHandlers.delete(handler);
      },
      getRunStartedAt(chatId: string) {
        const v = runStartedAtByChatId.get(chatId);
        return v === undefined ? null : v;
      },
      getGoalState(chatId: string) {
        return goalStateByChatId.get(chatId);
      },
      hasUnsettledRun(chatId: string) {
        return unsettledRunByChatId.get(chatId) === true;
      },
      onChat(chatId: string, h: (ev: InboundEvent) => void) {
        let set = handlers.get(chatId);
        if (!set) {
          set = new Set();
          handlers.set(chatId, set);
        }
        set.add(h);
        return () => set!.delete(h);
      },
      sendMessage: vi.fn(),
      requestMutation,
      finishRunLocally: vi.fn(),
      newChat: vi.fn(),
      forkChat: vi.fn(),
      attach: vi.fn(),
      connect: vi.fn(),
      close: vi.fn(),
      updateUrl: vi.fn(),
    },
    emit(chatId: string, ev: InboundEvent) {
      recordGoalStatusForRunStrip(chatId, ev);
      recordGoalStateSnapshot(chatId, ev);
      const set = handlers.get(chatId);
      set?.forEach((h) => h(ev));
    },
    emitStatus(nextStatus: ConnectionStatus) {
      status = nextStatus;
      statusHandlers.forEach((handler) => handler(status));
    },
    emitRunStatus(chatId: string, startedAt: number | null) {
      if (startedAt === null) runStartedAtByChatId.delete(chatId);
      else runStartedAtByChatId.set(chatId, startedAt);
      runStatusHandlers.forEach((handler) => handler(chatId, startedAt));
    },
    emitError(error: StreamError) {
      errorHandlers.forEach((handler) => handler(error));
    },
    setUnsettled(chatId: string, unsettled: boolean) {
      unsettledRunByChatId.set(chatId, unsettled);
    },
    requestMutation,
  };
}

function wrap(client: ReturnType<typeof fakeClient>["client"]) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <ClientProvider
        client={client as unknown as import("@/lib/nanobot-client").NanobotClient}
        token="tok"
      >
        {children}
      </ClientProvider>
    );
  };
}

async function flushStreamFrame() {
  await act(async () => {
    await new Promise<void>((resolve) => {
      requestAnimationFrame(() => resolve());
    });
  });
}

describe("useNanobotStream", () => {
  it("batches answer deltas into one animation-frame update", async () => {
    const fake = fakeClient();
    const requestFrame = vi.spyOn(window, "requestAnimationFrame");
    const { result } = renderHook(() => useNanobotStream("chat-batch", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-batch", {
        event: "delta",
        chat_id: "chat-batch",
        text: "Hello",
      });
      fake.emit("chat-batch", {
        event: "delta",
        chat_id: "chat-batch",
        text: " world",
      });
    });

    expect(requestFrame).toHaveBeenCalledTimes(1);
    expect(result.current.messages).toHaveLength(0);

    await flushStreamFrame();

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0]).toMatchObject({
      role: "assistant",
      content: "Hello world",
      isStreaming: true,
    });
    requestFrame.mockRestore();
  });

  it("coalesces hidden-tab deltas without scheduling paint frames", () => {
    vi.useFakeTimers();
    const visibilityDescriptor = Object.getOwnPropertyDescriptor(document, "visibilityState");
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "hidden",
    });
    const requestFrame = vi.spyOn(window, "requestAnimationFrame");

    try {
      const fake = fakeClient();
      const { result } = renderHook(
        () => useNanobotStream("chat-background", EMPTY_MESSAGES),
        { wrapper: wrap(fake.client) },
      );

      act(() => {
        fake.emit("chat-background", {
          event: "delta",
          chat_id: "chat-background",
          text: "Quiet",
        });
        fake.emit("chat-background", {
          event: "delta",
          chat_id: "chat-background",
          text: " background",
        });
      });

      expect(requestFrame).not.toHaveBeenCalled();
      expect(result.current.messages).toHaveLength(0);

      act(() => vi.advanceTimersByTime(1_000));

      expect(result.current.messages[0]).toMatchObject({
        content: "Quiet background",
        isStreaming: true,
      });
    } finally {
      requestFrame.mockRestore();
      if (visibilityDescriptor) {
        Object.defineProperty(document, "visibilityState", visibilityDescriptor);
      } else {
        delete (document as Document & { visibilityState?: DocumentVisibilityState }).visibilityState;
      }
      vi.useRealTimers();
    }
  });

  it("keeps the turn pending on disconnect without breaking a resumed stream", async () => {
    const fake = fakeClient();
    const { result } = renderHook(
      () => useNanobotStream("chat-reconnect", EMPTY_MESSAGES),
      { wrapper: wrap(fake.client) },
    );

    act(() => {
      fake.emit("chat-reconnect", {
        event: "goal_status",
        chat_id: "chat-reconnect",
        status: "running",
        started_at: 1_700,
      });
      fake.emit("chat-reconnect", {
        event: "delta",
        chat_id: "chat-reconnect",
        text: "partial",
      });
    });
    await flushStreamFrame();
    const assistantId = result.current.messages[0].id;
    expect(result.current.isStreaming).toBe(true);

    act(() => fake.emitStatus("reconnecting"));
    expect(result.current.runStartedAt).toBe(1_700);
    expect(result.current.isStreaming).toBe(true);
    expect(result.current.messages[0]).toMatchObject({
      id: assistantId,
      content: "partial",
      isStreaming: true,
    });

    act(() => {
      fake.emitStatus("open");
      fake.emit("chat-reconnect", {
        event: "goal_status",
        chat_id: "chat-reconnect",
        status: "running",
        started_at: 1_800,
      });
      fake.emit("chat-reconnect", {
        event: "delta",
        chat_id: "chat-reconnect",
        text: " resumed",
      });
    });
    await flushStreamFrame();

    expect(result.current.runStartedAt).toBe(1_800);
    expect(result.current.isStreaming).toBe(true);
    expect(result.current.messages[0]).toMatchObject({
      id: assistantId,
      content: "partial resumed",
      isStreaming: true,
    });
  });

  it("clears stale stream state when the transport resets a run", async () => {
    const fake = fakeClient();
    const { result } = renderHook(
      () => useNanobotStream("chat-reconnect-reset", EMPTY_MESSAGES),
      { wrapper: wrap(fake.client) },
    );

    act(() => {
      fake.emit("chat-reconnect-reset", {
        event: "goal_status",
        chat_id: "chat-reconnect-reset",
        status: "running",
        started_at: 1_700,
      });
      fake.emit("chat-reconnect-reset", {
        event: "delta",
        chat_id: "chat-reconnect-reset",
        text: "partial",
      });
    });
    await flushStreamFrame();
    expect(result.current.isStreaming).toBe(true);

    act(() => fake.emitRunStatus("chat-reconnect-reset", null));

    expect(result.current.runStartedAt).toBeNull();
    expect(result.current.isStreaming).toBe(false);
    expect(result.current.messages[0]).toMatchObject({
      content: "partial",
      isStreaming: false,
    });
  });

  it("flushes pending delta text before turn_end finalizes the turn", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-flush", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-flush", {
        event: "delta",
        chat_id: "chat-flush",
        text: "final chunk",
      });
      fake.emit("chat-flush", {
        event: "turn_end",
        chat_id: "chat-flush",
      });
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0]).toMatchObject({
      role: "assistant",
      content: "final chunk",
      isStreaming: false,
    });
    expect(result.current.isStreaming).toBe(false);
  });

  it("stamps provider usage and latest context on the completed answer", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-usage", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-usage", {
        event: "delta",
        chat_id: "chat-usage",
        text: "done",
        turn_id: "turn-usage",
      });
      fake.emit("chat-usage", {
        event: "turn_end",
        chat_id: "chat-usage",
        turn_id: "turn-usage",
        latency_ms: 18_200,
        context_window_tokens: 128_000,
        usage: {
          prompt_tokens: 12_400,
          completion_tokens: 823,
          cached_tokens: 9_672,
          context_tokens: 8_100,
          request_count: 3,
        },
      });
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0]).toMatchObject({
      content: "done",
      isStreaming: false,
      latencyMs: 18_200,
      contextWindowTokens: 128_000,
      usage: {
        prompt_tokens: 12_400,
        completion_tokens: 823,
        cached_tokens: 9_672,
        context_tokens: 8_100,
        request_count: 3,
      },
    });
  });

  it("exposes typed recovery state and validates actions with its recovery id", async () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-recovery", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-recovery", {
        event: "goal_status",
        chat_id: "chat-recovery",
        status: "running",
        started_at: 1_700,
      });
    });
    expect(result.current.runStartedAt).toBe(1_700);

    act(() => {
      fake.emit("chat-recovery", {
        event: "recovery_state",
        chat_id: "chat-recovery",
        recovery_id: "recovery-1",
        status: "awaiting_user",
        reason: "tool_state_uncertain",
        can_continue: false,
      });
    });

    expect(result.current.recoveryState).toEqual({
      recovery_id: "recovery-1",
      status: "awaiting_user",
      reason: "tool_state_uncertain",
      can_continue: false,
    });
    expect(result.current.isStreaming).toBe(false);
    expect(result.current.runStartedAt).toBeNull();
    expect(fake.client.finishRunLocally).toHaveBeenCalledWith("chat-recovery");

    act(() => {
      fake.emit("chat-recovery", {
        event: "recovery_state",
        chat_id: "chat-recovery",
        recovery_id: "recovery-1",
        status: "awaiting_user",
        reason: "tool_state_uncertain",
        can_continue: true,
      });
    });

    await act(async () => result.current.continueRecovery());
    expect(fake.requestMutation).toHaveBeenCalledWith("recovery.continue", {
      chat_id: "chat-recovery",
      recovery_id: "recovery-1",
    });

    act(() => {
      fake.emit("chat-recovery", {
        event: "recovery_state",
        chat_id: "chat-recovery",
        recovery_id: "recovery-1",
        status: "recovered",
      });
    });
    expect(result.current.isStreaming).toBe(false);
    expect(fake.client.finishRunLocally).toHaveBeenCalledWith("chat-recovery");
  });

  it("does not let historical recovered state clear a later active turn", () => {
    const fake = fakeClient();
    const { result } = renderHook(
      () => useNanobotStream("chat-recovered-history", EMPTY_MESSAGES),
      { wrapper: wrap(fake.client) },
    );

    act(() => {
      fake.emit("chat-recovered-history", {
        event: "goal_status",
        chat_id: "chat-recovered-history",
        status: "running",
        started_at: 1_700,
      });
      fake.emit("chat-recovered-history", {
        event: "attached",
        chat_id: "chat-recovered-history",
        recovery_state: {
          recovery_id: "old-recovery",
          status: "recovered",
        },
      });
    });

    expect(result.current.isStreaming).toBe(true);
    expect(result.current.runStartedAt).toBe(1_700);
    expect(fake.client.finishRunLocally).not.toHaveBeenCalled();
  });

  it("preserves proactive automation source metadata on complete assistant messages", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-cron", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-cron", {
        event: "message",
        chat_id: "chat-cron",
        text: "Time to drink water.",
        source: { kind: "cron", label: "drink water" },
      });
    });

    expect(result.current.messages[0]).toMatchObject({
      role: "assistant",
      content: "Time to drink water.",
      source: { kind: "cron", label: "drink water" },
    });
  });

  it("preserves proactive automation source metadata on streamed assistant messages", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-cron-stream", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });
    const source = { kind: "cron", label: "Repo check" };

    act(() => {
      fake.emit("chat-cron-stream", {
        event: "delta",
        chat_id: "chat-cron-stream",
        text: "Repo ",
        source,
      });
      fake.emit("chat-cron-stream", {
        event: "stream_end",
        chat_id: "chat-cron-stream",
        source,
      });
      fake.emit("chat-cron-stream", {
        event: "turn_end",
        chat_id: "chat-cron-stream",
      });
    });

    expect(result.current.messages[0]).toMatchObject({
      role: "assistant",
      content: "Repo ",
      isStreaming: false,
      source,
    });
  });

  it("preserves proactive automation source metadata on stream_end final text", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-cron-stream-end", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });
    const source = { kind: "cron", label: "Repo check" };

    act(() => {
      fake.emit("chat-cron-stream-end", {
        event: "stream_end",
        chat_id: "chat-cron-stream-end",
        text: "Repo clean.",
        source,
      });
    });

    expect(result.current.messages[0]).toMatchObject({
      role: "assistant",
      content: "Repo clean.",
      isStreaming: true,
      source,
    });
  });

  it("does not start streaming from completed trailing activity after an answer", () => {
    const fake = fakeClient();
    const initialMessages = [
      {
        id: "a1",
        role: "assistant" as const,
        content: "Cron test",
        turnId: "cron:run",
        createdAt: Date.now(),
      },
      {
        id: "t1",
        role: "tool" as const,
        kind: "trace" as const,
        content: "message({})",
        traces: ["message({})"],
        turnId: "cron:run",
        createdAt: Date.now(),
      },
    ];

    const { result } = renderHook(
      () => useNanobotStream("chat-cron-done", initialMessages),
      { wrapper: wrap(fake.client) },
    );

    expect(result.current.messages.at(-1)?.kind).toBe("trace");
    expect(result.current.isStreaming).toBe(false);
  });

  it("drops pending stream work when switching chats", async () => {
    const fake = fakeClient();
    const { result, rerender } = renderHook(
      ({ chatId }: { chatId: string }) => useNanobotStream(chatId, EMPTY_MESSAGES),
      {
        wrapper: wrap(fake.client),
        initialProps: { chatId: "chat-old" },
      },
    );

    act(() => {
      fake.emit("chat-old", {
        event: "delta",
        chat_id: "chat-old",
        text: "stale",
      });
    });

    rerender({ chatId: "chat-new" });

    act(() => {
      fake.emit("chat-new", {
        event: "delta",
        chat_id: "chat-new",
        text: "fresh",
      });
    });
    await flushStreamFrame();

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0]).toMatchObject({
      role: "assistant",
      content: "fresh",
    });
  });

  it("starts in streaming mode when history shows pending tool calls", () => {
    const fake = fakeClient();
    const initialMessages = [{
      id: "m1",
      role: "assistant" as const,
      content: "Using tools",
      createdAt: Date.now(),
    }];
    const { result } = renderHook(
      () => useNanobotStream("chat-p", initialMessages, true),
      {
        wrapper: wrap(fake.client),
      },
    );

    expect(result.current.isStreaming).toBe(true);
  });

  it("collapses consecutive tool_hint frames into one trace row", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-t", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-t", {
        event: "message",
        chat_id: "chat-t",
        text: 'weather("get")',
        kind: "tool_hint",
      });
      fake.emit("chat-t", {
        event: "message",
        chat_id: "chat-t",
        text: 'search "hk weather"',
        kind: "tool_hint",
      });
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].kind).toBe("trace");
    expect(result.current.messages[0].role).toBe("tool");
    expect(result.current.messages[0].traces).toEqual([
      'weather("get")',
      'search "hk weather"',
    ]);

    act(() => {
      fake.emit("chat-t", {
        event: "message",
        chat_id: "chat-t",
        text: "## Summary",
      });
    });

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[1].role).toBe("assistant");
    expect(result.current.messages[1].kind).toBeUndefined();
  });

  it("treats progress with arbitrary agent_ui like ordinary trace text", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-au", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });
    act(() => {
      fake.emit("chat-au", {
        event: "message",
        chat_id: "chat-au",
        text: "progress · panel tick",
        kind: "progress",
        agent_ui: {
          kind: "panel",
          data: { version: 1, event: "tick", id: "x1" },
        },
      });
    });
    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].kind).toBe("trace");
    expect(result.current.messages[0].content).toContain("panel tick");
  });

  it("renders live tool traces from structured tool events", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-tool-events", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-tool-events", {
        event: "message",
        chat_id: "chat-tool-events",
        text: 'search "hermes"',
        kind: "tool_hint",
        tool_events: [
          {
            phase: "start",
            name: "web_search",
            arguments: { query: "NousResearch hermes-agent", count: 8 },
          },
          {
            phase: "start",
            name: "web_search",
            arguments: { query: "hermes-agent GitHub stars", count: 8 },
          },
        ],
      });
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].traces).toEqual([
      'web_search({"query":"NousResearch hermes-agent","count":8})',
      'web_search({"query":"hermes-agent GitHub stars","count":8})',
    ]);
    expect(result.current.messages[0].content).toBe(
      'web_search({"query":"hermes-agent GitHub stars","count":8})',
    );
  });

  it("dedupes finish-phase tool events after their start trace", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-tool-finish", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-tool-finish", {
        event: "message",
        chat_id: "chat-tool-finish",
        text: 'exec({"cmd":"ls"})',
        kind: "tool_hint",
        tool_events: [{
          phase: "start",
          call_id: "call-exec",
          name: "exec",
          arguments: { cmd: "ls" },
        }],
      });
      fake.emit("chat-tool-finish", {
        event: "message",
        chat_id: "chat-tool-finish",
        text: "",
        kind: "progress",
        tool_events: [
          {
            phase: "end",
            call_id: "call-exec",
            name: "exec",
            arguments: { cmd: "ls" },
            result: "ok",
          },
          {
            phase: "error",
            call_id: "call-read",
            name: "read_file",
            arguments: { path: "notes.md" },
            error: "missing",
          },
        ],
      });
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].traces).toEqual([
      'exec({"cmd":"ls"})',
      'read_file({"path":"notes.md"})',
    ]);
    expect(result.current.messages[0].toolEvents).toMatchObject([
      { phase: "end", call_id: "call-exec", name: "exec" },
      { phase: "error", call_id: "call-read", name: "read_file", error: "missing" },
    ]);
  });

  it("replaces a hosted search placeholder when its query arrives", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-hosted-search", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-hosted-search", {
        event: "message",
        chat_id: "chat-hosted-search",
        text: "web_search()",
        kind: "tool_hint",
        tool_events: [{
          phase: "start",
          call_id: "ws-1",
          name: "web_search",
          arguments: {},
        }],
      });
      fake.emit("chat-hosted-search", {
        event: "message",
        chat_id: "chat-hosted-search",
        text: "",
        kind: "progress",
        tool_events: [{
          phase: "end",
          call_id: "ws-1",
          name: "web_search",
          arguments: { query: "nanobot news" },
          result: { status: "completed" },
        }],
      });
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].traces).toEqual([
      'web_search({"query":"nanobot news"})',
    ]);
    expect(result.current.messages[0].toolEvents).toMatchObject([{
      phase: "end",
      call_id: "ws-1",
      arguments: { query: "nanobot news" },
    }]);
  });

  it("keeps phase updates when a tool event trace line is deduped", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-tool-phase", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    const args = { name: "github", args: ["repo", "view"], json: "true" };
    act(() => {
      fake.emit("chat-tool-phase", {
        event: "message",
        chat_id: "chat-tool-phase",
        text: "",
        kind: "tool_hint",
        tool_events: [{
          phase: "start",
          call_id: "call-cli",
          name: "run_cli_app",
          arguments: args,
        }],
      });
      fake.emit("chat-tool-phase", {
        event: "message",
        chat_id: "chat-tool-phase",
        text: "",
        kind: "progress",
        tool_events: [{
          phase: "error",
          call_id: "call-cli",
          name: "run_cli_app",
          arguments: args,
          error: "Error: CLI app 'github' not found",
        }],
      });
    });

    expect(result.current.messages[0].traces).toEqual([
      'run_cli_app({"name":"github","args":["repo","view"],"json":"true"})',
    ]);
    expect(result.current.messages[0].toolEvents).toMatchObject([
      {
        phase: "error",
        call_id: "call-cli",
        name: "run_cli_app",
        error: "Error: CLI app 'github' not found",
      },
    ]);
  });

  it("renders live file_edit events as their own activity trace", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-file-edit", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-file-edit", {
        event: "message",
        chat_id: "chat-file-edit",
        text: 'write_file({"path":"foo.txt"})',
        kind: "tool_hint",
      });
      fake.emit("chat-file-edit", {
        event: "file_edit",
        chat_id: "chat-file-edit",
        edits: [{
          call_id: "call-write",
          tool: "write_file",
          path: "foo.txt",
          phase: "start",
          added: 1,
          deleted: 0,
          approximate: true,
          status: "editing",
        }],
      });
      fake.emit("chat-file-edit", {
        event: "file_edit",
        chat_id: "chat-file-edit",
        edits: [{
          call_id: "call-write",
          tool: "write_file",
          path: "foo.txt",
          phase: "end",
          added: 3,
          deleted: 1,
          approximate: false,
          status: "done",
        }],
      });
    });

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0]).toMatchObject({
      role: "tool",
      kind: "trace",
      traces: ['write_file({"path":"foo.txt"})'],
    });
    expect(result.current.messages[1]).toMatchObject({
      role: "tool",
      kind: "trace",
      fileEdits: [{
        call_id: "call-write",
        status: "done",
        added: 3,
        deleted: 1,
        approximate: false,
      }],
    });
    expect(result.current.messages[1].activitySegmentId).toBeTruthy();
    expect(result.current.messages[1].activitySegmentId).not.toBe(
      result.current.messages[0].activitySegmentId,
    );
  });

  it("replaces matching write_file tool events with live file edit activity", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-file-edit-events", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-file-edit-events", {
        event: "message",
        chat_id: "chat-file-edit-events",
        text: 'write_file({"path":"foo.txt"})',
        kind: "tool_hint",
        tool_events: [{
          phase: "start",
          call_id: "call-write",
          name: "write_file",
          arguments: { path: "foo.txt", content: "hello\n" },
        }],
      });
      fake.emit("chat-file-edit-events", {
        event: "file_edit",
        chat_id: "chat-file-edit-events",
        edits: [{
          call_id: "call-write",
          tool: "write_file",
          path: "foo.txt",
          phase: "start",
          added: 1,
          deleted: 0,
          approximate: true,
          status: "editing",
        }],
      });
      fake.emit("chat-file-edit-events", {
        event: "message",
        chat_id: "chat-file-edit-events",
        text: "",
        kind: "progress",
        tool_events: [{
          phase: "end",
          call_id: "call-write",
          name: "write_file",
          arguments: { path: "foo.txt", content: "hello\n" },
          result: "ok",
        }],
      });
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0]).toMatchObject({
      role: "tool",
      kind: "trace",
      traces: [],
      fileEdits: [{
        call_id: "call-write",
        tool: "write_file",
        path: "foo.txt",
        status: "editing",
      }],
    });
    expect(result.current.messages[0].toolEvents).toBeUndefined();
  });

  it("keeps live file edits separate from mixed non-file tool traces", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-file-edit-mixed-tools", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-file-edit-mixed-tools", {
        event: "message",
        chat_id: "chat-file-edit-mixed-tools",
        text: "",
        kind: "tool_hint",
        tool_events: [
          {
            phase: "start",
            call_id: "call-read",
            name: "read_file",
            arguments: { path: "quicksort.py" },
          },
          {
            phase: "start",
            call_id: "call-write",
            name: "write_file",
            arguments: { path: "sorting/quicksort.py", content: "def quicksort():\n" },
          },
        ],
      });
      fake.emit("chat-file-edit-mixed-tools", {
        event: "file_edit",
        chat_id: "chat-file-edit-mixed-tools",
        edits: [{
          call_id: "call-write",
          tool: "write_file",
          path: "sorting/quicksort.py",
          phase: "end",
          added: 3,
          deleted: 0,
          approximate: false,
          status: "done",
        }],
      });
    });

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0]).toMatchObject({
      role: "tool",
      kind: "trace",
      traces: ['read_file({"path":"quicksort.py"})'],
    });
    expect(result.current.messages[0].toolEvents?.map((event) => event.name)).toEqual(["read_file"]);
    expect(result.current.messages[0].fileEdits).toBeUndefined();
    expect(result.current.messages[1]).toMatchObject({
      role: "tool",
      kind: "trace",
      traces: [],
      fileEdits: [{
        call_id: "call-write",
        tool: "write_file",
        path: "sorting/quicksort.py",
        status: "done",
      }],
    });
    expect(result.current.messages[1].toolEvents).toBeUndefined();
  });

  it("keeps every file from one apply_patch call", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-apply-patch-many", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-apply-patch-many", {
        event: "message",
        chat_id: "chat-apply-patch-many",
        text: "apply_patch()",
        kind: "tool_hint",
        tool_events: [{
          phase: "start",
          call_id: "call-patch",
          name: "apply_patch",
          arguments: { edits: [] },
        }],
      });
      fake.emit("chat-apply-patch-many", {
        event: "file_edit",
        chat_id: "chat-apply-patch-many",
        edits: [
          {
            call_id: "call-patch",
            tool: "apply_patch",
            path: "USER.md",
            phase: "end",
            added: 0,
            deleted: 3,
            approximate: false,
            status: "done",
          },
          {
            call_id: "call-patch",
            tool: "apply_patch",
            path: "MEMORY.md",
            phase: "end",
            added: 0,
            deleted: 4,
            approximate: false,
            status: "done",
          },
        ],
      });
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].traces).toEqual([]);
    expect(result.current.messages[0].toolEvents).toBeUndefined();
    expect(result.current.messages[0].fileEdits?.map((edit) => edit.path)).toEqual([
      "USER.md",
      "MEMORY.md",
    ]);
  });

  it("upgrades pending file_edit placeholders when the path arrives", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-file-edit-pending", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-file-edit-pending", {
        event: "file_edit",
        chat_id: "chat-file-edit-pending",
        edits: [{
          call_id: "call-write",
          tool: "write_file",
          path: "",
          phase: "start",
          added: 1,
          deleted: 0,
          approximate: true,
          status: "editing",
          pending: true,
        }],
      });
      fake.emit("chat-file-edit-pending", {
        event: "file_edit",
        chat_id: "chat-file-edit-pending",
        edits: [{
          call_id: "call-write",
          tool: "write_file",
          path: "foo.txt",
          phase: "start",
          added: 12,
          deleted: 0,
          approximate: true,
          status: "editing",
        }],
      });
    });

    const fileEditMessages = result.current.messages.filter((message) => message.fileEdits?.length);
    expect(fileEditMessages).toHaveLength(1);
    expect(fileEditMessages[0].fileEdits).toEqual([{
      call_id: "call-write",
      tool: "write_file",
      path: "foo.txt",
      phase: "start",
      added: 12,
      deleted: 0,
      approximate: true,
      status: "editing",
    }]);
  });

  it("merges file_edit updates after interleaved progress events", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-file-edit-progress", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-file-edit-progress", {
        event: "message",
        chat_id: "chat-file-edit-progress",
        text: 'write_file({"path":"foo.txt"})',
        kind: "tool_hint",
      });
      fake.emit("chat-file-edit-progress", {
        event: "file_edit",
        chat_id: "chat-file-edit-progress",
        edits: [{
          call_id: "call-write",
          tool: "write_file",
          path: "foo.txt",
          phase: "start",
          added: 12,
          deleted: 0,
          approximate: true,
          status: "editing",
        }],
      });
      fake.emit("chat-file-edit-progress", {
        event: "message",
        chat_id: "chat-file-edit-progress",
        text: "still working",
        kind: "progress",
      });
      fake.emit("chat-file-edit-progress", {
        event: "file_edit",
        chat_id: "chat-file-edit-progress",
        edits: [{
          call_id: "call-write",
          tool: "write_file",
          path: "foo.txt",
          phase: "end",
          added: 30,
          deleted: 0,
          approximate: false,
          status: "done",
        }],
      });
    });

    const fileEditMessages = result.current.messages.filter((message) => message.fileEdits?.length);
    expect(fileEditMessages).toHaveLength(1);
    expect(fileEditMessages[0].fileEdits).toEqual([{
      call_id: "call-write",
      tool: "write_file",
      path: "foo.txt",
      phase: "end",
      added: 30,
      deleted: 0,
      approximate: false,
      status: "done",
    }]);
  });

  it("keeps interrupted pre-tool text as assistant output before activity", async () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-stream-segments", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-stream-segments", {
        event: "delta",
        chat_id: "chat-stream-segments",
        text: "I created the files.",
      });
      fake.emit("chat-stream-segments", {
        event: "stream_end",
        chat_id: "chat-stream-segments",
      });
      fake.emit("chat-stream-segments", {
        event: "message",
        chat_id: "chat-stream-segments",
        text: 'write_file({"path":"minecraft-fps/options.txt"})',
        kind: "tool_hint",
      });
      fake.emit("chat-stream-segments", {
        event: "delta",
        chat_id: "chat-stream-segments",
        text: "Now I will summarize the edits.",
      });
    });

    await flushStreamFrame();

    expect(result.current.messages).toHaveLength(3);
    expect(result.current.messages[0]).toMatchObject({
      role: "assistant",
      content: "I created the files.",
    });
    expect(result.current.messages[1]).toMatchObject({
      role: "tool",
      kind: "trace",
      traces: ['write_file({"path":"minecraft-fps/options.txt"})'],
    });
    expect(result.current.messages[2]).toMatchObject({
      role: "assistant",
      content: "Now I will summarize the edits.",
    });
  });

  it("does not replace interrupted pre-tool text with final stream_end text", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-stream-end-final", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-stream-end-final", {
        event: "delta",
        chat_id: "chat-stream-end-final",
        text: "I will inspect the project first.",
      });
      fake.emit("chat-stream-end-final", {
        event: "stream_end",
        chat_id: "chat-stream-end-final",
      });
      fake.emit("chat-stream-end-final", {
        event: "message",
        chat_id: "chat-stream-end-final",
        text: 'exec({"cmd":"ls"})',
        kind: "tool_hint",
      });
      fake.emit("chat-stream-end-final", {
        event: "stream_end",
        chat_id: "chat-stream-end-final",
        text: "Done. Open index.html to play.",
      });
    });

    expect(result.current.messages).toHaveLength(3);
    expect(result.current.messages[0]).toMatchObject({
      role: "assistant",
      content: "I will inspect the project first.",
    });
    expect(result.current.messages[1]).toMatchObject({
      role: "tool",
      kind: "trace",
      traces: ['exec({"cmd":"ls"})'],
    });
    expect(result.current.messages[2]).toMatchObject({
      role: "assistant",
      content: "Done. Open index.html to play.",
      isStreaming: true,
    });
  });

  it("splits live assistant output around tool hints without moving it into reasoning", async () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-live-segments", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-live-segments", {
        event: "delta",
        chat_id: "chat-live-segments",
        text: "Lint passed; now rendering the video.",
      });
      fake.emit("chat-live-segments", {
        event: "message",
        chat_id: "chat-live-segments",
        text: 'exec({"cmd":"hyperframes render"})',
        kind: "tool_hint",
      });
      fake.emit("chat-live-segments", {
        event: "delta",
        chat_id: "chat-live-segments",
        text: "Rendered successfully.",
      });
    });

    await flushStreamFrame();

    expect(result.current.messages).toHaveLength(3);
    expect(result.current.messages[0]).toMatchObject({
      role: "assistant",
      content: "Lint passed; now rendering the video.",
    });
    expect(result.current.messages[0].reasoning).toBeUndefined();
    expect(result.current.messages[1]).toMatchObject({
      role: "tool",
      kind: "trace",
      traces: ['exec({"cmd":"hyperframes render"})'],
    });
    expect(result.current.messages[2]).toMatchObject({
      role: "assistant",
      content: "Rendered successfully.",
    });
    expect(result.current.messages[2].reasoning).toBeUndefined();
  });

  it("opens a new activity segment for reasoning after file edit activity", async () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-file-segments", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-file-segments", {
        event: "reasoning_delta",
        chat_id: "chat-file-segments",
        text: "Plan.",
      });
      fake.emit("chat-file-segments", {
        event: "reasoning_end",
        chat_id: "chat-file-segments",
      });
      fake.emit("chat-file-segments", {
        event: "message",
        chat_id: "chat-file-segments",
        text: 'edit_file({"path":"foo.txt"})',
        kind: "tool_hint",
      });
      fake.emit("chat-file-segments", {
        event: "file_edit",
        chat_id: "chat-file-segments",
        edits: [{
          call_id: "call-edit",
          tool: "edit_file",
          path: "foo.txt",
          phase: "start",
          added: 1,
          deleted: 1,
          approximate: true,
          status: "editing",
        }],
      });
      fake.emit("chat-file-segments", {
        event: "reasoning_delta",
        chat_id: "chat-file-segments",
        text: "Review result.",
      });
    });

    await flushStreamFrame();

    expect(result.current.messages).toHaveLength(4);
    const firstSegment = result.current.messages[0].activitySegmentId;
    expect(firstSegment).toBeTruthy();
    expect(result.current.messages[1].activitySegmentId).toBe(firstSegment);
    expect(result.current.messages[2].activitySegmentId).toBeTruthy();
    expect(result.current.messages[2].activitySegmentId).not.toBe(firstSegment);
    expect(result.current.messages[3].activitySegmentId).toBeTruthy();
    expect(result.current.messages[3].activitySegmentId).not.toBe(result.current.messages[2].activitySegmentId);
  });

  it("keeps file edit blocks ordered across a new reasoning phase", async () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-file-order", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-file-order", {
        event: "file_edit",
        chat_id: "chat-file-order",
        edits: [{
          call_id: "call-one",
          tool: "write_file",
          path: "one.txt",
          phase: "start",
          added: 10,
          deleted: 0,
          approximate: true,
          status: "editing",
        }],
      });
      fake.emit("chat-file-order", {
        event: "reasoning_delta",
        chat_id: "chat-file-order",
        text: "Check the next file.",
      });
    });

    await flushStreamFrame();

    act(() => {
      fake.emit("chat-file-order", {
        event: "file_edit",
        chat_id: "chat-file-order",
        edits: [{
          call_id: "call-two",
          tool: "write_file",
          path: "two.txt",
          phase: "start",
          added: 20,
          deleted: 0,
          approximate: true,
          status: "editing",
        }],
      });
    });

    expect(result.current.messages.map((message) => message.fileEdits?.[0]?.path ?? message.reasoning)).toEqual([
      "one.txt",
      "Check the next file.",
      "two.txt",
    ]);
    const fileEditSegments = result.current.messages
      .filter((message) => message.fileEdits?.length)
      .map((message) => message.activitySegmentId);
    expect(fileEditSegments).toHaveLength(2);
    expect(fileEditSegments[0]).not.toBe(fileEditSegments[1]);
  });

  it("accumulates reasoning_delta chunks on a placeholder until reasoning_end", async () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-r", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-r", {
        event: "reasoning_delta",
        chat_id: "chat-r",
        text: "Let me think ",
      });
      fake.emit("chat-r", {
        event: "reasoning_delta",
        chat_id: "chat-r",
        text: "step by step.",
      });
    });

    await flushStreamFrame();

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].role).toBe("assistant");
    expect(result.current.messages[0].reasoning).toBe("Let me think step by step.");
    expect(result.current.messages[0].reasoningStreaming).toBe(true);

    act(() => {
      fake.emit("chat-r", { event: "reasoning_end", chat_id: "chat-r" });
    });

    expect(result.current.messages[0].reasoningStreaming).toBe(false);
    expect(result.current.messages[0].reasoning).toBe("Let me think step by step.");
  });

  it("absorbs a streaming reasoning placeholder into the answer turn that follows", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-r2", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-r2", {
        event: "reasoning_delta",
        chat_id: "chat-r2",
        text: "Plan first.",
      });
      fake.emit("chat-r2", { event: "reasoning_end", chat_id: "chat-r2" });
      fake.emit("chat-r2", {
        event: "delta",
        chat_id: "chat-r2",
        text: "The answer is 42.",
      });
      fake.emit("chat-r2", { event: "stream_end", chat_id: "chat-r2" });
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].content).toBe("The answer is 42.");
    expect(result.current.messages[0].reasoning).toBe("Plan first.");
    expect(result.current.messages[0].reasoningStreaming).toBe(false);
  });

  it("ignores empty reasoning_delta frames", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-r3", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-r3", {
        event: "reasoning_delta",
        chat_id: "chat-r3",
        text: "",
      });
    });

    expect(result.current.messages).toHaveLength(0);
  });

  it("treats legacy kind=reasoning messages as a complete delta + end pair", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-r4", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-r4", {
        event: "message",
        chat_id: "chat-r4",
        text: "one-shot reasoning",
        kind: "reasoning",
      });
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].reasoning).toBe("one-shot reasoning");
    expect(result.current.messages[0].reasoningStreaming).toBe(false);
  });

  it("starts a new Thought block when reasoning arrives after visible output", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-r5", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-r5", {
        event: "delta",
        chat_id: "chat-r5",
        text: "hi~",
      });
      fake.emit("chat-r5", { event: "stream_end", chat_id: "chat-r5" });
      fake.emit("chat-r5", {
        event: "reasoning_delta",
        chat_id: "chat-r5",
        text: "This reasoning arrived after the answer stream.",
      });
      fake.emit("chat-r5", { event: "reasoning_end", chat_id: "chat-r5" });
    });

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0].content).toBe("hi~");
    expect(result.current.messages[0].reasoning).toBeUndefined();
    expect(result.current.messages[1].content).toBe("");
    expect(result.current.messages[1].reasoning).toBe(
      "This reasoning arrived after the answer stream.",
    );
    expect(result.current.messages[1].reasoningStreaming).toBe(false);
  });

  it("stamps completed live Thought blocks with their own latency", async () => {
    const dateNow = vi.spyOn(Date, "now");
    let now = Date.UTC(2026, 5, 1, 0, 0, 0);
    dateNow.mockImplementation(() => now);
    try {
      const fake = fakeClient();
      const { result } = renderHook(() => useNanobotStream("chat-r5-lat", EMPTY_MESSAGES), {
        wrapper: wrap(fake.client),
      });
      await act(async () => {});

      act(() => {
        fake.emit("chat-r5-lat", {
          event: "reasoning_delta",
          chat_id: "chat-r5-lat",
          text: "Thinking through the tests.",
        });
      });
      await act(async () => {
        await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
      });

      expect(result.current.messages[0].createdAt).toBe(now);
      now += 2100;
      act(() => {
        fake.emit("chat-r5-lat", { event: "reasoning_end", chat_id: "chat-r5-lat" });
      });

      expect(result.current.messages[0].reasoningStreaming).toBe(false);
      expect(result.current.messages[0].latencyMs).toBe(2100);
    } finally {
      dateNow.mockRestore();
    }
  });

  it("keeps alternating reasoning and answer deltas in separate ordered blocks", async () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-r5b", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-r5b", {
        event: "reasoning_delta",
        chat_id: "chat-r5b",
        text: "Plan first.",
      });
      fake.emit("chat-r5b", {
        event: "delta",
        chat_id: "chat-r5b",
        text: "Visible progress.",
      });
      fake.emit("chat-r5b", {
        event: "reasoning_delta",
        chat_id: "chat-r5b",
        text: "Think again.",
      });
      fake.emit("chat-r5b", {
        event: "delta",
        chat_id: "chat-r5b",
        text: "Final visible text.",
      });
    });

    await flushStreamFrame();

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0]).toMatchObject({
      role: "assistant",
      reasoning: "Plan first.",
      content: "Visible progress.",
    });
    expect(result.current.messages[1]).toMatchObject({
      role: "assistant",
      reasoning: "Think again.",
      content: "Final visible text.",
    });
    expect(result.current.messages[1].activitySegmentId).not.toBe(
      result.current.messages[0].activitySegmentId,
    );
  });

  it("does not attach a new turn's reasoning across the latest user boundary", async () => {
    const fake = fakeClient();
    const initialMessages = [
      {
        id: "a-prev",
        role: "assistant" as const,
        content: "Previous answer.",
        reasoning: "Previous thought.",
        createdAt: Date.now(),
      },
      {
        id: "u-next",
        role: "user" as const,
        content: "Next question",
        createdAt: Date.now(),
      },
    ];
    const { result } = renderHook(
      () => useNanobotStream("chat-r6", initialMessages),
      { wrapper: wrap(fake.client) },
    );

    act(() => {
      fake.emit("chat-r6", {
        event: "reasoning_delta",
        chat_id: "chat-r6",
        text: "New turn thinking.",
      });
    });

    await flushStreamFrame();

    expect(result.current.messages).toHaveLength(3);
    expect(result.current.messages[0].reasoning).toBe("Previous thought.");
    expect(result.current.messages[2].role).toBe("assistant");
    expect(result.current.messages[2].content).toBe("");
    expect(result.current.messages[2].reasoning).toBe("New turn thinking.");
    expect(result.current.messages[2].reasoningStreaming).toBe(true);
  });

  it("does not attach reasoning across a tool trace boundary", async () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-r7", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-r7", {
        event: "reasoning_delta",
        chat_id: "chat-r7",
        text: "First reasoning.",
      });
      fake.emit("chat-r7", { event: "reasoning_end", chat_id: "chat-r7" });
      fake.emit("chat-r7", {
        event: "message",
        chat_id: "chat-r7",
        text: "web_search({\"query\":\"OpenClaw\"})",
        kind: "tool_hint",
      });
      fake.emit("chat-r7", {
        event: "reasoning_delta",
        chat_id: "chat-r7",
        text: "Second reasoning.",
      });
    });

    await flushStreamFrame();

    expect(result.current.messages).toHaveLength(3);
    expect(result.current.messages.map((m) => m.kind ?? "message")).toEqual([
      "message",
      "trace",
      "message",
    ]);
    expect(result.current.messages[0].reasoning).toBe("First reasoning.");
    expect(result.current.messages[1].traces).toEqual([
      "web_search({\"query\":\"OpenClaw\"})",
    ]);
    expect(result.current.messages[2].reasoning).toBe("Second reasoning.");
  });

  it("preserves closed reasoning slices when the tool trace is unavailable", async () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-r8", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-r8", {
        event: "reasoning_delta",
        chat_id: "chat-r8",
        text: "First reasoning.",
        turn_id: "turn-r8",
        turn_phase: "reasoning",
        turn_seq: 1,
      });
      fake.emit("chat-r8", {
        event: "reasoning_end",
        chat_id: "chat-r8",
        turn_id: "turn-r8",
        turn_phase: "reasoning",
        turn_seq: 2,
      });
      fake.emit("chat-r8", {
        event: "reasoning_delta",
        chat_id: "chat-r8",
        text: "Second reasoning.",
        turn_id: "turn-r8",
        turn_phase: "reasoning",
        turn_seq: 3,
      });
      fake.emit("chat-r8", {
        event: "reasoning_end",
        chat_id: "chat-r8",
        turn_id: "turn-r8",
        turn_phase: "reasoning",
        turn_seq: 4,
      });
      fake.emit("chat-r8", {
        event: "message",
        chat_id: "chat-r8",
        text: "Final answer.",
        turn_id: "turn-r8",
        turn_phase: "answer",
        turn_seq: 5,
      });
      fake.emit("chat-r8", {
        event: "turn_end",
        chat_id: "chat-r8",
        turn_id: "turn-r8",
        turn_phase: "complete",
        turn_seq: 6,
      });
    });

    await flushStreamFrame();

    expect(result.current.messages.map((message) => ({
      reasoning: message.reasoning,
      content: message.content,
    }))).toEqual([
      { reasoning: "First reasoning.", content: "" },
      { reasoning: "Second reasoning.", content: "Final answer." },
    ]);

    const units = normalizeActivityTimeline(result.current.messages);
    expect(units).toHaveLength(2);
    expect(units[0].type === "activity" ? units[0].messages.map((message) => (
      message.reasoning || message.traces?.[0]
    )) : []).toEqual([
      "First reasoning.",
      "Second reasoning.",
    ]);
    expect(units[1]).toMatchObject({
      type: "message",
      message: { content: "Final answer." },
    });
  });

  it("keeps tool-call reasoning before the matching live tool trace", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-tool-reasoning", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-tool-reasoning", {
        event: "reasoning_delta",
        chat_id: "chat-tool-reasoning",
        text: "I should search first.",
      });
      fake.emit("chat-tool-reasoning", {
        event: "reasoning_end",
        chat_id: "chat-tool-reasoning",
      });
      fake.emit("chat-tool-reasoning", {
        event: "message",
        chat_id: "chat-tool-reasoning",
        text: "web_search({\"query\":\"hermes\"})",
        kind: "tool_hint",
      });
      fake.emit("chat-tool-reasoning", {
        event: "turn_end",
        chat_id: "chat-tool-reasoning",
      });
    });

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0]).toMatchObject({
      role: "assistant",
      content: "",
      reasoning: "I should search first.",
      reasoningStreaming: false,
      isStreaming: false,
    });
    expect(result.current.messages[1]).toMatchObject({
      role: "tool",
      kind: "trace",
      traces: ["web_search({\"query\":\"hermes\"})"],
    });
  });

  it("absorbs non-streamed final answers into the preceding reasoning placeholder", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-final-reasoning", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-final-reasoning", {
        event: "message",
        chat_id: "chat-final-reasoning",
        text: "web_search({\"query\":\"hermes\"})",
        kind: "tool_hint",
      });
      fake.emit("chat-final-reasoning", {
        event: "reasoning_delta",
        chat_id: "chat-final-reasoning",
        text: "Got results; now summarize.",
      });
      fake.emit("chat-final-reasoning", {
        event: "reasoning_end",
        chat_id: "chat-final-reasoning",
      });
      fake.emit("chat-final-reasoning", {
        event: "message",
        chat_id: "chat-final-reasoning",
        text: "Hermes is an open-source agent project.",
      });
      fake.emit("chat-final-reasoning", {
        event: "turn_end",
        chat_id: "chat-final-reasoning",
      });
    });

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0]).toMatchObject({
      role: "tool",
      kind: "trace",
    });
    expect(result.current.messages[1]).toMatchObject({
      role: "assistant",
      content: "Hermes is an open-source agent project.",
      reasoning: "Got results; now summarize.",
      reasoningStreaming: false,
      isStreaming: false,
    });
  });

  it("preserves reasoning-only output when a turn ends without an answer", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-empty-thinking", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-empty-thinking", {
        event: "reasoning_delta",
        chat_id: "chat-empty-thinking",
        text: "thinking without final text",
      });
      fake.emit("chat-empty-thinking", {
        event: "reasoning_end",
        chat_id: "chat-empty-thinking",
      });
      fake.emit("chat-empty-thinking", {
        event: "turn_end",
        chat_id: "chat-empty-thinking",
      });
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0]).toMatchObject({
      role: "assistant",
      content: "",
      reasoning: "thinking without final text",
      reasoningStreaming: false,
      isStreaming: false,
    });
    expect(result.current.isStreaming).toBe(false);
  });

  it("keeps earlier reasoning before sending the next user turn", () => {
    const fake = fakeClient();
    const initialMessages = [
      {
        id: "stale-thinking",
        role: "assistant" as const,
        content: "",
        reasoning: "leftover thinking",
        reasoningStreaming: false,
        createdAt: Date.now(),
      },
    ];
    const { result } = renderHook(
      () => useNanobotStream("chat-stale-thinking", initialMessages),
      { wrapper: wrap(fake.client) },
    );

    act(() => {
      result.current.send("fine");
    });

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0]).toMatchObject({
      role: "assistant",
      reasoning: "leftover thinking",
    });
    expect(result.current.messages[1].role).toBe("user");
    expect(result.current.messages[1].content).toBe("fine");
    expect(result.current.messages[1].turnId).toEqual(expect.any(String));
    expect(result.current.messages[1].turnPhase).toBe("user");
    expect(result.current.messages[1].deliveryStatus).toBe("sending");
  });

  it("returns the submitted turn identity used by the optimistic row and wire frame", () => {
    const fake = fakeClient();
    const { result } = renderHook(
      () => useNanobotStream("chat-submitted-turn", EMPTY_MESSAGES),
      { wrapper: wrap(fake.client) },
    );

    let submitted: ReturnType<typeof result.current.send> = null;
    act(() => {
      submitted = result.current.send("bind the camera");
    });

    expect(submitted).not.toBeNull();
    expect(submitted?.sideChannel).toBe(false);
    expect(result.current.messages[0]).toMatchObject({
      id: submitted?.userMessageId,
      turnId: submitted?.turnId,
      role: "user",
    });
    expect(fake.client.sendMessage).toHaveBeenCalledWith(
      "chat-submitted-turn",
      "bind the camera",
      undefined,
      expect.objectContaining({ turnId: submitted?.turnId }),
    );
  });

  it("marks an optimistic turn accepted when its acknowledgement arrives", () => {
    const fake = fakeClient();
    const { result } = renderHook(
      () => useNanobotStream("chat-accept-one", EMPTY_MESSAGES),
      { wrapper: wrap(fake.client) },
    );
    let submitted: ReturnType<typeof result.current.send> = null;
    act(() => {
      submitted = result.current.send("hello");
    });

    act(() => {
      fake.emit("chat-accept-one", {
        event: "message_accepted",
        chat_id: "chat-accept-one",
        turn_id: submitted!.turnId,
      });
    });

    expect(result.current.messages).toEqual([
      expect.objectContaining({
        id: submitted!.userMessageId,
        deliveryStatus: "accepted",
      }),
    ]);
  });

  it("projects a user turn submitted from another attached client exactly once", () => {
    const fake = fakeClient();
    const { result } = renderHook(
      () => useNanobotStream("chat-shared", EMPTY_MESSAGES),
      { wrapper: wrap(fake.client) },
    );
    const event: InboundEvent = {
      event: "user_message",
      chat_id: "chat-shared",
      text: "hello from terminal A",
      turn_id: "remote-turn",
      active_turn_id: "remote-turn",
      starts_turn: true,
      started_at: 1_700_000_000,
      media_urls: [{ kind: "file", url: "/api/media/sig/report", name: "report.pdf" }],
      cli_apps: [{ name: "drawio", display_name: "Draw.io" }],
      mcp_presets: [{ name: "github", display_name: "GitHub" }],
      session_mentions: [{
        name: "pricing",
        session_key: "websocket:pricing",
        title: "Pricing",
      }],
    };

    act(() => {
      fake.emit("chat-shared", event);
      fake.emit("chat-shared", event);
    });

    expect(result.current.messages).toEqual([
      expect.objectContaining({
        role: "user",
        content: "hello from terminal A",
        turnId: "remote-turn",
        deliveryStatus: "accepted",
        createdAt: expect.any(Number),
        media: [{ kind: "file", url: "/api/media/sig/report", name: "report.pdf" }],
        cliApps: [{ name: "drawio", display_name: "Draw.io" }],
        mcpPresets: [{ name: "github", display_name: "GitHub" }],
        sessionMentions: [{
          name: "pricing",
          session_key: "websocket:pricing",
          title: "Pricing",
        }],
      }),
    ]);
    expect(result.current.isStreaming).toBe(true);
    expect(result.current.runStartedAt).toBe(1_700_000_000);
  });

  it("projects a cross-session input with its public handle exactly once", () => {
    const fake = fakeClient();
    const { result } = renderHook(
      () => useNanobotStream("chat-target", EMPTY_MESSAGES),
      { wrapper: wrap(fake.client) },
    );
    const event: InboundEvent = {
      event: "user_message",
      chat_id: "chat-target",
      text: "Please review this.",
      created_at_ms: 1_700_000_000_123,
      starts_turn: false,
      provenance: {
        session_message: {
          message_id: "message-1",
          session: {
            id: "handle_0123456789abcdef0123456789abcdef",
            name: "mira-0123456789",
          },
        },
      },
    };

    act(() => {
      fake.emit("chat-target", event);
      fake.emit("chat-target", event);
    });

    expect(result.current.messages).toEqual([expect.objectContaining({
      id: "session-message:message-1",
      role: "user",
      content: "Please review this.",
      createdAt: 1_700_000_000_123,
      sessionMessage: event.provenance?.session_message,
    })]);
    expect(result.current.isStreaming).toBe(true);
  });

  it("marks only the optimistic turn named by a correlated rejection as failed", () => {
    const fake = fakeClient();
    const { result } = renderHook(
      () => useNanobotStream("chat-reject-one", EMPTY_MESSAGES),
      { wrapper: wrap(fake.client) },
    );
    let first: ReturnType<typeof result.current.send> = null;
    let second: ReturnType<typeof result.current.send> = null;
    act(() => {
      first = result.current.send("first");
      second = result.current.send("second");
    });
    fake.setUnsettled("chat-reject-one", true);

    act(() => {
      fake.emitError({
        kind: "turn_rejected",
        detail: "message_rejected",
        chatId: "chat-reject-one",
        turnId: first!.turnId,
      });
    });

    expect(result.current.messages).toEqual([
      expect.objectContaining({
        id: first!.userMessageId,
        turnId: first!.turnId,
        content: "first",
        deliveryStatus: "failed",
        deliveryErrorKind: "turn_rejected",
      }),
      expect.objectContaining({
        id: second!.userMessageId,
        turnId: second!.turnId,
        content: "second",
        deliveryStatus: "sending",
      }),
    ]);
    expect(result.current.isStreaming).toBe(true);
    expect(result.current.streamError).toMatchObject({
      kind: "turn_rejected",
      turnId: first!.turnId,
    });
  });

  it("falls back to the previous running turn when the newer turn is rejected", () => {
    const fake = fakeClient();
    const { result } = renderHook(
      () => useNanobotStream("chat-reject-new", EMPTY_MESSAGES),
      { wrapper: wrap(fake.client) },
    );
    let first: ReturnType<typeof result.current.send> = null;
    let second: ReturnType<typeof result.current.send> = null;
    act(() => {
      first = result.current.send("first");
      fake.emit("chat-reject-new", {
        event: "goal_status",
        chat_id: "chat-reject-new",
        status: "running",
        started_at: 1234,
        turn_id: first!.turnId,
      });
      second = result.current.send("second");
    });

    act(() => {
      fake.emitError({
        kind: "turn_rejected",
        detail: "attachment_rejected",
        chatId: "chat-reject-new",
        turnId: second!.turnId,
      });
    });

    expect(result.current.messages).toEqual([
      expect.objectContaining({
        id: first!.userMessageId,
        turnId: first!.turnId,
        deliveryStatus: "accepted",
      }),
      expect.objectContaining({
        id: second!.userMessageId,
        turnId: second!.turnId,
        deliveryStatus: "failed",
      }),
    ]);
    expect(result.current.runStartedAt).toBe(1234);
    expect(result.current.isStreaming).toBe(true);
  });

  it("ends the spinner and drops pending stream work when the only turn is rejected", async () => {
    const fake = fakeClient();
    const { result } = renderHook(
      () => useNanobotStream("chat-reject-only", EMPTY_MESSAGES),
      { wrapper: wrap(fake.client) },
    );
    let submitted: ReturnType<typeof result.current.send> = null;
    act(() => {
      submitted = result.current.send("only");
      fake.emit("chat-reject-only", {
        event: "delta",
        chat_id: "chat-reject-only",
        turn_id: submitted!.turnId,
        text: "must not survive",
      });
    });

    act(() => {
      fake.emitError({
        kind: "turn_rejected",
        detail: "access_denied",
        chatId: "chat-reject-only",
        turnId: submitted!.turnId,
      });
    });
    await flushStreamFrame();

    expect(result.current.messages).toEqual([
      expect.objectContaining({
        id: submitted!.userMessageId,
        deliveryStatus: "failed",
        deliveryErrorKind: "turn_rejected",
      }),
    ]);
    expect(result.current.runStartedAt).toBeNull();
    expect(result.current.isStreaming).toBe(false);
  });

  it("applies a correlated rejection replayed through the chat event queue", () => {
    const fake = fakeClient();
    const { result } = renderHook(
      () => useNanobotStream("chat-replayed-reject", EMPTY_MESSAGES),
      { wrapper: wrap(fake.client) },
    );
    let submitted: ReturnType<typeof result.current.send> = null;
    act(() => {
      submitted = result.current.send("queued optimistic row");
    });

    act(() => {
      fake.emit("chat-replayed-reject", {
        event: "error",
        detail: "message_rejected",
        reason: "policy",
        chat_id: "chat-replayed-reject",
        turn_id: submitted!.turnId,
      });
    });

    expect(result.current.messages).toEqual([
      expect.objectContaining({
        id: submitted!.userMessageId,
        deliveryStatus: "failed",
      }),
    ]);
    expect(result.current.streamError).toMatchObject({
      kind: "turn_rejected",
      chatId: "chat-replayed-reject",
      turnId: submitted!.turnId,
    });
  });

  it("does not show or apply an error correlated to another chat", () => {
    const fake = fakeClient();
    const { result } = renderHook(
      () => useNanobotStream("chat-visible", EMPTY_MESSAGES),
      { wrapper: wrap(fake.client) },
    );
    let submitted: ReturnType<typeof result.current.send> = null;
    act(() => {
      submitted = result.current.send("stay");
    });

    act(() => {
      fake.emitError({
        kind: "turn_rejected",
        detail: "message_rejected",
        chatId: "chat-background",
        turnId: submitted!.turnId,
      });
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].content).toBe("stay");
    expect(result.current.streamError).toBeNull();
  });

  it("shows an uncorrelated 1009 fault without rolling back the current turn", () => {
    const fake = fakeClient();
    const { result } = renderHook(
      () => useNanobotStream("chat-generic-1009", EMPTY_MESSAGES),
      { wrapper: wrap(fake.client) },
    );
    act(() => {
      result.current.send("stay visible");
      fake.emitError({ kind: "message_too_big" });
    });

    expect(result.current.messages).toEqual([
      expect.objectContaining({ role: "user", content: "stay visible" }),
    ]);
    expect(result.current.streamError).toEqual({ kind: "message_too_big" });
  });

  it("marks rejected side-channel guidance failed without stopping the main run", () => {
    const fake = fakeClient();
    const { result } = renderHook(
      () => useNanobotStream("chat-side-reject", EMPTY_MESSAGES),
      { wrapper: wrap(fake.client) },
    );
    let main: ReturnType<typeof result.current.send> = null;
    let side: ReturnType<typeof result.current.send> = null;
    act(() => {
      main = result.current.send("main");
      fake.emit("chat-side-reject", {
        event: "goal_status",
        chat_id: "chat-side-reject",
        status: "running",
        started_at: 9876,
        turn_id: main!.turnId,
      });
      side = result.current.send("guidance", undefined, { sideChannel: true });
    });

    act(() => {
      fake.emitError({
        kind: "turn_rejected",
        detail: "message_rejected",
        chatId: "chat-side-reject",
        turnId: side!.turnId,
      });
    });

    expect(result.current.messages).toEqual([
      expect.objectContaining({
        id: main!.userMessageId,
        turnId: main!.turnId,
        deliveryStatus: "accepted",
      }),
      expect.objectContaining({
        id: side!.userMessageId,
        turnId: side!.turnId,
        deliveryStatus: "failed",
      }),
    ]);
    expect(result.current.runStartedAt).toBe(9876);
    expect(result.current.isStreaming).toBe(true);
  });

  it("adds optimistic user file attachments as media", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-file-send", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });
    const attachment = {
      media: {
        data_url: "data:application/pdf;base64,JVBERi0xLjQ=",
        name: "report.pdf",
      },
      preview: {
        kind: "file" as const,
        url: "data:application/pdf;base64,JVBERi0xLjQ=",
        name: "report.pdf",
      },
    };

    act(() => {
      result.current.send("summarize", [attachment]);
    });

    expect(result.current.messages[0].media).toEqual([attachment.preview]);
    expect(result.current.messages[0].images).toBeUndefined();
    expect(fake.client.sendMessage).toHaveBeenCalledWith(
      "chat-file-send",
      "summarize",
      [attachment.media],
      expect.objectContaining({ turnId: expect.any(String) }),
    );
  });

  it("inlines quoted context into the optimistic and outbound user message", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-quote", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      result.current.send("What about this?", undefined, {
        quotedContext: "selected assistant excerpt",
      });
    });

    const expectedContent = "> [!QUOTE]\n> selected assistant excerpt\n\nWhat about this?";
    expect(result.current.messages[0].content).toBe(expectedContent);
    const outbound = fake.client.sendMessage.mock.calls.at(-1)!;
    expect(outbound[1]).toBe(expectedContent);
    expect(outbound[3]).not.toHaveProperty("quotedContext");
  });

  it("attaches assistant media_urls to complete messages", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-m", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-m", {
        event: "message",
        chat_id: "chat-m",
        text: "video ready",
        media_urls: [{ url: "/api/media/sig/payload", name: "demo.mp4" }],
      });
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].media).toEqual([
      { kind: "video", url: "/api/media/sig/payload", name: "demo.mp4" },
    ]);
  });

  it("keeps assistant html media as a file attachment", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-html-media", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-html-media", {
        event: "message",
        chat_id: "chat-html-media",
        text: "file ready",
        media_urls: [{ url: "/api/media/sig/html", name: "index.html" }],
      });
    });

    expect(result.current.messages[0].media).toEqual([
      { kind: "file", url: "/api/media/sig/html", name: "index.html" },
    ]);
  });

  it("infers assistant svg media as an image attachment", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-svg-media", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-svg-media", {
        event: "message",
        chat_id: "chat-svg-media",
        text: "chart ready",
        media_urls: [{ url: "/api/media/sig/svg", name: "growth.svg" }],
      });
    });

    expect(result.current.messages[0].media).toEqual([
      { kind: "image", url: "/api/media/sig/svg", name: "growth.svg" },
    ]);
  });

  it("corrects explicit image media when the name is a non-image file", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-mislabelled-html", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-mislabelled-html", {
        event: "message",
        chat_id: "chat-mislabelled-html",
        text: "file ready",
        media_urls: [{ kind: "image", url: "/api/media/sig/html", name: "index.html" }],
      });
    });

    expect(result.current.messages[0].media).toEqual([
      { kind: "file", url: "/api/media/sig/html", name: "index.html" },
    ]);
  });

  it("suppresses redundant stream confirmation after assistant media", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-img-result", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-img-result", {
        event: "message",
        chat_id: "chat-img-result",
        text: "image ready",
        media_urls: [{ url: "/api/media/sig/image", name: "generated.png" }],
      });
      fake.emit("chat-img-result", {
        event: "message",
        chat_id: "chat-img-result",
        text: "message()",
        kind: "tool_hint",
      });
      fake.emit("chat-img-result", {
        event: "delta",
        chat_id: "chat-img-result",
        text: "发送成功",
      });
      fake.emit("chat-img-result", {
        event: "stream_end",
        chat_id: "chat-img-result",
      });
      fake.emit("chat-img-result", {
        event: "turn_end",
        chat_id: "chat-img-result",
      });
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].content).toBe("image ready");
    expect(result.current.messages[0].media).toHaveLength(1);
  });

  it("stops the active turn without adding a user slash command bubble", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-stop", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      result.current.send("long task");
    });
    expect(result.current.messages).toHaveLength(1);
    expect(result.current.isStreaming).toBe(true);

    act(() => {
      result.current.stop();
    });

    expect(fake.client.sendMessage).toHaveBeenLastCalledWith("chat-stop", "/stop");
    expect(fake.client.finishRunLocally).toHaveBeenCalledWith("chat-stop");
    expect(result.current.isStreaming).toBe(false);
    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].content).toBe("long task");
  });

  it("does not mark side-channel slash commands as streaming", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-status", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      result.current.send("/status", undefined, { sideChannel: true });
    });

    const call = fake.client.sendMessage.mock.calls.at(-1)!;
    const turnId = call[3]?.turnId;
    expect(call[3]).not.toHaveProperty("sideChannel");
    expect(call[3]).toMatchObject({ startsNewRun: false });
    expect(result.current.isStreaming).toBe(false);

    act(() => {
      fake.emit("chat-status", {
        event: "message",
        chat_id: "chat-status",
        text: "status reply",
        turn_id: turnId,
      });
    });

    expect(result.current.isStreaming).toBe(false);
    expect(result.current.messages.map((message) => message.content)).toEqual([
      "/status",
      "status reply",
    ]);
  });

  it("finalizes active streaming before turn-ending side-channel commands", async () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-new", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      result.current.send("long task");
    });
    const activeTurnId = fake.client.sendMessage.mock.calls.at(-1)![3]?.turnId;

    act(() => {
      fake.emit("chat-new", {
        event: "delta",
        chat_id: "chat-new",
        text: "partial answer",
        turn_id: activeTurnId,
      });
    });
    await flushStreamFrame();

    expect(result.current.isStreaming).toBe(true);
    expect(result.current.messages.find((message) => message.content === "partial answer"))
      .toMatchObject({ isStreaming: true });

    act(() => {
      result.current.send("/new", undefined, {
        sideChannel: true,
        finalizeActiveTurn: true,
      });
    });

    const newCall = fake.client.sendMessage.mock.calls.at(-1)!;
    expect(newCall[3]).not.toHaveProperty("sideChannel");
    expect(newCall[3]).not.toHaveProperty("finalizeActiveTurn");
    expect(result.current.isStreaming).toBe(false);
    expect(result.current.messages.find((message) => message.content === "partial answer"))
      .toMatchObject({ isStreaming: false });

    act(() => {
      fake.emit("chat-new", {
        event: "message",
        chat_id: "chat-new",
        text: "New session started.",
        turn_id: newCall[3]?.turnId,
      });
    });

    expect(result.current.isStreaming).toBe(false);
    expect(result.current.messages.map((message) => message.content)).toEqual([
      "long task",
      "partial answer",
      "/new",
      "New session started.",
    ]);
  });

  it("keeps the turn active after stream_end while side-channel replies arrive", () => {
    vi.useFakeTimers();
    try {
      const fake = fakeClient();
      const { result } = renderHook(() => useNanobotStream("chat-status-loop", EMPTY_MESSAGES), {
        wrapper: wrap(fake.client),
      });

      act(() => {
        result.current.send("write normally");
      });
      const promptTurnId = fake.client.sendMessage.mock.calls.at(-1)![3]?.turnId;

      act(() => {
        fake.emit("chat-status-loop", {
          event: "stream_end",
          chat_id: "chat-status-loop",
          text: "done",
          turn_id: promptTurnId,
        });
      });

      act(() => {
        result.current.send("/status", undefined, { sideChannel: true });
      });
      const statusTurnId = fake.client.sendMessage.mock.calls.at(-1)![3]?.turnId;

      act(() => {
        fake.emit("chat-status-loop", {
          event: "message",
          chat_id: "chat-status-loop",
          text: "status reply",
          turn_id: statusTurnId,
        });
      });

      expect(result.current.isStreaming).toBe(true);

      act(() => {
        vi.advanceTimersByTime(1000);
      });

      expect(result.current.isStreaming).toBe(true);
      expect(result.current.messages.find((message) => message.content === "done")).toMatchObject({
        isStreaming: true,
      });

      act(() => {
        fake.emit("chat-status-loop", {
          event: "turn_end",
          chat_id: "chat-status-loop",
          turn_id: promptTurnId,
        });
      });

      expect(result.current.isStreaming).toBe(false);
      expect(result.current.messages.find((message) => message.content === "done")).toMatchObject({
        isStreaming: false,
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps guided output in place while the active turn resumes", async () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-guide", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      result.current.send("research this");
    });
    const activeTurnId = fake.client.sendMessage.mock.calls.at(-1)![3]?.turnId;

    act(() => {
      fake.emit("chat-guide", {
        event: "delta",
        chat_id: "chat-guide",
        text: "Initial findings",
        turn_id: activeTurnId,
      });
    });
    await flushStreamFrame();

    act(() => {
      result.current.send("focus on primary sources", undefined, {
        continueActiveTurn: true,
      });
    });

    const guideCall = fake.client.sendMessage.mock.calls.at(-1)!;
    expect(guideCall[3]).not.toHaveProperty("continueActiveTurn");
    expect(guideCall[3]).toMatchObject({ startsNewRun: false });
    expect(result.current.messages.map((message) => message.content)).toEqual([
      "research this",
      "Initial findings",
      "focus on primary sources",
    ]);

    act(() => {
      fake.emit("chat-guide", {
        event: "stream_end",
        chat_id: "chat-guide",
        text: "Initial findings",
        resuming: true,
        turn_id: activeTurnId,
      });
    });

    expect(result.current.isStreaming).toBe(true);
    expect(result.current.messages).toHaveLength(3);
    expect(result.current.messages[1]).toMatchObject({
      content: "Initial findings",
      isStreaming: true,
    });

    act(() => {
      fake.emit("chat-guide", {
        event: "delta",
        chat_id: "chat-guide",
        text: "Updated with primary sources",
        turn_id: activeTurnId,
      });
    });
    await flushStreamFrame();

    expect(result.current.messages.map((message) => message.content)).toEqual([
      "research this",
      "Initial findings",
      "focus on primary sources",
      "Updated with primary sources",
    ]);
    expect(result.current.messages[3]).toMatchObject({ isStreaming: true });

    act(() => {
      fake.emit("chat-guide", {
        event: "turn_end",
        chat_id: "chat-guide",
        turn_id: activeTurnId,
      });
    });

    expect(result.current.isStreaming).toBe(false);
    expect(result.current.messages.every((message) => !message.isStreaming)).toBe(true);
  });

  it("keeps length-recovery segments in one assistant message", async () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-length", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      result.current.send("give a long answer");
    });
    const activeTurnId = fake.client.sendMessage.mock.calls.at(-1)![3]?.turnId;

    act(() => {
      fake.emit("chat-length", {
        event: "delta",
        chat_id: "chat-length",
        text: "first ",
        turn_id: activeTurnId,
      });
    });
    await flushStreamFrame();
    const assistantId = result.current.messages[1].id;

    act(() => {
      fake.emit("chat-length", {
        event: "stream_end",
        chat_id: "chat-length",
        text: "first ",
        resuming: true,
        merge_next: true,
        turn_id: activeTurnId,
      });
    });

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[1]).toMatchObject({
      id: assistantId,
      content: "first ",
      isStreaming: true,
    });

    act(() => {
      fake.emit("chat-length", {
        event: "delta",
        chat_id: "chat-length",
        text: "second",
        turn_id: activeTurnId,
      });
    });
    await flushStreamFrame();

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[1]).toMatchObject({
      id: assistantId,
      content: "first second",
      isStreaming: true,
    });

    act(() => {
      fake.emit("chat-length", {
        event: "turn_end",
        chat_id: "chat-length",
        turn_id: activeTurnId,
      });
    });

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[1]).toMatchObject({
      id: assistantId,
      content: "first second",
      isStreaming: false,
    });
  });

  it("keeps streaming alive across stream_end when tool activity follows", async () => {
    const fake = fakeClient();
    const onTurnEnd = vi.fn();
    const { result } = renderHook(() => useNanobotStream("chat-s", EMPTY_MESSAGES, false, onTurnEnd), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-s", {
        event: "delta",
        chat_id: "chat-s",
        text: "Hello",
      });
    });

    await flushStreamFrame();

    expect(result.current.isStreaming).toBe(true);
    expect(result.current.messages[0]).toMatchObject({
      role: "assistant",
      content: "Hello",
      isStreaming: true,
    });

    act(() => {
      fake.emit("chat-s", {
        event: "stream_end",
        chat_id: "chat-s",
      });
    });

    expect(result.current.isStreaming).toBe(true);
    expect(result.current.messages[0].isStreaming).toBe(true);

    act(() => {
      fake.emit("chat-s", {
        event: "message",
        chat_id: "chat-s",
        kind: "progress",
        text: "Calling tool",
      });
    });

    expect(result.current.isStreaming).toBe(true);
    expect(result.current.messages.at(-1)).toMatchObject({
      role: "tool",
      content: "Calling tool",
    });

    act(() => {
      fake.emit("chat-s", {
        event: "turn_end",
        chat_id: "chat-s",
      });
    });

    expect(result.current.isStreaming).toBe(false);
    expect(result.current.messages.every((message) => !message.isStreaming)).toBe(true);
    expect(onTurnEnd).toHaveBeenCalledTimes(1);
  });

  it("replaces streamed content with final stream_end text when provided", async () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-stream-final", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-stream-final", {
        event: "delta",
        chat_id: "chat-stream-final",
        text: "![Diagram](diagram.png)",
      });
    });

    await flushStreamFrame();

    act(() => {
      fake.emit("chat-stream-final", {
        event: "stream_end",
        chat_id: "chat-stream-final",
        text: "![Diagram](/api/media/sig/payload)",
      });
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0]).toMatchObject({
      role: "assistant",
      content: "![Diagram](/api/media/sig/payload)",
      isStreaming: true,
    });
  });

  it("creates an assistant bubble from final stream_end text without prior delta", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-stream-end-only", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-stream-end-only", {
        event: "stream_end",
        chat_id: "chat-stream-end-only",
        text: "![Diagram](/api/media/sig/payload)",
      });
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0]).toMatchObject({
      role: "assistant",
      content: "![Diagram](/api/media/sig/payload)",
      isStreaming: true,
    });
  });

  it("stamps completion time and latency on the last assistant bubble from turn_end", () => {
    const completedAt = Date.UTC(2026, 6, 25, 12, 34, 56);
    const dateNow = vi.spyOn(Date, "now").mockReturnValue(completedAt);
    try {
      const fake = fakeClient();
      const { result } = renderHook(() => useNanobotStream("chat-lat", EMPTY_MESSAGES), {
        wrapper: wrap(fake.client),
      });

      act(() => {
        fake.emit("chat-lat", {
          event: "delta",
          chat_id: "chat-lat",
          text: "Hi",
        });
      });

      act(() => {
        fake.emit("chat-lat", {
          event: "turn_end",
          chat_id: "chat-lat",
          latency_ms: 2400,
        });
      });

      const lastAssistant = [...result.current.messages]
        .reverse()
        .find((m) => m.role === "assistant");
      expect(lastAssistant?.latencyMs).toBe(2400);
      expect(lastAssistant?.completedAt).toBe(completedAt);
    } finally {
      dateNow.mockRestore();
    }
  });

  it("tracks goal_status running and clears on idle", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-g", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    expect(result.current.runStartedAt).toBeNull();
    expect(result.current.isStreaming).toBe(false);

    act(() => {
      fake.emit("chat-g", {
        event: "goal_status",
        chat_id: "chat-g",
        status: "running",
        started_at: 1700,
      });
    });
    expect(result.current.runStartedAt).toBe(1700);
    expect(result.current.isStreaming).toBe(true);

    act(() => {
      fake.emit("chat-g", {
        event: "goal_status",
        chat_id: "chat-g",
        status: "idle",
      });
    });
    expect(result.current.runStartedAt).toBeNull();
    expect(result.current.isStreaming).toBe(false);
  });

  it("clears runStartedAt on turn_end even without idle", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-g", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-g", {
        event: "goal_status",
        chat_id: "chat-g",
        status: "running",
        started_at: 1700,
      });
    });
    expect(result.current.runStartedAt).toBe(1700);
    expect(result.current.isStreaming).toBe(true);

    act(() => {
      fake.emit("chat-g", {
        event: "turn_end",
        chat_id: "chat-g",
      });
    });
    expect(result.current.runStartedAt).toBeNull();
    expect(result.current.isStreaming).toBe(false);
  });

  it("restores runStartedAt after switching away and back when goal_status was recorded without a subscriber", () => {
    const fake = fakeClient();
    const { result, rerender } = renderHook(
      ({ chatId }: { chatId: string }) => useNanobotStream(chatId, EMPTY_MESSAGES),
      {
        wrapper: wrap(fake.client),
        initialProps: { chatId: "chat-a" },
      },
    );

    act(() => {
      fake.emit("chat-a", {
        event: "goal_status",
        chat_id: "chat-a",
        status: "running",
        started_at: 4242,
      });
    });
    expect(result.current.runStartedAt).toBe(4242);
    expect(result.current.isStreaming).toBe(true);

    rerender({ chatId: "chat-b" });
    expect(result.current.runStartedAt).toBeNull();
    expect(result.current.isStreaming).toBe(false);

    act(() => {
      fake.emit("chat-a", {
        event: "goal_status",
        chat_id: "chat-a",
        status: "running",
        started_at: 9001,
      });
    });

    rerender({ chatId: "chat-a" });
    expect(result.current.runStartedAt).toBe(9001);
    expect(result.current.isStreaming).toBe(true);
  });

  it("tracks goal_state per chat and restores after switching sessions", () => {
    const fake = fakeClient();
    const { result, rerender } = renderHook(
      ({ chatId }: { chatId: string }) => useNanobotStream(chatId, EMPTY_MESSAGES),
      {
        wrapper: wrap(fake.client),
        initialProps: { chatId: "chat-a" },
      },
    );

    act(() => {
      fake.emit("chat-a", {
        event: "goal_state",
        chat_id: "chat-a",
        goal_state: { active: true, ui_summary: "Alpha" },
      });
    });
    expect(result.current.goalState).toEqual({ active: true, ui_summary: "Alpha" });

    act(() => {
      fake.emit("chat-b", {
        event: "goal_state",
        chat_id: "chat-b",
        goal_state: { active: true, objective: "Beta task" },
      });
    });

    rerender({ chatId: "chat-b" });
    expect(result.current.goalState).toEqual({ active: true, objective: "Beta task" });

    rerender({ chatId: "chat-a" });
    expect(result.current.goalState).toEqual({ active: true, ui_summary: "Alpha" });

    act(() => {
      fake.emit("chat-a", {
        event: "goal_state",
        chat_id: "chat-a",
        goal_state: { active: false },
      });
    });
    expect(result.current.goalState).toEqual({ active: false });
  });

});

describe("live/replay projection before canonical-event revision migration", () => {
  it.each(PROJECTION_FIXTURE_CASES)("matches the shared $name fixture", (fixtureCase) => {
    const fake = fakeClient();
    const { result } = renderHook(
      () => useNanobotStream(fixtureCase.chat_id, fixtureCase.initial_messages),
      { wrapper: wrap(fake.client) },
    );

    for (const event of fixtureCase.live_events) {
      act(() => {
        fake.emit(fixtureCase.chat_id, event);
      });
    }

    expect(normalizeProjection(result.current.messages)).toEqual(fixtureCase.expected);
  });
});
