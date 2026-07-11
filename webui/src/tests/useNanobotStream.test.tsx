import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { useNanobotStream } from "@/hooks/useNanobotStream";
import type { InboundEvent, GoalStateWsPayload } from "@/lib/types";
import { ClientProvider } from "@/providers/ClientProvider";

const EMPTY_MESSAGES: import("@/lib/types").UIMessage[] = [];

function fakeClient() {
  const handlers = new Map<string, Set<(ev: InboundEvent) => void>>();
  const runStartedAtByChatId = new Map<string, number>();
  const goalStateByChatId = new Map<string, GoalStateWsPayload>();

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
      status: "open" as const,
      defaultChatId: null as string | null,
      onStatus: () => () => {},
      onError: () => () => {},
      getRunStartedAt(chatId: string) {
        const v = runStartedAtByChatId.get(chatId);
        return v === undefined ? null : v;
      },
      getGoalState(chatId: string) {
        return goalStateByChatId.get(chatId);
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

  it("prunes reasoning-only placeholders when a turn ends without an answer", () => {
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

    expect(result.current.messages).toHaveLength(0);
    expect(result.current.isStreaming).toBe(false);
  });

  it("drops stale reasoning-only placeholders before sending the next user turn", () => {
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

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].role).toBe("user");
    expect(result.current.messages[0].content).toBe("fine");
    expect(result.current.messages[0].turnId).toEqual(expect.any(String));
    expect(result.current.messages[0].turnPhase).toBe("user");
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

  it("lets stream_end finish streaming while side-channel status replies arrive", () => {
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

      expect(result.current.isStreaming).toBe(false);
      expect(result.current.messages.find((message) => message.content === "done")).toMatchObject({
        isStreaming: false,
      });
    } finally {
      vi.useRealTimers();
    }
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

  it("stamps latency on the last assistant bubble from turn_end", () => {
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

    const lastAssistant = [...result.current.messages].reverse().find((m) => m.role === "assistant");
    expect(lastAssistant?.latencyMs).toBe(2400);
  });

  it("tracks goal_status running and clears on idle", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-g", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    expect(result.current.runStartedAt).toBeNull();

    act(() => {
      fake.emit("chat-g", {
        event: "goal_status",
        chat_id: "chat-g",
        status: "running",
        started_at: 1700,
      });
    });
    expect(result.current.runStartedAt).toBe(1700);

    act(() => {
      fake.emit("chat-g", {
        event: "goal_status",
        chat_id: "chat-g",
        status: "idle",
      });
    });
    expect(result.current.runStartedAt).toBeNull();
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

    act(() => {
      fake.emit("chat-g", {
        event: "turn_end",
        chat_id: "chat-g",
      });
    });
    expect(result.current.runStartedAt).toBeNull();
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

    rerender({ chatId: "chat-b" });
    expect(result.current.runStartedAt).toBeNull();

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
