import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Profiler, StrictMode, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { preloadMarkdownText } from "@/components/MarkdownText";
import { ThreadCameraController } from "@/components/thread/thread-camera";
import { ThreadShell } from "@/components/thread/ThreadShell";
import { SessionSearchDialog } from "@/components/SessionSearchDialog";
import i18n from "@/i18n";
import { ComposerDraftStore, clearStoredComposerDrafts } from "@/lib/composer-draft";
import { CLI_APPS_CHANGED_EVENT } from "@/lib/cli-app-events";
import type { CanonicalRunSnapshot, StreamError } from "@/lib/nanobot-client";
import { webuiThreadCache } from "@/lib/webui-thread-cache";
import { ThreadMessageCache } from "@/lib/thread-message-cache";
import { ThreadTranscript } from "@/lib/thread-transcript";
import { persistedCanonicalRunState } from "@/lib/canonical-run-snapshot";
import { ClientProvider } from "@/providers/ClientProvider";
import type {
  CliAppsPayload,
  ConnectionStatus,
  SettingsPayload,
  SubagentTaskSnapshot,
  ThreadProjectionEvent,
  UIMessage,
  WebuiThreadPersistedPayload,
} from "@/lib/types";
import { canonicalThreadPayload } from "./thread-test-payload";
import { createStreamClient } from "./stream-client";

const HERO_GREETING_PATTERN =
  /What should we work on\?|Where should we start\?|What are we building today\?|What should we tackle together\?/;

async function openMessageActions(text: string): Promise<HTMLElement> {
  const message = await screen.findByText(text);
  const block = message.closest<HTMLElement>("[data-thread-display-unit]")!;
  fireEvent.click(within(block).getByRole("button", { name: "Message actions" }));
  return screen.findByRole("dialog", { name: "Message actions" });
}

function makeClient() {
  const { client: lifecycle, receive } = createStreamClient();
  const errorHandlers = new Set<(err: StreamError) => void>();
  const statusHandlers = new Set<(status: ConnectionStatus) => void>();
  const runtimeModelHandlers = new Set<
    (modelName: string | null, modelPreset?: string | null) => void
  >();
  const sessionUpdateHandlers = new Set<(chatId: string, scope?: string) => void>();
  let status: ConnectionStatus = "open";
  const sendMessage = vi.fn(lifecycle.sendMessage.bind(lifecycle));
  const canReconcileCanonicalCompletion = vi.fn(lifecycle.canReconcileCanonicalCompletion.bind(lifecycle));
  const reconcileCanonicalCompletion = vi.fn((
    chatId: string,
    expectedRunGeneration: number,
    completedTurnIds: readonly string[],
    snapshot?: CanonicalRunSnapshot,
  ) => {
    if (!canReconcileCanonicalCompletion(
      chatId,
      expectedRunGeneration,
      completedTurnIds,
      snapshot,
    )) {
      return false;
    }
    return lifecycle.reconcileCanonicalCompletion(chatId, expectedRunGeneration, completedTurnIds, snapshot);
  });
  return {
    get status() {
      return status;
    },
    defaultChatId: null as string | null,
    onStatus: (handler: (nextStatus: ConnectionStatus) => void) => {
      statusHandlers.add(handler);
      handler(status);
      return () => {
        statusHandlers.delete(handler);
      };
    },
    onRunStatus: lifecycle.onRunStatus.bind(lifecycle),
    onRunCompletion: lifecycle.onRunCompletion.bind(lifecycle),
    onRuntimeModelUpdate: (
      handler: (modelName: string | null, modelPreset?: string | null) => void,
    ) => {
      runtimeModelHandlers.add(handler);
      return () => {
        runtimeModelHandlers.delete(handler);
      };
    },
    getRunState: lifecycle.getRunState.bind(lifecycle),
    restorePendingRun: lifecycle.restorePendingRun.bind(lifecycle),
    getRunStartedAt: lifecycle.getRunStartedAt.bind(lifecycle),
    getRunTurnId: lifecycle.getRunTurnId.bind(lifecycle),
    isRunCompleted: lifecycle.isRunCompleted.bind(lifecycle),
    finishRunLocally: vi.fn(lifecycle.finishRunLocally.bind(lifecycle)),
    hasUnsettledRun: lifecycle.hasUnsettledRun.bind(lifecycle),
    getRunGeneration: lifecycle.getRunGeneration.bind(lifecycle),
    canReconcileCanonicalCompletion,
    reconcileCanonicalCompletion,
    fenceCanonicalCompletedTurns: lifecycle.fenceCanonicalCompletedTurns.bind(lifecycle),
    getGoalState: lifecycle.getGoalState.bind(lifecycle),
    onTranscript: lifecycle.onTranscript.bind(lifecycle),
    onChat: lifecycle.onChat.bind(lifecycle),
    onError: (handler: (err: StreamError) => void) => {
      errorHandlers.add(handler);
      return () => {
        errorHandlers.delete(handler);
      };
    },
    onSessionUpdate: (handler: (chatId: string, scope?: string) => void) => {
      sessionUpdateHandlers.add(handler);
      return () => {
        sessionUpdateHandlers.delete(handler);
      };
    },
    _emitError(err: StreamError) {
      if (err.chatId && err.turnId) receive({
        event: "error", chat_id: err.chatId, turn_id: err.turnId, detail: err.kind,
      });
      for (const h of errorHandlers) h(err);
    },
    _emitStatus(nextStatus: ConnectionStatus) {
      status = nextStatus;
      for (const h of statusHandlers) h(status);
    },
    _emitChat(_chatId: string, ev: import("@/lib/types").InboundEvent) { receive(ev); },
    _emitRuntimeModelUpdate(modelName: string | null, modelPreset?: string | null) {
      for (const h of runtimeModelHandlers) h(modelName, modelPreset);
    },
    _emitSessionUpdate(chatId: string, scope?: string) {
      for (const h of sessionUpdateHandlers) h(chatId, scope);
    },
    sendMessage,
    sendSystemCommand: vi.fn().mockResolvedValue(undefined),
    newChat: vi.fn(),
    forkChat: vi.fn(),
    attach: vi.fn(),
    connect: vi.fn(),
    close: vi.fn(),
    updateUrl: vi.fn(),
  };
}

function wrap(
  client: ReturnType<typeof makeClient>,
  children: ReactNode,
  modelName?: string | null,
  token = "tok",
  webuiCapabilities: string[] = [],
) {
  return (
    <ClientProvider
      client={client as unknown as import("@/lib/nanobot-client").NanobotClient}
      token={token}
      modelName={modelName ?? null}
      webuiCapabilities={webuiCapabilities}
    >
      {children}
    </ClientProvider>
  );
}

function expectSendMessageWithTurn(
  client: ReturnType<typeof makeClient>,
  chatId: string,
  content: string,
  options: unknown = undefined,
) {
  expect(client.sendMessage).toHaveBeenCalledWith(
    chatId,
    content,
    options,
    expect.objectContaining({ turnId: expect.any(String) }),
  );
}

function session(chatId: string, modelPreset?: string | null) {
  return {
    key: `websocket:${chatId}`,
    channel: "websocket" as const,
    chatId,
    createdAt: null,
    updatedAt: null,
    preview: "",
    modelPreset,
  };
}

function transcriptFromSimpleMessages(
  rows: Array<{ id?: string; role: "user" | "assistant"; content: string; turnId?: string }>,
): WebuiThreadPersistedPayload {
  return canonicalThreadPayload({
    schemaVersion: 3,
    messages: rows.map((m, i) => ({
      id: m.id ?? `m-${i}`,
      role: m.role,
      content: m.content,
      ...(m.turnId ? { turnId: m.turnId } : {}),
      createdAt: 1000 + i,
    })),
  })!;
}

type StreamedFixtureRow =
  | ({
      role: "user";
      content: string;
      startsTurn?: boolean;
      activeTurnId?: string;
    } & (
      | { turnId: string; sessionMessage?: never }
      | { turnId?: never; sessionMessage: NonNullable<UIMessage["sessionMessage"]> }
    ))
  | {
      role: "assistant";
      content: string;
      turnId: string;
      streamId: string;
      textSeq?: number;
      endSeq?: number;
      mergeNext?: boolean;
    };

// Stream replacement requires the actual input and wire sources, not display IDs.
function streamedThreadPayload(
  chatId: string,
  rows: StreamedFixtureRow[],
  completedTurnIds: string[] = [],
): WebuiThreadPersistedPayload {
  const events: ThreadProjectionEvent[] = [];
  rows.forEach((row, index) => {
    if (row.role === "user") {
      events.push({
        event: "user_message", chat_id: chatId,
        projection_id: `input:${row.turnId ?? row.sessionMessage.message_id}`,
        text: row.content, starts_turn: row.startsTurn ?? true,
        ...(row.turnId ? { turn_id: row.turnId, turn_seq: 1 } : {}),
        ...(row.activeTurnId ? { active_turn_id: row.activeTurnId } : {}),
        ...(row.sessionMessage ? { provenance: { session_message: row.sessionMessage } } : {}),
      });
    } else {
      const textSeq = row.textSeq ?? 2;
      const endSeq = row.endSeq ?? 3;
      events.push({
        event: "stream_end", chat_id: chatId,
        projection_id: `answer:${row.turnId}:${row.streamId}:${endSeq}`,
        turn_id: row.turnId, turn_phase: "answer", turn_seq: endSeq,
        stream_id: row.streamId, text: row.content,
        projection_receipts: [{ turn_id: row.turnId, ranges: [[textSeq, endSeq]] }],
        ...(row.mergeNext ? { resuming: true, merge_next: true } : {}),
      });
    }
    if (row.turnId && completedTurnIds.includes(row.turnId)
      && !rows.slice(index + 1).some((later) => later.turnId === row.turnId)) {
      events.push({
        event: "turn_end", chat_id: chatId, turn_id: row.turnId,
        projection_id: `complete:${row.turnId}`,
        turn_seq: row.role === "assistant" ? (row.endSeq ?? 3) + 1 : 2,
      });
    }
  });
  return { schemaVersion: 3, projection: "events", events, completed_turn_ids: completedTurnIds };
}

function publishReconnectCompletion(
  client: ReturnType<typeof makeClient>,
  chatId: string,
  body: WebuiThreadPersistedPayload,
) {
  const generation = client.getRunGeneration(chatId);
  const { completedTurnIds, snapshot } = persistedCanonicalRunState(body);
  expect(client.canReconcileCanonicalCompletion(chatId, generation, completedTurnIds, snapshot)).toBe(true);
  // useReconnectRuns publishes synchronously before settling/fencing the ledger.
  webuiThreadCache.set(`websocket:${chatId}`, body);
  expect(client.reconcileCanonicalCompletion(chatId, generation, completedTurnIds, snapshot)).toBe(true);
}

function httpJson(body: unknown) {
  const normalized = body && typeof body === "object"
    && "schemaVersion" in body
    && "messages" in body
      ? canonicalThreadPayload(body as never)
      : body;
  return Response.json(normalized);
}

function traceDetailThread(
  deferred: boolean,
  answer: string,
  revision?: string,
): WebuiThreadPersistedPayload {
  return canonicalThreadPayload({
    schemaVersion: 3,
    ...(revision ? { revision } : {}),
    messages: [
      {
        id: "trace-shared",
        role: "tool",
        kind: "trace",
        content: deferred ? "exec(…)" : 'exec({"command":"echo full"})',
        traces: [deferred ? "exec(…)" : 'exec({"command":"echo full"})'],
        ...(deferred
          ? {
              traceDetail: {
                ref: "1.history-aaaaaaaaaaaaaaaaaaaa",
                bytes: 40_000,
                traceCount: 1,
              },
            }
          : {}),
        createdAt: 1_000,
      },
      {
        id: "answer-shared",
        role: "assistant",
        content: answer,
        createdAt: 2_000,
      },
    ],
  })!;
}

function setDocumentVisibility(value: DocumentVisibilityState): void {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    value,
  });
  document.dispatchEvent(new Event("visibilitychange"));
}

function restoreDocumentVisibility(
  descriptor: PropertyDescriptor | undefined,
): void {
  if (descriptor) {
    Object.defineProperty(document, "visibilityState", descriptor);
  } else {
    Reflect.deleteProperty(document, "visibilityState");
  }
}

interface ThreadResizeObserverInstance {
  elements: Element[];
  callback: ResizeObserverCallback;
}

function stubThreadResizeObserver() {
  const original = globalThis.ResizeObserver;
  const observers: ThreadResizeObserverInstance[] = [];
  class MockResizeObserver {
    elements: Element[] = [];
    callback: ResizeObserverCallback;

    constructor(callback: ResizeObserverCallback) {
      this.callback = callback;
      observers.push(this);
    }

    observe(element: Element) {
      this.elements.push(element);
    }

    disconnect() {}
  }
  vi.stubGlobal("ResizeObserver", MockResizeObserver);
  return {
    observers,
    restore: () => vi.stubGlobal("ResizeObserver", original),
  };
}

function modelSettings(model: string, provider: string): SettingsPayload {
  return {
    agent: {
      model,
      provider,
      resolved_provider: provider,
      has_api_key: true,
      model_preset: "default",
      max_tokens: 4096,
      context_window_tokens: 65536,
      temperature: 0.7,
      reasoning_effort: null,
      timezone: "UTC",
      tool_hint_max_length: 40,
    },
    model_presets: [{
      name: "default",
      label: "Default",
      active: true,
      is_default: true,
      model,
      provider,
      max_tokens: 4096,
      context_window_tokens: 65536,
      temperature: 0.7,
      reasoning_effort: null,
    }],
    model_call_order: [],
    model_call_order_editable: false,
    providers: [
      { name: "deepseek", label: "DeepSeek", configured: true },
      { name: "openai_codex", label: "OpenAI Codex", configured: true },
    ],
    web_search: {
      provider: "duckduckgo",
      api_key_hint: null,
      base_url: null,
      max_results: 5,
      timeout: 30,
      providers: [],
    },
    web: {
      enable: true,
      use_proxy: false,
      user_agent: null,
      search: { max_results: 5, timeout: 30 },
      fetch: { use_jina_reader: true },
    },
    image_generation: {
      enabled: false,
      provider: "openrouter",
      provider_configured: false,
      model: "openai/gpt-5.4-image-2",
      default_aspect_ratio: "1:1",
      default_image_size: "1K",
      max_images_per_turn: 4,
      save_dir: "generated",
      providers: [],
    },
    runtime: {
      config_path: "/tmp/config.json",
      workspace_path: "/tmp/workspace",
      gateway_host: "127.0.0.1",
      gateway_port: 18790,
      heartbeat: {
        enabled: true,
        interval_s: 1800,
      },
      dream: {
        schedule: "every 2h",
      },
      unified_session: false,
    },
    advanced: {
      restrict_to_workspace: false,
      webui_allow_local_service_access: true,
      webui_default_access_mode: "default",
      private_service_protection_enabled: true,
      ssrf_whitelist_count: 0,
      mcp_server_count: 0,
      exec_enabled: true,
      exec_sandbox: null,
      exec_path_prepend_set: false,
      exec_path_append_set: false,
    },
    requires_restart: false,
  };
}

function settingsWithFastPreset(): SettingsPayload {
  const settings = modelSettings("deepseek-v4-pro", "deepseek");
  settings.model_presets.push({
    ...settings.model_presets[0]!,
    name: "fast",
    label: "Fast",
    active: false,
    is_default: false,
    model: "openai-codex/gpt-5.5",
    provider: "openai_codex",
  });
  return settings;
}

describe("ThreadShell", () => {
  beforeEach(() => {
    webuiThreadCache.clear();
    clearStoredComposerDrafts();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        json: async () => ({}),
      }),
    );
  });

  it("publishes received and live body text to local search without search-driven reads", async () => {
    const client = makeClient();
    const cache = new ThreadMessageCache(() => false);
    const chatId = "loaded-search";
    const fetch = vi.fn(async (input: RequestInfo | URL) => String(input).includes("/webui-thread")
      ? httpJson(transcriptFromSimpleMessages([{ role: "assistant", content: "Seeded history" }]))
      : new Response(null, { status: 404 }));
    vi.stubGlobal("fetch", fetch);
    render(wrap(client, <>
      <ThreadShell session={session(chatId)} title="Loaded topic" messageCache={cache} onToggleSidebar={() => {}} />
      <SessionSearchDialog open sessions={[session(chatId)]} activeKey={null} loading={false}
        messageCache={cache} onOpenChange={() => {}} onSelect={() => {}} />
    </>));
    const dialog = await screen.findByRole("dialog", { name: "Search" });
    const input = within(dialog).getByRole("textbox", { name: "Search" });
    fireEvent.change(input, { target: { value: "seeded history" } });
    await within(dialog).findByText("Seeded history");
    const readsBeforeSearch = fetch.mock.calls.length;
    fireEvent.change(input, { target: { value: "fresh needle" } });
    expect(within(dialog).getByText("No matching topics.")).toBeInTheDocument();
    act(() => client._emitChat(chatId, { event: "message", chat_id: chatId, text: "Fresh needle from the live stream" }));
    await within(dialog).findByText("Fresh needle from the live stream");
    expect(fetch).toHaveBeenCalledTimes(readsBeforeSearch);
  });

  it.each(["callback", "cached return"] as const)("keeps closed answer segments in order after %s", async (path) => {
    const client = makeClient();
    const messageCache = new ThreadMessageCache(() => false);
    const chatId = "answer-order";
    const turnId = "answer-order-turn";
    const source = { provider: "fixture", model: "fixture", preset: "fixture" };
    const shell = (id: string, onTurnEnd = () => {}) => wrap(client, <ThreadShell
      session={session(id)} title="Answer order" messageCache={messageCache}
      onToggleSidebar={() => {}} onTurnEnd={onTurnEnd} />);
    const view = render(shell(chatId));
    act(() => {
      client._emitChat(chatId, { event: "goal_status", chat_id: chatId, turn_id: turnId, status: "running", started_at: 100 });
      client._emitChat(chatId, { event: "delta", chat_id: chatId, turn_id: turnId, stream_id: "first", turn_seq: 1, text: "Earlier answer" });
      client._emitChat(chatId, { event: "stream_end", chat_id: chatId, turn_id: turnId, stream_id: "first", turn_seq: 2, resuming: true, response_sources: [source] });
      client._emitChat(chatId, { event: "message", chat_id: chatId, turn_id: turnId, turn_seq: 3, kind: "tool_hint", text: "read_file(earlier)" });
      client._emitChat(chatId, { event: "delta", chat_id: chatId, turn_id: turnId, stream_id: "second", turn_seq: 4, text: "Later answer" });
      client._emitChat(chatId, { event: "stream_end", chat_id: chatId, turn_id: turnId, stream_id: "second", turn_seq: 5, resuming: true, response_sources: [source] });
      client._emitChat(chatId, { event: "message", chat_id: chatId, turn_id: turnId, turn_seq: 6, kind: "tool_hint", text: "read_file(later)" });
    });
    await screen.findByText("Later answer");
    if (path === "cached return") {
      view.rerender(shell("other-chat"));
      expect(screen.queryByText("Earlier answer")).not.toBeInTheDocument();
    }
    view.rerender(shell(chatId));
    await screen.findByText("Earlier answer");
    act(() => {
      client._emitChat(chatId, { event: "stream_end", chat_id: chatId, turn_id: turnId, stream_id: "empty-one", turn_seq: 7, resuming: true, response_sources: [source] });
      client._emitChat(chatId, { event: "stream_end", chat_id: chatId, turn_id: turnId, stream_id: "empty-two", turn_seq: 8, resuming: true, response_sources: [source] });
    });
    const earlier = screen.getByText("Earlier answer");
    const later = screen.getByText("Later answer");
    expect(earlier.compareDocumentPosition(later) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("button", { name: "Stop response" })).toBeInTheDocument();
  });

  it("keeps the dock and task events alive after the parent response finishes", async () => {
    const client = makeClient();
    const snapshot: SubagentTaskSnapshot = {
      task_id: "background-task", revision: 1, label: "Background inspection", task_description: "Inspect settings",
      origin_turn_id: "parent-turn", origin_message_id: null, created_at: 100, completed_at: null,
      state: "running", phase: "awaiting_model", elapsed_seconds: 2, iteration: 1, tool_events: [],
      usage: null, receipts: {}, result: null, partial: false, stop_reason: null, error: null,
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/subagents")) return httpJson({ tasks: [snapshot] });
      if (String(input).includes("/webui-thread")) return httpJson(transcriptFromSimpleMessages([
        { role: "user", content: "Delegate inspection", turnId: "parent-turn" },
      ]));
      return Response.json({}, { status: 404 });
    }));
    render(wrap(client, <ThreadShell session={session("background-work")} title="Background work" onToggleSidebar={() => {}} />,
      null, "tok", ["webui.core.v1", "webui.subagents.v1", "webui.subagents.events.v1"]));
    const trigger = await screen.findByTestId("subagent-task-dock-trigger");
    act(() => client._emitChat("background-work", { event: "goal_status", chat_id: "background-work", turn_id: "parent-turn", status: "running", started_at: 100 }));
    expect(screen.getByRole("button", { name: "Stop response" })).toBeVisible();
    act(() => client._emitChat("background-work", { event: "turn_end", chat_id: "background-work", turn_id: "parent-turn" }));
    expect(screen.queryByRole("button", { name: "Stop response" })).not.toBeInTheDocument();
    expect(trigger).toHaveTextContent("Running: 1");
    act(() => client._emitChat("background-work", { event: "user_message", chat_id: "background-work", turn_id: "next-turn", turn_seq: 1, starts_turn: true, text: "Continue with the next request" }));
    expect(trigger).toHaveTextContent("Running: 1");
    fireEvent.click(trigger);
    const list = screen.getByTestId("subagent-task-tree");
    expect(within(list).getByRole("button", { name: /Background inspection Running/ })).toBeVisible();
    act(() => client._emitChat("background-work", { event: "subagent_task", chat_id: "background-work", task: {
      ...snapshot, revision: 2, state: "done", completed_at: 103, result: "Inspection finished after the parent reply",
    } }));
    expect(trigger).toHaveTextContent("Completed: 1");
    expect(await within(list).findByText("Inspection finished after the parent reply")).toBeVisible();
    expect(list).toBeVisible();
  });

  it("renders one persisted task entry at the initiating prompt through the full shell", async () => {
    const client = makeClient();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/subagents")) return httpJson({ tasks: [{
        task_id: "completed-task", label: "Inspect settings", task_description: "Inspect settings",
        origin_turn_id: "delegation-turn", origin_message_id: null, created_at: 100, completed_at: 102,
        state: "done", phase: "done", elapsed_seconds: 2, iteration: 1, tool_events: [],
        usage: null, receipts: {}, result: "Verified", partial: false, stop_reason: "completed", error: null,
      }] });
      if (String(input).includes("/webui-thread")) return httpJson(transcriptFromSimpleMessages([
        { role: "user", content: "Delegate inspection", turnId: "delegation-turn" },
        { role: "assistant", content: "Parent conclusion", turnId: "delegation-turn" },
      ]));
      return { ok: false, status: 404, json: async () => ({}) };
    }));
    const shell = () => wrap(client, <ThreadShell session={session("persisted-tasks")} title="Task history"
      onToggleSidebar={() => {}} />, null, "tok", ["webui.core.v1", "webui.subagents.v1"]);
    const view = render(shell());
    await screen.findByText("Delegate inspection");
    fireEvent.click(await screen.findByRole("button", { name: /Subtasks Completed: 1/ }));
    const task = await screen.findByRole("button", { name: /Inspect settings Completed/ });
    expect(screen.queryByTestId("subagent-task-dock")).not.toBeInTheDocument();
    await screen.findByText("Delegate inspection");
    expect(screen.getAllByRole("button", { name: /Inspect settings/ })).toHaveLength(1);
    expect(screen.getByTestId("thread-message-region")).toContainElement(task);
    expect(within(screen.getByTestId("thread-composer-motion")).queryByText("Inspect settings")).not.toBeInTheDocument();
    view.unmount();
    render(shell());
    await screen.findByText("Delegate inspection");
    fireEvent.click(await screen.findByRole("button", { name: /Subtasks Completed: 1/ }));
    await screen.findByRole("button", { name: /Inspect settings Completed/ });
    expect(screen.queryByTestId("subagent-task-dock")).not.toBeInTheDocument();
    expect(client.sendMessage).not.toHaveBeenCalled();
  });

  it("restores the landing attachment draft in its created topic after a gateway rejection", async () => {
    const client = { ...makeClient(), sendAttachments: vi.fn().mockRejectedValue(new Error("file not found")) };
    const store = new ComposerDraftStore();
    store.set("new:chat", {
      text: "keep the first draft", sessionMentions: [], quotedContext: null,
      attachments: [{ path: "/project/video.mp4", name: "video.mp4", size: 8, mime: "video/mp4", kind: "video", url: "" }],
    });
    const onCreateChat = vi.fn().mockResolvedValue("created");
    const shell = (id: string | null) => wrap(client, <ThreadShell session={id ? session(id) : null}
      title="First attachment" draftStore={store} onToggleSidebar={() => {}} onCreateChat={onCreateChat} />);
    const view = render(shell(null));
    await screen.findByTestId("composer-chip");
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(onCreateChat).toHaveBeenCalledTimes(1));
    view.rerender(shell("created"));
    await waitFor(() => expect(screen.getByRole("textbox")).toHaveValue("keep the first draft"));
    expect(within(await screen.findByTestId("composer-chip")).getByRole("button", { name: "video.mp4" })).toBeVisible();
    expect(screen.getByRole("alert")).toHaveTextContent("file not found");
    expect(store.get("websocket:created")).toMatchObject({
      text: "keep the first draft",
      attachments: [{ path: "/project/video.mp4", name: "video.mp4", kind: "video" }],
    });
    expect(store.has("new:chat")).toBe(false);
    client.sendAttachments.mockResolvedValue(undefined);
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(screen.queryByTestId("composer-chip")).not.toBeInTheDocument());
    expect(screen.getByRole("textbox")).toHaveValue("");
    expect(client.sendAttachments).toHaveBeenCalledTimes(2);
  });

  it("clears the welcome draft after a delayed new-chat send and an unchanged round-trip", async () => {
    const client = makeClient();
    const store = new ComposerDraftStore();
    let completeCreate!: (id: string) => void;
    const onCreateChat = vi.fn(() => new Promise<string>((resolve) => { completeCreate = resolve; }));
    const shell = (id: string | null) => wrap(client,
      <ThreadShell session={id ? session(id) : null} title="Draft race" draftStore={store}
        onToggleSidebar={() => {}} onCreateChat={onCreateChat} />);
    const view = render(shell(null));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "original first message" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect(onCreateChat).toHaveBeenCalledTimes(1);
    view.rerender(shell("other"));
    view.rerender(shell(null));
    expect(screen.getByRole("textbox")).toHaveValue("original first message");
    await act(async () => {
      view.rerender(shell("created"));
      completeCreate("created");
    });
    await waitFor(() => expect(client.sendMessage).toHaveBeenCalledWith(
      "created", "original first message", undefined, expect.anything()));
    view.unmount();
    expect(new ComposerDraftStore().get("new:chat", true)).toBeUndefined();
  });

  it.each([false, true])("restores regular drafts after reload but excludes temporary chats (temporary=%s)", async (temporary) => {
    const client = makeClient();
    let draftStore = new ComposerDraftStore();
    draftStore.set("websocket:reload-draft", {
      text: "original", attachments: [], sessionMentions: [], quotedContext: "quoted answer",
    });
    const shell = () => wrap(client, (
      <ThreadShell session={session("reload-draft")} title="Reload test" temporary={temporary}
        draftStore={draftStore} onToggleSidebar={() => {}} />
    ));
    const first = render(shell());
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "  unsent draft\n第二行" } });
    first.unmount();
    draftStore = new ComposerDraftStore();
    const reloaded = render(shell());
    expect(screen.getByRole("textbox")).toHaveValue(temporary ? "" : "  unsent draft\n第二行");
    if (temporary) {
      expect(screen.queryByLabelText("Quoted context")).not.toBeInTheDocument();
    } else {
      expect(screen.getByLabelText("Quoted context")).toHaveTextContent("quoted answer");
      fireEvent.click(screen.getByRole("button", { name: "Send message" }));
      await waitFor(() => expect(client.sendMessage).toHaveBeenCalled());
      reloaded.unmount();
      draftStore = new ComposerDraftStore();
      render(shell());
      expect(screen.getByRole("textbox")).toHaveValue("");
      expect(screen.queryByLabelText("Quoted context")).not.toBeInTheDocument();
    }
    await act(async () => {});
    clearStoredComposerDrafts();
  });

  it.each([false, true])("persists only ordinary new-topic drafts (temporary=%s)", async (temporary) => {
    const client = makeClient();
    const shell = () => wrap(client, (
      <ThreadShell session={null} title="New topic" temporaryChatEnabled={temporary}
        draftStore={new ComposerDraftStore()} onToggleSidebar={() => {}} />
    ));
    const first = render(shell());
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "new topic draft" } });
    first.unmount();
    render(shell());
    expect(screen.getByRole("textbox")).toHaveValue(temporary ? "" : "new topic draft");
    await act(async () => {});
    clearStoredComposerDrafts();
  });

  it.each([false, true])("keeps text and quote drafts scoped to the session (temporary=%s)", async (temporary) => {
    const client = makeClient();
    const draftStore: ComposerDraftStore = new Map([
      ["websocket:draft-a", { text: "draft A", attachments: [], sessionMentions: [], quotedContext: "quote A" }],
      ["websocket:draft-b", { text: "draft B", attachments: [], sessionMentions: [], quotedContext: "quote B" }],
    ]);
    const shell = (chatId: string) => wrap(client, (
      <ThreadShell session={session(chatId)} title="Draft test" temporary={temporary}
        draftStore={draftStore} onToggleSidebar={() => {}} />
    ));
    const view = render(shell("draft-a"));
    expect(screen.getByRole("textbox")).toHaveValue("draft A");
    expect(screen.getByLabelText("Quoted context")).toHaveTextContent("quote A");
    fireEvent.click(screen.getByRole("button", { name: "Remove quote" }));
    view.rerender(shell("draft-b"));
    expect(screen.getByRole("textbox")).toHaveValue("draft B");
    expect(screen.getByLabelText("Quoted context")).toHaveTextContent("quote B");
    view.rerender(shell("draft-a"));
    expect(screen.getByRole("textbox")).toHaveValue("draft A");
    expect(screen.queryByLabelText("Quoted context")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(client.sendMessage).toHaveBeenCalled());
    view.rerender(shell("draft-b"));
    view.rerender(shell("draft-a"));
    expect(screen.getByRole("textbox")).toHaveValue("");
    expect(draftStore.has("websocket:draft-a")).toBe(false);
    await act(async () => {});
  });

  it("surfaces and retries a deferred trace-detail request failure", async () => {
    const client = makeClient();
    let detailCalls = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/webui-thread/trace-detail?")) {
        detailCalls += 1;
        if (detailCalls === 1) {
          return Promise.resolve({ ok: false, status: 500, json: async () => ({}) });
        }
        return Promise.resolve(httpJson({
          message_id: "history-aaaaaaaaaaaaaaaaaaaa",
          events: [{
            event: "message",
            chat_id: "trace-detail-retry",
            projection_id: "trace-deferred",
            kind: "progress",
            text: 'exec({"command":"echo full"})',
          }],
        }));
      }
      if (url.includes("websocket%3Atrace-detail-retry/webui-thread")) {
        return Promise.resolve(httpJson({
          schemaVersion: 3,
          messages: [
            {
              id: "trace-deferred",
              role: "tool",
              kind: "trace",
              content: "exec(…)",
              traces: ["exec(…)"],
              traceDetail: {
                ref: "1.history-aaaaaaaaaaaaaaaaaaaa",
                bytes: 40_000,
                traceCount: 1,
              },
              createdAt: 1_000,
            },
            { id: "answer", role: "assistant", content: "done", createdAt: 2_000 },
          ],
        }));
      }
      return Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(wrap(
      client,
      <ThreadShell
        session={session("trace-detail-retry")}
        title="Trace detail retry"
        onToggleSidebar={() => {}}
      />,
    ));

    const menu = await openMessageActions("done");
    const activity = within(menu).getByRole("button", { name: /Worked/ });
    fireEvent.click(activity);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Full activity details could not be loaded.",
    );
    expect(detailCalls).toBe(1);

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(detailCalls).toBe(2));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    await waitFor(() => expect(document.body).toHaveTextContent("echo full"));

    fireEvent.click(screen.getByRole("button", { name: /Collapse activity details/ }));
    const reopenedMenu = await openMessageActions("done");
    fireEvent.click(within(reopenedMenu).getByRole("button", { name: /Worked/ }));
    await act(async () => Promise.resolve());
    expect(detailCalls).toBe(2);
  });

  it("hydrates deferred activity in an independently paged navigation window", async () => {
    const client = makeClient();
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/prompts")) return Promise.resolve(httpJson({ prompts: [{
        id: "old-user", preview: "Old question", answerPreview: "old answer", createdAt: 1,
        cursor: "0", turnId: "old-turn",
      }] }));
      if (url.includes("/trace-detail?")) return Promise.resolve(httpJson({
        message_id: "history-aaaaaaaaaaaaaaaaaaaa", events: [{
          event: "message", chat_id: "trace-navigation", projection_id: "old-trace", kind: "progress",
          text: 'exec({"command":"echo historical"})',
        }],
      }));
      if (url.includes("after=0")) return Promise.resolve(httpJson({
        schemaVersion: 3, projection: "events", events: [
          { event: "user_message", chat_id: "trace-navigation", projection_id: "old-user", text: "Old question", starts_turn: true },
          { event: "message", chat_id: "trace-navigation", projection_id: "old-trace", kind: "progress", text: "exec(…)",
            trace_detail: { ref: "1.history-aaaaaaaaaaaaaaaaaaaa", bytes: 40_000, traceCount: 1 } },
          { event: "message", chat_id: "trace-navigation", projection_id: "old-answer", text: "old answer" },
        ], page: { user_message_offset: 0, has_more_before: false, has_more_after: true, after_cursor: "1" },
      }));
      if (url.includes("/webui-thread")) return Promise.resolve(httpJson({
        schemaVersion: 3, messages: [{ id: "latest-answer", role: "assistant", content: "latest answer", createdAt: 100 }],
      }));
      return Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
    }));
    render(wrap(client, <ThreadShell session={session("trace-navigation")} title="Trace navigation" onToggleSidebar={() => {}} />,
      null, "tok", ["webui.prompt-navigation.v1"]));
    await screen.findByText("latest answer");
    fireEvent.click(await screen.findByRole("button", { name: "Message navigation" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Jump to message: Old question" }));
    await screen.findByText("old answer");
    const menu = await openMessageActions("old answer");
    fireEvent.click(within(menu).getByRole("button", { name: /Worked/ }));
    await waitFor(() => expect(document.body).toHaveTextContent("echo historical"));
    fireEvent.click(screen.getByRole("button", { name: "Scroll to bottom" }));
    await screen.findByText("latest answer");
    expect(screen.queryByText("old answer")).not.toBeInTheDocument();
  });

  it("ignores a deferred trace-detail failure after switching sessions", async () => {
    const client = makeClient();
    const detailUrls: string[] = [];
    let rejectDetail!: (reason: Error) => void;
    const pendingDetail = new Promise<Response>((_resolve, reject) => {
      rejectDetail = reject;
    });
    const cachedB = traceDetailThread(false, "done-b", "rev-b");
    webuiThreadCache.set("websocket:trace-failure-b", cachedB);
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/webui-thread/trace-detail?")) {
        detailUrls.push(url);
        return pendingDetail;
      }
      if (url.includes("websocket%3Atrace-failure-a/webui-thread")) {
        return Promise.resolve(httpJson(traceDetailThread(true, "done-a")));
      }
      if (url.includes("websocket%3Atrace-failure-b/webui-thread")) {
        return Promise.resolve(httpJson(cachedB));
      }
      return Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
    }));

    const view = (chatId: string) => wrap(
      client,
      <ThreadShell
        session={session(chatId)}
        title={`Trace ${chatId}`}
        onToggleSidebar={() => {}}
      />,
    );
    const { rerender } = render(view("trace-failure-a"));
    fireEvent.click(within(await openMessageActions("done-a")).getByRole("button", { name: /Worked/ }));

    rerender(view("trace-failure-b"));
    await screen.findByText("done-b");
    await act(async () => rejectDetail(new Error("late failure")));

    expect(detailUrls).toHaveLength(1);
    expect(detailUrls[0]).toContain("websocket%3Atrace-failure-a");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("does not carry a visible trace-detail failure into a cached session", async () => {
    const client = makeClient();
    const detailUrls: string[] = [];
    const cachedB = traceDetailThread(false, "cached-b", "rev-visible-b");
    webuiThreadCache.set("websocket:visible-failure-b", cachedB);
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/webui-thread/trace-detail?")) {
        detailUrls.push(url);
        return Promise.resolve({ ok: false, status: 500, json: async () => ({}) });
      }
      if (url.includes("websocket%3Avisible-failure-a/webui-thread")) {
        return Promise.resolve(httpJson(traceDetailThread(true, "failed-a")));
      }
      if (url.includes("websocket%3Avisible-failure-b/webui-thread")) {
        return Promise.resolve(httpJson(cachedB));
      }
      return Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
    }));

    const view = (chatId: string) => wrap(
      client,
      <ThreadShell
        session={session(chatId)}
        title={`Trace ${chatId}`}
        onToggleSidebar={() => {}}
      />,
    );
    const { rerender } = render(view("visible-failure-a"));
    fireEvent.click(within(await openMessageActions("failed-a")).getByRole("button", { name: /Worked/ }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();

    rerender(view("visible-failure-b"));
    await screen.findByText("cached-b");

    expect(detailUrls).toHaveLength(1);
    expect(detailUrls[0]).toContain("websocket%3Avisible-failure-a");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("renders each logical round in a completed turn as its own usage bar", async () => {
    const client = makeClient();
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      if (String(input).includes("websocket%3Ausage-chart/webui-thread")) {
        return Promise.resolve(httpJson({
          schemaVersion: 3,
          messages: [
            {
              id: "assistant-1",
              role: "assistant",
              content: "First response",
              turnId: "turn-1",
              createdAt: 1_000,
              usage: {
                prompt_tokens: 18_000,
                completion_tokens: 280,
                cached_tokens: 12_000,
                request_count: 2,
              },
              roundUsages: [
                { prompt_tokens: 8_000, completion_tokens: 120, cached_tokens: 2_000 },
                { prompt_tokens: 10_000, completion_tokens: 160, cached_tokens: 10_000 },
              ],
            },
            {
              id: "assistant-2",
              role: "assistant",
              content: "Second response",
              turnId: "turn-2",
              createdAt: 2_000,
              contextWindowTokens: 65_536,
              usage: {
                prompt_tokens: 29_400,
                completion_tokens: 416,
                cached_tokens: 26_180,
                context_tokens: 14_700,
                request_count: 2,
              },
              roundUsages: [
                { prompt_tokens: 13_000, completion_tokens: 180, cached_tokens: 10_000 },
                { prompt_tokens: 16_400, completion_tokens: 236, cached_tokens: 16_180 },
              ],
            },
          ] satisfies UIMessage[],
        }));
      }
      return Promise.resolve({
        ok: false,
        status: 404,
        json: async () => ({}),
      });
    }));

    render(wrap(
      client,
      <ThreadShell
        session={session("usage-chart")}
        title="Usage chart"
        onToggleSidebar={() => {}}
        settingsSnapshot={modelSettings("openai-codex/gpt-5.5", "openai_codex")}
      />,
      "openai-codex/gpt-5.5",
    ));

    const trigger = await screen.findByTestId("composer-context-usage");
    fireEvent.click(trigger);
    expect(await screen.findAllByTestId("round-usage-bar")).toHaveLength(4);
    expect(screen.getByRole("img", {
      name: /input tokens 16,400.*KV cache hit rate 99%.*output tokens 236/i,
    })).toBeInTheDocument();
    expect(screen.getByTestId("composer-context-meter")).toBeInTheDocument();
    for (const phase of ["started", "failed"] as const) {
      act(() => client._emitChat("usage-chart", {
        event: "context_compaction", chat_id: "usage-chart", compaction_id: "failed", phase,
      }));
      expect(screen.getByTestId("composer-context-meter")).toBeInTheDocument();
    }
    act(() => client._emitChat("usage-chart", {
      event: "context_compaction", chat_id: "usage-chart",
      compaction_id: "success", phase: "succeeded",
    }));
    expect(trigger).toHaveAccessibleName("Open context usage");
    expect(screen.getAllByTestId("round-usage-bar")).toHaveLength(4);
  });

  it.each([false, true])("restores context after compaction only with newer usage (%s)", async (newReply) => {
    const client = makeClient();
    const messages: UIMessage[] = [
      {
        id: "old", role: "assistant", content: "Before compact", createdAt: 1_000,
        contextWindowTokens: 1_000_000, usage: { context_tokens: 170_000 },
        roundUsages: [{ prompt_tokens: 170_000 }],
      },
      {
        id: "compact", role: "assistant", kind: "compaction", content: "", createdAt: 2_000,
        compaction: { id: "compact", phase: "succeeded" },
      },
    ];
    if (newReply) messages.push({
      id: "new", role: "assistant", content: "After compact", createdAt: 3_000,
      contextWindowTokens: 1_000_000, usage: { context_tokens: 20_700 },
    });
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => Promise.resolve(
      String(input).includes("websocket%3Acompact-usage/webui-thread")
        ? httpJson({ schemaVersion: 3, messages })
        : { ok: false, status: 404, json: async () => ({}) },
    )));
    render(wrap(client, <ThreadShell
      session={session("compact-usage")} title="Compact usage" onToggleSidebar={() => {}}
      settingsSnapshot={modelSettings("test-model", "deepseek")}
    />));
    const trigger = await screen.findByTestId("composer-context-usage");
    if (newReply) {
      expect(trigger).toHaveAccessibleName("Context 2%. Open context usage");
    } else {
      expect(trigger).toHaveAccessibleName("Open context usage");
    }
  });

  it("moves the session handle into the pane only when the workbench is split", () => {
    const client = makeClient();
    const portal = document.createElement("div");
    document.body.append(portal);
    const activeSession = {
      ...session("pane-handle"),
      handle: {
        id: "handle_11111111111111111111111111111111",
        name: "soro",
      },
    };

    const { unmount } = render(wrap(
      client,
      <ThreadShell
        session={activeSession}
        title="Single pane"
        onToggleSidebar={() => {}}
        hideHeaderTitle
        headerPortalTarget={portal}
      />,
    ));

    expect(within(portal).queryByText("@soro")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Session @soro")).not.toBeInTheDocument();

    unmount();
    const splitView = render(wrap(
      client,
      <ThreadShell
        session={activeSession}
        title="Split pane"
        onToggleSidebar={() => {}}
        hideHeaderTitle
        inlineHandle
        headerPortalTarget={portal}
      />,
    ));

    expect(screen.getByLabelText("Session @soro")).toHaveTextContent("@soro");
    expect(within(portal).queryByText("@soro")).not.toBeInTheDocument();

    splitView.unmount();
    portal.remove();
  });

  it("keeps inferred file paths non-interactive when the availability probe fails", async () => {
    await preloadMarkdownText();
    const client = makeClient();
    let resolveProbe!: (value: Response) => void;
    const probe = new Promise<Response>((resolve) => {
      resolveProbe = resolve;
    });
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("websocket%3Apreview-error/webui-thread")) {
        return Promise.resolve(httpJson(transcriptFromSimpleMessages([
          { role: "assistant", content: "Unreadable file: `prompts/dream.md`" },
        ])));
      }
      if (url.includes("websocket%3Apreview-error/file-preview?")) return probe;
      return Promise.resolve({
        ok: false,
        status: 404,
        json: async () => ({}),
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(wrap(
      client,
      <ThreadShell
        session={session("preview-error")}
        title="Preview error"
        onToggleSidebar={() => {}}
      />,
    ));

    const reference = await screen.findByTestId("inline-file-path");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("file-preview?path=prompts%2Fdream.md&probe=1"),
      expect.anything(),
    ));
    await act(async () => {
      resolveProbe({
        ok: false,
        status: 500,
        text: async () => "failed to read file",
        json: async () => ({}),
      } as Response);
      await probe;
      await Promise.resolve();
    });

    expect(reference).not.toHaveAttribute("role");
    expect(reference).not.toHaveAttribute("tabindex");
    fireEvent.click(reference);
    expect(screen.queryByText("failed to read file")).not.toBeInTheDocument();
  });

  it("hides actions for a complete assistant-only message until turn_end", async () => {
    const client = makeClient();
    vi.mocked(fetch).mockImplementation(async (input) => (
      String(input).includes("websocket%3Aassistant-only-actions/webui-thread")
        ? httpJson(transcriptFromSimpleMessages([
            { role: "assistant", content: "old automation", turnId: "turn-old" },
          ]))
        : { ok: false, status: 404, json: async () => ({}) }
    ) as Response);

    render(wrap(
      client,
      <ThreadShell
        session={session("assistant-only-actions")}
        title="Assistant-only actions"
        onToggleSidebar={() => {}}
      />,
    ));

    const oldMenu = await openMessageActions("old automation");
    expect(within(oldMenu).getByRole("button", { name: "Copy" })).toBeInTheDocument();
    const turnId = "turn-automation";
    const startedAt = Date.now() / 1000;
    act(() => client._emitChat("assistant-only-actions", {
      event: "goal_status",
      chat_id: "assistant-only-actions",
      status: "running",
      started_at: startedAt,
      turn_id: turnId,
    }));
    expect(screen.getAllByRole("button", { name: "Message actions" })).toHaveLength(1);

    act(() => client._emitChat("assistant-only-actions", {
      event: "message",
      chat_id: "assistant-only-actions",
      text: "new automation",
      turn_id: turnId,
    }));
    await waitFor(() => expect(screen.getByText("new automation")).toBeInTheDocument());
    expect(screen.getAllByRole("button", { name: "Message actions" })).toHaveLength(1);
    expect(screen.getByText("new automation").closest("[data-thread-display-unit]"))
      .not.toHaveAttribute("data-message-context-block");

    act(() => client._emitChat("assistant-only-actions", {
      event: "turn_end",
      chat_id: "assistant-only-actions",
      turn_id: turnId,
    }));
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Message actions" })).toHaveLength(2));
    const newMenu = await openMessageActions("new automation");
    expect(within(newMenu).getByRole("button", { name: "Copy" })).toBeInTheDocument();
  });

  it("does not navigate away when clicking the chat title", async () => {
    const client = makeClient();
    render(wrap(
      client,
      <ThreadShell
        session={session("chat-title")}
        title="Important conversation"
        onToggleSidebar={() => {}}
      />,
    ));

    await waitFor(() => expect(screen.getByText("Important conversation")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Important conversation"));

    expect(screen.getByText("Important conversation")).toBeVisible();
  });

  it.each([true, false])("waits for parent settings and retries only on failure (success: %s)", async (success) => {
    const client = makeClient();
    const settings = modelSettings("deepseek-v4-pro", "deepseek");
    const settingsRequest = vi.fn(() => Promise.resolve(httpJson(settings)));
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => (
      String(input).endsWith("/api/settings")
        ? settingsRequest()
        : Promise.resolve(httpJson({}))
    )));
    const view = (loading: boolean, snapshot: SettingsPayload | null) => wrap(
      client,
      <ThreadShell session={null} title="New topic" onToggleSidebar={() => {}}
        settingsLoading={loading} settingsSnapshot={snapshot} />,
    );
    const { rerender } = render(view(true, null));
    await act(async () => {});
    expect(settingsRequest).not.toHaveBeenCalled();

    rerender(view(false, success ? settings : null));
    expect(await screen.findByTestId("composer-model-logo-deepseek")).toBeInTheDocument();
    expect(settingsRequest).toHaveBeenCalledTimes(success ? 0 : 1);
  });

  it("updates the composer model logo when settings snapshot changes", async () => {
    const client = makeClient();
    const { rerender } = render(
      wrap(
        client,
        <ThreadShell
          session={session("model-logo")}
          title="Model logo"
          onToggleSidebar={() => {}}
          settingsSnapshot={modelSettings("deepseek-v4-pro", "deepseek")}
        />,
        "deepseek-v4-pro",
      ),
    );

    expect(await screen.findByTestId("composer-model-logo-deepseek")).toBeInTheDocument();

    await act(async () => {
      rerender(
        wrap(
          client,
          <ThreadShell
            session={session("model-logo")}
            title="Model logo"
            onToggleSidebar={() => {}}
            settingsSnapshot={modelSettings("openai-codex/gpt-5.5", "openai_codex")}
          />,
          "openai-codex/gpt-5.5",
        ),
      );
    });

    expect(await screen.findByTestId("composer-model-logo-openai_codex")).toBeInTheDocument();
  });

  it("keeps the composer model name and provider on the same settings snapshot", async () => {
    const client = makeClient();
    render(
      wrap(
        client,
        <ThreadShell
          session={session("model-settings-sync")}
          title="Model settings sync"
          onToggleSidebar={() => {}}
          settingsSnapshot={modelSettings("openai-codex/gpt-5.5", "openai_codex")}
        />,
        "ling/ling-3.0-flash",
      ),
    );

    expect(await screen.findByTestId("composer-model-logo-openai_codex")).toBeInTheDocument();
    expect(screen.getByText("Default")).toBeInTheDocument();
    expect(screen.queryByText("ling-3.0-flash")).not.toBeInTheDocument();
  });

  it("resolves the composer model from the active session preset", async () => {
    const client = makeClient();
    render(
      wrap(
        client,
        <ThreadShell
          session={session("chat-fast", "fast")}
          title="Fast session"
          onToggleSidebar={() => {}}
          settingsSnapshot={settingsWithFastPreset()}
        />,
        "deepseek-v4-pro",
      ),
    );

    fireEvent.focus(await screen.findByLabelText("fast"));
    expect(await screen.findByRole("tooltip")).toHaveTextContent("fast gpt-5.5 OpenAI Codex");
    fireEvent.blur(screen.getByLabelText("fast"));
    expect(screen.queryByLabelText("Default")).not.toBeInTheDocument();
  });

  it("falls back to the current preset while a renamed session reference is stale", async () => {
    const client = makeClient();
    const settings = settingsWithFastPreset();
    settings.agent.model_preset = "fast";
    settings.model_presets = settings.model_presets.map((preset) => ({
      ...preset,
      active: preset.name === "fast",
    }));
    render(
      wrap(
        client,
        <ThreadShell
          session={session("renamed-preset", "old-fast")}
          title="Renamed preset"
          onToggleSidebar={() => {}}
          settingsSnapshot={settings}
        />,
        "openai-codex/gpt-5.5",
      ),
    );

    fireEvent.focus(await screen.findByLabelText("fast"));
    expect(await screen.findByRole("tooltip")).toHaveTextContent("fast gpt-5.5 OpenAI Codex");
    fireEvent.blur(screen.getByLabelText("fast"));
    expect(screen.queryByRole("button", { name: "Choose model" })).not.toBeInTheDocument();
  });

  it("switches through every named preset while preserving call-order priority", async () => {
    const client = makeClient();
    const settings = settingsWithFastPreset();
    settings.model_presets.push({
      ...settings.model_presets.at(-1)!,
      name: "extra",
      label: "Extra",
      model: "deepseek/extra",
      provider: "deepseek",
      active: false,
      is_default: false,
    });
    settings.model_call_order = ["fast"];

    const view = (preset: string) => wrap(client, (
      <ThreadShell
        session={session("preset-order", preset)}
        title="Preset order"
        onToggleSidebar={() => {}}
        settingsSnapshot={settings}
      />
    ));
    const { rerender } = render(view("default"));

    const badge = await screen.findByRole("button", { name: "Default" });
    expect(badge).toHaveTextContent("Default");
    fireEvent.click(badge);
    fireEvent.click(await screen.findByRole("option", { name: /^fast\b/i }));

    expect(client.sendSystemCommand).toHaveBeenCalledWith(
      "preset-order",
      "/model fast",
    );
    expect(await screen.findByLabelText("fast", { selector: "button" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "fast" }));
    fireEvent.click(await screen.findByRole("option", { name: /^extra\b/i }));
    expect(client.sendSystemCommand).toHaveBeenLastCalledWith(
      "preset-order",
      "/model extra",
    );
    expect(await screen.findByText("extra")).toBeInTheDocument();

    rerender(view("fast"));
    expect(await screen.findByLabelText("fast", { selector: "button" })).toBeInTheDocument();
  });

  it("uses the backend-resolved provider for an auto session preset", async () => {
    const client = makeClient();
    const settings = modelSettings("deepseek-v4-pro", "deepseek");
    settings.providers.push({
      name: "companyproxy",
      label: "Company Proxy",
      configured: true,
    });
    settings.model_presets.push({
      ...settings.model_presets[0]!,
      name: "fast",
      label: "Fast",
      active: false,
      is_default: false,
      model: "companyproxy/gpt-4",
      provider: "auto",
      resolved_provider: "companyproxy",
    });

    render(
      wrap(
        client,
        <ThreadShell
          session={session("chat-auto", "fast")}
          title="Auto provider session"
          onToggleSidebar={() => {}}
          settingsSnapshot={settings}
        />,
        "deepseek-v4-pro",
      ),
    );

    fireEvent.focus(await screen.findByLabelText("fast"));
    expect(await screen.findByRole("tooltip")).toHaveTextContent("fast gpt-4 Company Proxy");
    fireEvent.blur(screen.getByLabelText("fast"));
    expect(screen.queryByRole("button", { name: "Choose model" })).not.toBeInTheDocument();
  });

  it("keeps the selected composer preset and attributes only the reply to its actual source", async () => {
    const client = makeClient();
    render(wrap(
      client,
      <ThreadShell
        session={session("fallback-model")}
        title="Fallback model"
        onToggleSidebar={() => {}}
        settingsSnapshot={modelSettings("openai-codex/gpt-5.5", "openai_codex")}
      />,
      "openai-codex/gpt-5.5",
    ));

    expect(await screen.findByText("Default")).toBeInTheDocument();
    const configuredLogo = await screen.findByTestId("composer-model-logo-openai_codex");
    const configuredBadge = configuredLogo.parentElement;
    expect(configuredBadge).not.toBeNull();
    expect(configuredBadge).toHaveClass("composer-model-badge");
    expect(configuredBadge).not.toHaveAttribute("data-fallback");

    act(() => {
      client._emitChat("fallback-model", {
        event: "turn_model_updated",
        chat_id: "fallback-model",
        model_name: "openai-codex/gpt-5.5",
        model_preset: "Default",
      });
    });

    expect(configuredBadge).not.toHaveAttribute("data-fallback");
    expect(screen.getByText("Default")).toBeInTheDocument();

    act(() => {
      client._emitChat("fallback-model", {
        event: "turn_model_updated",
        chat_id: "fallback-model",
        model_name: "deepseek/deepseek-chat",
        fallback: true,
      });
    });

    expect(screen.getByTestId("composer-model-logo-openai_codex").parentElement).toBe(configuredBadge);
    expect(screen.getByText("Default")).toBeInTheDocument();
    expect(screen.queryByTestId("composer-model-logo-deepseek")).not.toBeInTheDocument();
    expect(configuredBadge).not.toHaveAttribute("data-fallback");
    fireEvent.focus(screen.getByLabelText("Default"));
    expect(await screen.findByRole("tooltip")).toHaveTextContent(
      "Default gpt-5.5 OpenAI Codex",
    );
    fireEvent.blur(screen.getByLabelText("Default"));

    act(() => {
      client._emitChat("fallback-model", {
        event: "message", chat_id: "fallback-model", text: "Reply from the actual provider",
        response_sources: [{provider: "deepseek", model: "deepseek-chat", preset: "backup", fallback: true}],
      });
      client._emitChat("fallback-model", {
        event: "turn_end",
        chat_id: "fallback-model",
      });
    });

    await waitFor(() => {
      expect(
        screen.getByTestId("composer-model-logo-openai_codex").parentElement,
      ).not.toHaveAttribute("data-fallback");
    });
    expect(screen.getByText("Default")).toBeInTheDocument();
    await openMessageActions("Reply from the actual provider");
    expect(await screen.findByText("backup")).toBeInTheDocument();
  });

  it("shows a dismissible, session-scoped fallback notice without changing the composer preset", async () => {
    const client = makeClient();
    const openSettings = vi.fn();
    const settings = modelSettings("openai-codex/gpt-5.5", "openai_codex");
    const tree = (chatId: string) => wrap(client, <ThreadShell
      session={session(chatId)} title="Fallback notice" onToggleSidebar={() => {}}
      settingsSnapshot={settings} onOpenModelSettings={openSettings}
    />);
    const view = render(tree("notice-a"));
    await screen.findByTestId("composer-model-logo-openai_codex");
    const emit = (chatId: string, fallback: boolean) => act(() => client._emitChat(chatId, {
      event: "turn_model_updated", chat_id: chatId,
      model_name: fallback ? "xai-grok/grok-4.5" : "openai-codex/gpt-5.5",
      fallback,
    }));
    const notice = () => screen.queryByText("This response used a fallback model: xai-grok/grok-4.5.");
    emit("notice-b", true);
    emit("notice-a", false);
    expect(notice()).not.toBeInTheDocument();
    emit("notice-a", true);
    const banner = notice()!.closest('[role="status"]') as HTMLElement;
    expect(banner).toBeVisible();
    expect(screen.getByTestId("composer-model-logo-openai_codex")).toBeInTheDocument();
    expect(banner.textContent).not.toMatch(/expired|sign in/i);
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "Keep my draft" } });
    fireEvent.click(within(banner).getByRole("button", { name: "Check model settings" }));
    expect(openSettings).toHaveBeenCalledTimes(1);
    fireEvent.click(within(banner).getByRole("button", { name: "Dismiss" }));
    expect(notice()).not.toBeInTheDocument();
    expect(input).toHaveValue("Keep my draft");
    expect(client.sendSystemCommand).not.toHaveBeenCalled();
    emit("notice-a", true);
    expect(notice()).not.toBeInTheDocument();
    // A new turn can notify again; it does not inherit the previous dismissal.
    emit("notice-a", false);
    emit("notice-a", true);
    expect(notice()).toBeVisible();
    view.rerender(tree("notice-b"));
    expect(notice()).not.toBeInTheDocument();
    emit("notice-a", true);
    expect(notice()).not.toBeInTheDocument();
    view.rerender(tree("notice-a"));
    await act(async () => {});
    expect(notice()).not.toBeInTheDocument();
  });

  it("prioritizes the rejected provider's login over fallback details", async () => {
    const client = makeClient();
    const openSettings = vi.fn();
    render(wrap(client, <ThreadShell session={session("reauth")}
      title="Auth notice" onToggleSidebar={() => {}} onOpenModelSettings={openSettings}
      settingsSnapshot={modelSettings("openai-codex/gpt-5.5", "openai_codex")} />));
    await screen.findByTestId("composer-model-logo-openai_codex");
    const emit = (reauth_provider?: string) => act(() => client._emitChat("reauth", {
      event: "turn_model_updated", chat_id: "reauth", model_name: "xai-grok/grok-4.5",
      fallback: true, reauth_provider,
    }));
    emit();
    const generic = screen.getByText(/This response used a fallback model/).closest('[role="status"]')!;
    fireEvent.click(within(generic as HTMLElement).getByRole("button", { name: "Dismiss" }));
    emit("openai_codex");
    const title = screen.getByText("OpenAI Codex authorization expired. Please sign in again.");
    expect(title).toBeVisible();
    expect(screen.getByText("A fallback model handled this response.")).toBeVisible();
    expect(screen.queryByText(/This response used a fallback model/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open model settings" }));
    expect(openSettings).toHaveBeenCalledOnce();
    fireEvent.click(within(title.closest('[role="status"]') as HTMLElement).getByRole("button", { name: "Dismiss" }));
    emit("openai_codex");
    emit();
    expect(screen.queryByText(/authorization expired/)).not.toBeInTheDocument();
    expect(screen.getByTestId("composer-model-logo-openai_codex")).toBeInTheDocument();
    expect(client.sendSystemCommand).not.toHaveBeenCalled();
  });

  it("does not show a live fallback notice just from replayed response attribution", async () => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => Promise.resolve(
      String(input).includes("/webui-thread") ? httpJson({
        schemaVersion: 3,
        messages: [{ id: "old-reply", role: "assistant", content: "Previous reply", createdAt: 1_000,
          responseSources: [{ provider: "xai", model: "grok-4.5", preset: "backup", fallback: true }] }],
      }) : { ok: false, status: 404, json: async () => ({}) },
    )));
    render(wrap(makeClient(), <ThreadShell session={session("old-fallback")} title="History"
      onToggleSidebar={() => {}} settingsSnapshot={modelSettings("gpt-5.5", "openai_codex")} />));
    expect(await screen.findByText("Previous reply")).toBeInTheDocument();
    expect(screen.queryByText(/This response used a fallback model/)).not.toBeInTheDocument();
  });

  it.each([false, true])("keeps model setup actionable without a repeated tooltip (existing history: %s)", async (hasHistory) => {
    const client = makeClient();
    const settings = modelSettings("anthropic/claude-opus-4-5", "anthropic");
    settings.agent.has_api_key = false;
    settings.providers = [{ name: "anthropic", label: "Anthropic", configured: false }];
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      if (String(input).includes("websocket%3Asetup-tooltip/webui-thread")) {
        return Promise.resolve(httpJson(transcriptFromSimpleMessages(
          hasHistory ? [{ role: "user", content: "Previous message" }] : [],
        )));
      }
      return Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
    }));
    const onOpenModelSettings = vi.fn();
    render(wrap(
      client,
      <ThreadShell
        session={session("setup-tooltip")}
        title="Setup tooltip"
        onToggleSidebar={() => {}}
        settingsSnapshot={settings}
        onOpenModelSettings={onOpenModelSettings}
      />,
      "anthropic/claude-opus-4-5",
    ));

    await screen.findByText(hasHistory ? "Previous message" : HERO_GREETING_PATTERN);
    const badge = screen.getByRole("button", { name: "Choose model" });
    fireEvent.focus(badge);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    fireEvent.click(badge);
    expect(onOpenModelSettings).toHaveBeenCalledTimes(1);
    expect(client.sendMessage).not.toHaveBeenCalled();
  });

  it("opens model settings directly without clearing the draft", async () => {
    const client = makeClient();
    const settings = modelSettings("openai-codex/gpt-5.1-codex", "openai_codex");
    settings.agent.has_api_key = false;
    settings.providers = settings.providers.map((provider) =>
      provider.name === "openai_codex"
        ? { ...provider, auth_type: "oauth", configured: false }
        : provider,
    );
    settings.providers.push(
      {
        name: "xai_grok",
        label: "xAI Grok",
        auth_type: "oauth",
        configured: true,
      },
      {
        name: "ollama",
        label: "Ollama",
        configured: true,
        api_base: "http://127.0.0.1:11434",
      },
    );
    const onOpenModelSettings = vi.fn();

    render(
      wrap(
        client,
        <ThreadShell
          session={session("unconfigured-model")}
          title="Unconfigured model"
          onToggleSidebar={() => {}}
          settingsSnapshot={settings}
          onOpenModelSettings={onOpenModelSettings}
        />,
        "openai-codex/gpt-5.1-codex",
      ),
    );

    const badge = await screen.findByRole("button", { name: "Choose model" });
    expect(screen.queryByTestId("composer-model-setup-icon")).not.toBeInTheDocument();
    expect(badge.querySelector('[data-needs-setup="true"]')).toHaveClass(
      "composer-model-pill-setup",
    );
    expect(screen.getByTestId("composer-model-setup-label")).toHaveTextContent("Choose model");
    expect(badge).not.toHaveClass("border-amber-500/35");
    expect(screen.queryByTestId("composer-model-logo-openai_codex")).not.toBeInTheDocument();

    const input = screen.getByRole("textbox", { name: "Message input" });
    fireEvent.change(input, {
      target: { value: "hello" },
    });
    fireEvent.click(badge);

    expect(screen.queryByRole("dialog", { name: "Choose model" })).not.toBeInTheDocument();
    expect(onOpenModelSettings).toHaveBeenCalledTimes(1);
    expect(input).toHaveValue("hello");
    expect(client.sendMessage).not.toHaveBeenCalled();

    onOpenModelSettings.mockClear();
    const firstSetupPill = badge.querySelector('[data-needs-setup="true"]');
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });

    const secondSetupPill = badge.querySelector('[data-needs-setup="true"]');
    expect(onOpenModelSettings).not.toHaveBeenCalled();
    expect(secondSetupPill).not.toBe(firstSetupPill);
    expect(secondSetupPill).toHaveClass("composer-model-pill-setup-attention");
    expect(input).toHaveValue("hello");
    expect(client.sendMessage).not.toHaveBeenCalled();

    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });
    expect(badge.querySelector('[data-needs-setup="true"]')).not.toBe(secondSetupPill);
  });

  it("keeps image generation controls out of the composer", async () => {
    const client = makeClient();
    const disabledSettings = modelSettings("deepseek-v4-pro", "deepseek");
    const enabledSettings: SettingsPayload = {
      ...disabledSettings,
      image_generation: {
        ...disabledSettings.image_generation,
        enabled: true,
        provider_configured: true,
      },
    };

    const { rerender } = render(
      wrap(
        client,
        <ThreadShell
          session={session("image-generation-disabled")}
          title="Image generation disabled"
          onToggleSidebar={() => {}}
          settingsSnapshot={disabledSettings}
        />,
        "deepseek-v4-pro",
      ),
    );

    await screen.findByLabelText("Message input");
    expect(screen.queryByRole("button", { name: "Image mode" })).not.toBeInTheDocument();

    await act(async () => {
      rerender(
        wrap(
          client,
          <ThreadShell
            session={session("image-generation-disabled")}
            title="Image generation disabled"
            onToggleSidebar={() => {}}
            settingsSnapshot={enabledSettings}
          />,
          "deepseek-v4-pro",
        ),
      );
    });

    expect(screen.queryByRole("button", { name: "Image mode" })).not.toBeInTheDocument();
  });

  it("restores in-memory messages when switching away and back to a session", async () => {
    const client = makeClient();

    const { rerender } = render(
      wrap(
        client,
        <ThreadShell
          session={session("chat-a")}
          title="Chat chat-a"
          onToggleSidebar={() => {}}
        />,
      ),
    );

    fireEvent.change(screen.getByLabelText("Message input"), {
      target: { value: "persist me across tabs" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() =>
      expectSendMessageWithTurn(client, "chat-a", "persist me across tabs"),
    );
    expect(screen.getByText("persist me across tabs")).toBeInTheDocument();

    await act(async () => {
      rerender(
        wrap(
          client,
          <ThreadShell
            session={session("chat-b")}
            title="Chat chat-b"
            onToggleSidebar={() => {}}
          />,
        ),
      );
    });

    await act(async () => {
      rerender(
        wrap(
          client,
          <ThreadShell
            session={session("chat-a")}
            title="Chat chat-a"
            onToggleSidebar={() => {}}
          />,
        ),
      );
    });

    expect(screen.getByText("persist me across tabs")).toBeInTheDocument();
  });

  it.each([false, true])("sends the merged pending message before history refresh resolves (pending tools=%s)", async (pendingTools) => {
    const client = makeClient();
    const chatId = "queued-live-completion";
    const owner = "queued-owner";
    const initialHistory = httpJson({
      ...transcriptFromSimpleMessages([{ role: "user", content: "Initial question", turnId: owner }]),
      has_pending_tool_calls: pendingTools,
      active_turn_id: owner,
      completed_turn_ids: [],
    });
    vi.mocked(fetch).mockImplementation(async (input) => (
      String(input).includes("/webui-thread") ? initialHistory.clone()
        : { ok: false, status: 404, json: async () => ({}) }
    ) as Response);
    render(wrap(client, <ThreadShell session={session(chatId)} title="Queued chat" onToggleSidebar={() => {}} />));
    await screen.findByText("Initial question");
    act(() => client._emitChat(chatId, {
      event: "goal_status", chat_id: chatId, turn_id: owner,
      status: "running", started_at: 1_000,
    }));
    const input = screen.getByLabelText("Message input");
    for (const text of ["first persisted follow-up", "second persisted follow-up"]) {
      fireEvent.change(input, { target: { value: text } });
      fireEvent.keyDown(input, { key: "Enter" });
    }
    let finishRefresh!: (response: Response) => void;
    const refresh = new Promise<Response>((resolve) => { finishRefresh = resolve; });
    let refreshStarted = false;
    vi.mocked(fetch).mockImplementation(async (input) => {
      if (String(input).includes("/webui-thread")) {
        refreshStarted = true;
        return refresh;
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    act(() => client._emitSessionUpdate(chatId, "thread"));
    await waitFor(() => expect(refreshStarted).toBe(true));
    try {
      act(() => client._emitChat(chatId, { event: "turn_end", chat_id: chatId, turn_id: owner }));
      await waitFor(() => expectSendMessageWithTurn(client, chatId, "first persisted follow-up\nsecond persisted follow-up"));
      expect(screen.queryByRole("group", { name: "Waiting to send" })).not.toBeInTheDocument();
      expect(client.sendMessage).toHaveBeenCalledTimes(1);
      const nextTurnId = client.sendMessage.mock.calls[0][3]!.turnId!;
      act(() => client._emitChat(chatId, {
        event: "goal_status", chat_id: chatId, turn_id: nextTurnId,
        status: "running", started_at: 2_000,
      }));
      expect(client.sendMessage).toHaveBeenCalledTimes(1);
      act(() => client._emitChat(chatId, { event: "turn_end", chat_id: chatId, turn_id: nextTurnId }));
      expect(client.sendMessage).toHaveBeenCalledTimes(1);
    } finally {
      await act(async () => { finishRefresh(initialHistory.clone()); });
    }
  });

  it("sends the complete temporary pending message once without persisted history", async () => {
    const client = makeClient();
    const chatId = "temporary-queued-follow-ups";
    render(wrap(client, <ThreadShell
      session={session(chatId)} title="Temporary chat" temporary
      temporaryChatIds={[chatId]} onToggleSidebar={() => {}}
    />));
    act(() => client._emitChat(chatId, {
      event: "goal_status", chat_id: chatId, turn_id: "temporary-owner",
      status: "running", started_at: 1_000,
    }));
    const input = screen.getByLabelText("Message input");
    for (const text of ["first temporary follow-up", "second temporary follow-up"]) {
      fireEvent.change(input, { target: { value: text } });
      fireEvent.keyDown(input, { key: "Enter" });
    }
    expect(client.sendMessage).not.toHaveBeenCalled();

    act(() => client._emitChat(chatId, {
      event: "turn_end", chat_id: chatId, turn_id: "temporary-owner",
    }));
    await waitFor(() => expectSendMessageWithTurn(client, chatId, "first temporary follow-up\nsecond temporary follow-up"));
    expect(client.sendMessage).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("group", { name: "Waiting to send" })).not.toBeInTheDocument();
    const nextTurnId = client.sendMessage.mock.calls[0][3]!.turnId!;
    act(() => client._emitChat(chatId, {
      event: "goal_status", chat_id: chatId, turn_id: nextTurnId,
      status: "running", started_at: 2_000,
    }));
    expect(client.sendMessage).toHaveBeenCalledTimes(1);

    act(() => client._emitChat(chatId, {
      event: "turn_end", chat_id: chatId, turn_id: nextTurnId,
    }));
    expect(client.sendMessage).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("group", { name: "Waiting to send" })).not.toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes("/webui-thread"))).toBe(false);
    expect(window.localStorage.getItem(`nanobot.webui.composerQueuedGuidance.v1:${chatId}`)).toBeNull();
  });

  it("keeps temporary messages across navigation and drops them after clear", async () => {
    const client = makeClient();
    const view = (
      chatId: string,
      temporary: boolean,
      temporaryChatIds: readonly string[],
    ) => wrap(
      client,
      <ThreadShell
        session={session(chatId)}
        title={temporary ? "Temporary chat" : "Regular chat"}
        temporary={temporary}
        temporaryChatIds={temporaryChatIds}
        onToggleSidebar={() => {}}
      />,
    );
    const retainedTemporaryChats = ["temporary-live"];
    const { rerender } = render(view("temporary-live", true, retainedTemporaryChats));

    fireEvent.change(screen.getByLabelText("Message input"), {
      target: { value: "keep this only in memory" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expectSendMessageWithTurn(
      client,
      "temporary-live",
      "keep this only in memory",
    ));

    rerender(view("regular", false, retainedTemporaryChats));
    await waitFor(() => {
      expect(screen.queryByText("keep this only in memory")).not.toBeInTheDocument();
    });
    rerender(view("temporary-live", true, retainedTemporaryChats));
    expect(screen.getByText("keep this only in memory")).toBeInTheDocument();

    rerender(view("temporary-cleared", true, ["temporary-cleared"]));
    await waitFor(() => {
      expect(screen.queryByText("keep this only in memory")).not.toBeInTheDocument();
    });
  });

  it("highlights sent skill references without skill metadata", async () => {
    const client = makeClient();
    render(wrap(
      client,
      <ThreadShell
        session={session("skill-reference")}
        title="Skill reference"
        onToggleSidebar={() => {}}
      />,
    ));

    fireEvent.change(screen.getByLabelText("Message input"), {
      target: { value: "Use $github for this" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() =>
      expectSendMessageWithTurn(client, "skill-reference", "Use $github for this"),
    );
    expect(screen.getByTestId("message-skill-reference-github"))
      .toHaveTextContent(/^\$github$/);
  });

  it("clears the old thread when the active session is removed", async () => {
    const client = makeClient();

    const { rerender } = render(
      wrap(
        client,
        <ThreadShell
          session={session("chat-a")}
          title="Chat chat-a"
          onToggleSidebar={() => {}}
        />,
      ),
    );

    fireEvent.change(screen.getByLabelText("Message input"), {
      target: { value: "delete me cleanly" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() =>
      expectSendMessageWithTurn(client, "chat-a", "delete me cleanly"),
    );
    expect(screen.getByText("delete me cleanly")).toBeInTheDocument();

    await act(async () => {
      rerender(
        wrap(
          client,
          <ThreadShell
            session={null}
            title="nanobot"
            onToggleSidebar={() => {}}
          />,
        ),
      );
    });

    await waitFor(() => {
      expect(screen.queryByText("delete me cleanly")).not.toBeInTheDocument();
    });
    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });

  it("creates a chat only when the blank landing sends a first message", async () => {
    const client = makeClient();
    const onCreateChat = vi.fn().mockResolvedValue("chat-new");

    render(
      wrap(
        client,
        <ThreadShell
          session={null}
          title="nanobot"
          onToggleSidebar={() => {}}
          onCreateChat={onCreateChat}
        />,
      ),
    );

    fireEvent.change(screen.getByLabelText("Message input"), {
      target: { value: "start for real" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => expect(onCreateChat).toHaveBeenCalledTimes(1));
    expect(onCreateChat).toHaveBeenCalledWith(null, "start for real", null);
  });

  it("applies the selected landing preset before sending the first prompt", async () => {
    const client = makeClient();
    const settings = settingsWithFastPreset();
    settings.model_call_order = ["fast"];
    let resolveModelCommand!: () => void;
    client.sendSystemCommand.mockImplementation(
      () => new Promise<void>((resolve) => {
        resolveModelCommand = resolve;
      }),
    );
    const onCreateChat = vi.fn().mockResolvedValue("chat-new");

    const view = (currentSession: ReturnType<typeof session> | null) => wrap(client, (
      <ThreadShell
        session={currentSession}
        title={currentSession ? "New chat" : "nanobot"}
        onToggleSidebar={() => {}}
        onCreateChat={onCreateChat}
        settingsSnapshot={settings}
      />
    ));
    const { rerender } = render(view(null));

    fireEvent.click(await screen.findByRole("button", { name: "Default" }));
    fireEvent.click(await screen.findByRole("option", { name: /^fast\b/i }));
    expect(await within(screen.getByTestId("thread-welcome-layout")).findByText("fast")).toBeInTheDocument();
    expect(client.sendSystemCommand).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Message input"), {
      target: { value: "use the selected model" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => expect(client.sendSystemCommand).toHaveBeenCalledWith(
      "chat-new",
      "/model fast",
    ));
    expect(onCreateChat).toHaveBeenCalledWith(null, "use the selected model", "fast");

    await act(async () => {
      rerender(view(session("chat-new", "fast")));
    });
    fireEvent.focus(await screen.findByLabelText("fast"));
    expect(await screen.findByRole("tooltip")).toHaveTextContent("fast gpt-5.5 OpenAI Codex");
    fireEvent.blur(screen.getByLabelText("fast"));
    expect(screen.queryByText("Default")).not.toBeInTheDocument();
    expect(client.sendMessage).not.toHaveBeenCalled();

    await act(async () => {
      resolveModelCommand();
    });
    await waitFor(() => {
      expectSendMessageWithTurn(client, "chat-new", "use the selected model");
    });
  });

  it("binds a pending landing message to the chat created for it", async () => {
    const client = makeClient();
    let resolveCreate: ((chatId: string) => void) | null = null;
    const onCreateChat = vi.fn(() => new Promise<string>((resolve) => {
      resolveCreate = resolve;
    }));

    const { rerender } = render(
      wrap(
        client,
        <ThreadShell
          session={null}
          title="nanobot"
          onToggleSidebar={() => {}}
          onCreateChat={onCreateChat}
        />,
      ),
    );

    fireEvent.change(screen.getByLabelText("Message input"), {
      target: { value: "must not leak" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => expect(onCreateChat).toHaveBeenCalledTimes(1));

    await act(async () => {
      rerender(
        wrap(
          client,
          <ThreadShell
            session={session("existing-chat")}
            title="Existing chat"
            onToggleSidebar={() => {}}
            onCreateChat={onCreateChat}
          />,
        ),
      );
    });

    await act(async () => {
      resolveCreate?.("chat-new");
    });

    expect(client.sendMessage).not.toHaveBeenCalled();

    await act(async () => {
      rerender(
        wrap(
          client,
          <ThreadShell
            session={session("chat-new")}
            title="New chat"
            onToggleSidebar={() => {}}
            onCreateChat={onCreateChat}
          />,
        ),
      );
    });

    await waitFor(() =>
      expectSendMessageWithTurn(client, "chat-new", "must not leak"),
    );
  });

  it("consumes an automation-page first message through the normal thread stream", async () => {
    const client = makeClient();
    const consumed = vi.fn();
    const pendingFirstMessage = {
      id: "automation-first-message",
      chatId: "chat-new",
      content: "Every weekday at 9, summarize open pull requests",
      options: { intent: "create_automation" as const },
    };

    render(
      wrap(
        client,
        <StrictMode>
          <ThreadShell
            session={session("chat-new")}
            title="New automation chat"
            onToggleSidebar={() => {}}
            pendingFirstMessage={pendingFirstMessage}
            onPendingFirstMessageConsumed={consumed}
          />
        </StrictMode>,
      ),
    );

    await waitFor(() => expectSendMessageWithTurn(
      client,
      "chat-new",
      pendingFirstMessage.content,
    ));
    expect(client.sendMessage).toHaveBeenCalledTimes(1);
    expect(consumed).toHaveBeenCalledOnce();
    expect(consumed).toHaveBeenCalledWith(pendingFirstMessage.id);
    expect(client.sendMessage).toHaveBeenCalledWith(
      "chat-new",
      pendingFirstMessage.content,
      undefined,
      expect.objectContaining({ intent: "create_automation" }),
    );
  });

  it("keeps the first landing message when new chat history is still empty", async () => {
    const client = makeClient();
    const onCreateChat = vi.fn().mockResolvedValue("chat-new");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: false,
        status: 404,
        json: async () => ({}),
      })),
    );

    const { rerender } = render(
      wrap(
        client,
        <ThreadShell
          session={null}
          title="nanobot"
          onToggleSidebar={() => {}}
          onCreateChat={onCreateChat}
        />,
      ),
    );

    fireEvent.change(screen.getByLabelText("Message input"), {
      target: { value: "first message should stay" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => expect(onCreateChat).toHaveBeenCalledTimes(1));

    await act(async () => {
      rerender(
        wrap(
          client,
          <ThreadShell
            session={session("chat-new")}
            title="Chat chat-new"
            onToggleSidebar={() => {}}
            onCreateChat={onCreateChat}
          />,
        ),
      );
    });

    await waitFor(() =>
      expectSendMessageWithTurn(client, "chat-new", "first message should stay"),
    );
    await waitFor(() =>
      expect(screen.getByText("first message should stay")).toBeInTheDocument(),
    );
    expect(screen.queryByText(HERO_GREETING_PATTERN)).not.toBeInTheDocument();
  });

  it("hides a live first /model turn when the initial history snapshot is stale", async () => {
    const client = makeClient();
    const onCreateChat = vi.fn().mockResolvedValue("chat-new");
    let resolveThread:
      | ((value: { ok: boolean; status: number; json: () => Promise<unknown> }) => void)
      | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("websocket%3Achat-new/webui-thread")) {
          return new Promise((resolve) => {
            resolveThread = resolve;
          });
        }
        return Promise.resolve({
          ok: false,
          status: 404,
          json: async () => ({}),
        });
      }),
    );

    const { rerender } = render(
      wrap(
        client,
        <ThreadShell
          session={null}
          title="nanobot"
          onToggleSidebar={() => {}}
          onCreateChat={onCreateChat}
        />,
      ),
    );

    fireEvent.change(screen.getByLabelText("Message input"), {
      target: { value: "/model" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => expect(onCreateChat).toHaveBeenCalledTimes(1));

    await act(async () => {
      rerender(
        wrap(
          client,
          <ThreadShell
            session={session("chat-new")}
            title="Chat chat-new"
            onToggleSidebar={() => {}}
            onCreateChat={onCreateChat}
          />,
        ),
      );
    });

    await waitFor(() =>
      expectSendMessageWithTurn(client, "chat-new", "/model"),
    );

    await act(async () => {
      client._emitChat("chat-new", {
        event: "message",
        chat_id: "chat-new",
        text: "## Model\n- Current model: `Ring-2.6-1T`",
      });
      client._emitChat("chat-new", {
        event: "message",
        chat_id: "chat-new",
        text: "This unrelated reply stays visible.",
      });
    });
    expect(screen.queryByText("/model")).not.toBeInTheDocument();
    expect(screen.queryByText(/Current model/)).not.toBeInTheDocument();
    expect(screen.getByText("This unrelated reply stays visible.")).toBeInTheDocument();

    await act(async () => {
      resolveThread?.(
        httpJson(transcriptFromSimpleMessages([{ role: "user", content: "/model" }])),
      );
    });

    await waitFor(() => {
      expect(screen.queryByText("/model")).not.toBeInTheDocument();
      expect(screen.queryByText(/Current model/)).not.toBeInTheDocument();
      expect(screen.getByText("This unrelated reply stays visible.")).toBeInTheDocument();
    });
  });

  it("keeps the empty thread landing focused on the composer", async () => {
    const client = makeClient();
    render(
      wrap(
        client,
        <ThreadShell
          session={null}
          title="nanobot"
          onToggleSidebar={() => {}}
        />,
      ),
    );
    await act(async () => {});

    const greeting = screen.getByRole("heading", { level: 1, name: HERO_GREETING_PATTERN });
    expect(greeting).toHaveAttribute("data-testid", "hero-greeting");
    expect(greeting).toHaveClass("select-none", "whitespace-nowrap");
    expect(screen.getByRole("textbox")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Write code" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Make a plan" })).not.toBeInTheDocument();
  });

  it("does not leak the previous thread when opening a brand-new chat", async () => {
    const client = makeClient();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("websocket%3Achat-a/webui-thread")) {
          return httpJson(
            transcriptFromSimpleMessages([
              { role: "user", content: "old question" },
              { role: "assistant", content: "old answer" },
            ]),
          );
        }
        return {
          ok: false,
          status: 404,
          json: async () => ({}),
        };
      }),
    );

    const { rerender } = render(
      wrap(
        client,
        <ThreadShell
          session={session("chat-a")}
          title="Chat chat-a"
          onToggleSidebar={() => {}}
        />,
      ),
    );

    await waitFor(() => expect(screen.getByText("old answer")).toBeInTheDocument());

    await act(async () => {
      rerender(
        wrap(
          client,
          <ThreadShell
            session={session("chat-new")}
            title="Chat chat-new"
            onToggleSidebar={() => {}}
          />,
        ),
      );
    });

    expect(screen.queryByText("old answer")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("textbox")).toBeInTheDocument(),
    );
    const input = screen.getByRole("textbox");
    expect(input).toHaveAttribute("placeholder", "Describe what you’d like to do");
    expect(input.className).toContain("min-h-[78px]");
    expect(screen.queryByText("old answer")).not.toBeInTheDocument();
  });

  it("forks assistant replies using the global user message index rather than the visible window index", async () => {
    const client = makeClient();
    const onForkChat = vi.fn().mockResolvedValue("chat-fork");
    const rows = [
      { role: "user" as const, content: "question 100" },
      { role: "assistant" as const, content: "answer 100" },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("websocket%3Along-chat/webui-thread")) {
          return httpJson({
            ...transcriptFromSimpleMessages(rows),
            page: {
              before_cursor: "before-question-100",
              has_more_before: true,
              loaded_message_count: 2,
              user_message_offset: 100,
            },
          });
        }
        return {
          ok: false,
          status: 404,
          json: async () => ({}),
        };
      }),
    );

    render(
      wrap(
        client,
        <ThreadShell
          session={session("long-chat")}
          title="Long chat"
          onToggleSidebar={() => {}}
          onForkChat={onForkChat}
        />,
      ),
    );

    const menu = await openMessageActions("answer 100");
    fireEvent.click(within(menu).getByRole("button", { name: "New chat from here" }));

    await waitFor(() =>
      expect(onForkChat).toHaveBeenCalledWith("long-chat", 101),
    );
  });

  it("does not cache optimistic messages under the next chat during a session switch", async () => {
    const client = makeClient();

    const { rerender } = render(
      wrap(
        client,
        <ThreadShell
          session={session("chat-a")}
          title="Chat chat-a"
          onToggleSidebar={() => {}}
        />,
      ),
    );

    fireEvent.change(screen.getByLabelText("Message input"), {
      target: { value: "only in chat a" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() =>
      expectSendMessageWithTurn(client, "chat-a", "only in chat a"),
    );
    expect(screen.getByText("only in chat a")).toBeInTheDocument();

    await act(async () => {
      rerender(
        wrap(
          client,
          <ThreadShell
            session={session("chat-b")}
            title="Chat chat-b"
            onToggleSidebar={() => {}}
          />,
        ),
      );
    });

    await waitFor(() => {
      expect(screen.queryByText("only in chat a")).not.toBeInTheDocument();
    });

    await act(async () => {
      rerender(
        wrap(
          client,
          <ThreadShell
            session={session("chat-a")}
            title="Chat chat-a"
            onToggleSidebar={() => {}}
          />,
        ),
      );
    });

    expect(screen.getByText("only in chat a")).toBeInTheDocument();

    await act(async () => {
      rerender(
        wrap(
          client,
          <ThreadShell
            session={session("chat-b")}
            title="Chat chat-b"
            onToggleSidebar={() => {}}
          />,
        ),
      );
    });

    await waitFor(() => {
      expect(screen.queryByText("only in chat a")).not.toBeInTheDocument();
    });
  });

  it("keeps live assistant replies after visiting the blank new-chat page", async () => {
    const client = makeClient();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("websocket%3Achat-a/webui-thread")) {
          return httpJson(transcriptFromSimpleMessages([{ role: "user", content: "hello" }]));
        }
        return {
          ok: false,
          status: 404,
          json: async () => ({}),
        };
      }),
    );

    const { rerender } = render(
      wrap(
        client,
        <ThreadShell
          session={session("chat-a")}
          title="Chat chat-a"
          onToggleSidebar={() => {}}
        />,
      ),
    );

    await waitFor(() => expect(screen.getByText("hello")).toBeInTheDocument());
    await act(async () => {
      client._emitChat("chat-a", {
        event: "message",
        chat_id: "chat-a",
        text: "live assistant reply",
      });
    });
    expect(screen.getByText("live assistant reply")).toBeInTheDocument();

    await act(async () => {
      rerender(
        wrap(
          client,
          <ThreadShell
            session={null}
            title="nanobot"
            onToggleSidebar={() => {}}
          />,
        ),
      );
    });

    expect(screen.queryByText("live assistant reply")).not.toBeInTheDocument();
    expect(screen.getByText(HERO_GREETING_PATTERN)).toBeInTheDocument();

    await act(async () => {
      rerender(
        wrap(
          client,
          <ThreadShell
            session={session("chat-a")}
            title="Chat chat-a"
            onToggleSidebar={() => {}}
          />,
        ),
      );
    });

    await waitFor(() => expect(screen.getByText("live assistant reply")).toBeInTheDocument());
  });

  it("restores the stop control when returning to a running chat", async () => {
    const client = makeClient();
    const view = (chatId: string) => wrap(
      client,
      <ThreadShell
        session={session(chatId)}
        title={`Chat ${chatId}`}
        onToggleSidebar={() => {}}
      />,
    );
    const { rerender } = render(view("chat-a"));

    await act(async () => {
      client._emitChat("chat-a", {
        event: "goal_status",
        chat_id: "chat-a", turn_id: "running-chat-a-turn",
        status: "running",
        started_at: Date.now() / 1000,
      });
    });
    expect(screen.getByRole("button", { name: "Stop response" })).toBeInTheDocument();

    await act(async () => {
      rerender(view("chat-b"));
    });
    expect(screen.queryByRole("button", { name: "Stop response" })).not.toBeInTheDocument();

    await act(async () => {
      rerender(view("chat-a"));
    });
    expect(screen.getByRole("button", { name: "Stop response" })).toBeInTheDocument();
  });

  it("keeps live fork replies when a canonical refresh is missing an earlier assistant answer", async () => {
    const client = makeClient();
    let historyCalls = 0;
    let secondTurnId = "";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("websocket%3Achat-fork/webui-thread")) {
          historyCalls += 1;
          return httpJson(
            streamedThreadPayload("chat-fork",
              historyCalls === 1
                ? [{ role: "user", content: "first fork question", turnId: "first-fork-turn" }]
                : [
                    { role: "user", content: "first fork question", turnId: "first-fork-turn" },
                    { role: "user", content: "second fork question", turnId: secondTurnId },
                  ],
            ),
          );
        }
        return {
          ok: false,
          status: 404,
          json: async () => ({}),
        };
      }),
    );

    render(
      wrap(
        client,
        <ThreadShell
          session={session("chat-fork")}
          title="Chat chat-fork"
          onToggleSidebar={() => {}}
        />,
      ),
    );

    await waitFor(() => expect(screen.getByText("first fork question")).toBeInTheDocument());
    await act(async () => {
      client._emitChat("chat-fork", {
        event: "message",
        chat_id: "chat-fork",
        text: "first fork answer", turn_id: "first-fork-turn", turn_seq: 2,
      });
    });
    expect(screen.getByText("first fork answer")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Message input"), {
      target: { value: "second fork question" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() =>
      expectSendMessageWithTurn(client, "chat-fork", "second fork question"),
    );
    secondTurnId = client.sendMessage.mock.calls[0]?.[3]?.turnId ?? "";
    expect(secondTurnId).not.toBe("");
    expect(screen.getByText("second fork question")).toBeInTheDocument();

    await act(async () => {
      client._emitSessionUpdate("chat-fork");
    });

    await waitFor(() => expect(historyCalls).toBe(2));
    const firstQuestion = screen.getByText("first fork question");
    const firstAnswer = screen.getByText("first fork answer");
    const secondQuestion = screen.getByText("second fork question");
    expect(firstQuestion.compareDocumentPosition(firstAnswer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(firstAnswer.compareDocumentPosition(secondQuestion) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("recovers a truncated streamed answer after reconnecting", async () => {
    const client = makeClient();
    const turnId = "resume-turn";
    const streamId = "resume-answer";
    let historyCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("websocket%3Aresume-chat/webui-thread")) {
          historyCalls += 1;
          return httpJson({
            ...streamedThreadPayload("resume-chat",
              historyCalls === 1
                ? [{ role: "user", content: "question", turnId }]
                : [
                    { role: "user", content: "question", turnId },
                    { role: "assistant", content: "partial answer completed while away", turnId, streamId },
                  ],
              historyCalls === 1 ? [] : [turnId],
            ),
            has_pending_tool_calls: historyCalls === 1,
          });
        }
        return {
          ok: false,
          status: 404,
          json: async () => ({}),
        };
      }),
    );

    render(
      wrap(
        client,
        <ThreadShell
          session={session("resume-chat")}
          title="Resume chat"
          onToggleSidebar={() => {}}
        />,
      ),
    );

    await waitFor(() => expect(screen.getByText("question")).toBeInTheDocument());
    act(() => {
      client._emitChat("resume-chat", {
        event: "goal_status",
        chat_id: "resume-chat", turn_id: turnId,
        status: "running",
        started_at: 1_700,
      });
      client._emitChat("resume-chat", {
        event: "delta",
        chat_id: "resume-chat", turn_id: turnId, turn_seq: 2, stream_id: streamId,
        text: "partial answer",
      });
    });
    await waitFor(() => expect(screen.getByText("partial answer")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Stop response" })).toBeInTheDocument();
    expect(historyCalls).toBe(1);

    act(() => client._emitStatus("reconnecting"));
    expect(screen.getByRole("button", { name: "Stop response" })).toBeInTheDocument();
    act(() => client._emitStatus("open"));

    await waitFor(() => expect(historyCalls).toBe(2));
    await waitFor(() =>
      expect(screen.getByText("partial answer completed while away")).toBeInTheDocument(),
    );
    expect(screen.queryByText("partial answer")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Stop response" })).not.toBeInTheDocument();
  });

  it("adopts a completed canonical cache when reconnect revalidation returns 304", async () => {
    const client = makeClient();
    const chatId = "reconnect-not-modified";
    const turnId = "turn-cached-completion";
    let historyCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (!String(input).includes(`websocket%3A${chatId}/webui-thread`)) {
        return { ok: false, status: 404, json: async () => ({}) };
      }
      historyCalls += 1;
      if (historyCalls > 1) return { ok: false, status: 304 };
      return httpJson({
        ...streamedThreadPayload(chatId, [{ role: "user", content: "question", turnId }]),
        has_pending_tool_calls: true,
      });
    }));
    render(wrap(client, <ThreadShell
      session={session(chatId)} title="Cached completion"
      onToggleSidebar={() => {}}
    />));
    await screen.findByText("question");
    act(() => {
      client._emitChat(chatId, {
        event: "goal_status", chat_id: chatId, turn_id: turnId,
        status: "running", started_at: 1_700,
      });
      client._emitChat(chatId, {
        event: "delta", chat_id: chatId, turn_id: turnId, turn_seq: 2,
        stream_id: "cached-answer", text: "cached prefix",
      });
    });
    await screen.findByText("cached prefix");
    act(() => client._emitStatus("reconnecting"));
    // The reconnect coordinator can cache this response before the mounted
    // thread's conditional request returns the same body through HTTP 304.
    act(() => publishReconnectCompletion(client, chatId, {
      ...streamedThreadPayload(chatId, [
        { role: "user", content: "question", turnId },
        { role: "assistant", content: "full cached answer", turnId, streamId: "cached-answer" },
      ], [turnId]),
      revision: "completed-revision",
      has_pending_tool_calls: false,
    }));
    expect(client.reconcileCanonicalCompletion).toHaveBeenCalledTimes(1);
    act(() => client._emitStatus("open"));
    await screen.findByText("full cached answer");
    expect(historyCalls).toBe(2);
    expect(screen.queryByText("cached prefix")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Stop response" })).not.toBeInTheDocument();
  });

  it("shows externally published completion before an older mounted reconnect read returns", async () => {
    const client = makeClient();
    const chatId = "published-completion-race";
    const turnId = "published-completed-turn";
    let historyCalls = 0;
    let finishOlderRead!: (response: ReturnType<typeof httpJson>) => void;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      if (!String(input).includes(`websocket%3A${chatId}/webui-thread`)) {
        return Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
      }
      historyCalls += 1;
      if (historyCalls === 1) return Promise.resolve(httpJson({
        ...streamedThreadPayload(chatId, [{ role: "user", content: "question", turnId }]),
        has_pending_tool_calls: true,
      }));
      return new Promise<ReturnType<typeof httpJson>>((resolve) => { finishOlderRead = resolve; });
    }));
    render(wrap(client, <ThreadShell
      session={session(chatId)} title="Published completion"
      onToggleSidebar={() => {}}
    />));
    await screen.findByText("question");
    act(() => {
      client._emitChat(chatId, {
        event: "goal_status", chat_id: chatId, turn_id: turnId,
        status: "running", started_at: 1_700,
      });
      client._emitChat(chatId, {
        event: "delta", chat_id: chatId, turn_id: turnId, turn_seq: 2,
        stream_id: "published-answer", text: "old active prefix",
      });
    });
    await screen.findByText("old active prefix");
    act(() => client._emitStatus("reconnecting"));
    act(() => client._emitStatus("open"));
    await waitFor(() => expect(historyCalls).toBe(2));
    const completed = {
      ...streamedThreadPayload(chatId, [
        { role: "user", content: "question", turnId },
        { role: "assistant", content: "externally published final answer", turnId, streamId: "published-answer" },
      ], [turnId]),
      revision: "completed-revision",
      has_pending_tool_calls: false,
    };
    act(() => publishReconnectCompletion(client, chatId, completed));
    expect(client.reconcileCanonicalCompletion).toHaveBeenCalledTimes(1);
    await screen.findByText("externally published final answer");
    expect(screen.queryByRole("button", { name: "Stop response" })).not.toBeInTheDocument();
    await act(async () => finishOlderRead(httpJson({
      ...streamedThreadPayload(chatId, [{ role: "user", content: "question", turnId }]),
      revision: "older-active-revision",
      has_pending_tool_calls: true,
      active_turn_id: turnId,
      completed_turn_ids: [],
    })));
    expect(screen.getByText("externally published final answer")).toBeInTheDocument();
    expect(screen.queryByText("old active prefix")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Stop response" })).not.toBeInTheDocument();
    expect(webuiThreadCache.get(`websocket:${chatId}`)).toBe(completed);
    expect(client.reconcileCanonicalCompletion).toHaveBeenCalledTimes(1);
  });

  it("refreshes after opening when mounted while the socket is reconnecting", async () => {
    const client = makeClient();
    client._emitStatus("reconnecting");
    let historyCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes("websocket%3Amount-during-reconnect/webui-thread")) {
          historyCalls += 1;
          return httpJson(transcriptFromSimpleMessages(
            historyCalls === 1
              ? [{ role: "user", content: "question before reconnect" }]
              : [
                  { role: "user", content: "question before reconnect" },
                  { role: "assistant", content: "answer completed before open" },
                ],
          ));
        }
        return {
          ok: false,
          status: 404,
          json: async () => ({}),
        };
      }),
    );

    render(
      wrap(
        client,
        <ThreadShell
          session={session("mount-during-reconnect")}
          title="Mount during reconnect"
          onToggleSidebar={() => {}}
        />,
      ),
    );

    await waitFor(() => expect(screen.getByText("question before reconnect")).toBeInTheDocument());
    expect(historyCalls).toBe(1);

    act(() => client._emitStatus("open"));

    await waitFor(() => expect(historyCalls).toBe(2));
    await waitFor(() =>
      expect(screen.getByText("answer completed before open")).toBeInTheDocument(),
    );
  });

  it("adopts a disjoint authoritative latest-window reset after overlap falls out", async () => {
    const client = makeClient();
    let historyCalls = 0;
    const canonicalTurnId = "turn-new-window";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes("websocket%3Awindow-reset-chat/webui-thread")) {
          historyCalls += 1;
          return httpJson({
            ...transcriptFromSimpleMessages(
              historyCalls === 1
                ? [
                    {
                      id: "expired-window-replay", role: "assistant",
                      content: "row from the expired latest window",
                      turnId: "turn-old-window",
                    },
                  ]
                : [
                    {
                      role: "user",
                      content: "question in the new latest window",
                      turnId: canonicalTurnId,
                    },
                    {
                      id: "new-window-replay", role: "assistant",
                      content: "answer in the new latest window",
                      turnId: canonicalTurnId,
                    },
                  ],
            ),
            has_pending_tool_calls: false,
          });
        }
        return {
          ok: false,
          status: 404,
          json: async () => ({}),
        };
      }),
    );

    render(
      wrap(
        client,
        <ThreadShell
          session={session("window-reset-chat")}
          title="Window reset"
          onToggleSidebar={() => {}}
        />,
      ),
    );

    await waitFor(() =>
      expect(screen.getByText("row from the expired latest window")).toBeInTheDocument(),
    );

    act(() => client._emitSessionUpdate("window-reset-chat", "thread"));

    await waitFor(() =>
      expect(screen.getByText("answer in the new latest window")).toBeInTheDocument(),
    );
    expect(screen.queryByText("row from the expired latest window")).not.toBeInTheDocument();
    expect(client.reconcileCanonicalCompletion).toHaveBeenCalledWith(
      "window-reset-chat",
      expect.any(Number),
      expect.arrayContaining([canonicalTurnId]),
      {
        observedTurnIds: [canonicalTurnId],
        hasPendingToolCalls: false,
        activeTurnId: null,
        completionIdsProvided: false,
      },
    );
  });

  it("recovers an uncommitted reset lineage on the next canonical hydrate", async () => {
    const client = makeClient();
    let chatACalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("websocket%3Alineage-chat-a/webui-thread")) {
          chatACalls += 1;
          return httpJson({
            ...transcriptFromSimpleMessages(
              chatACalls === 1
                ? [{ id: "old-lineage-replay", role: "assistant", content: "committed old lineage" }]
                : [{ id: "new-lineage-replay", role: "assistant", content: "disjoint new lineage" }],
            ),
            has_pending_tool_calls: false,
          });
        }
        if (url.includes("websocket%3Alineage-chat-b/webui-thread")) {
          return httpJson(transcriptFromSimpleMessages([
            { role: "assistant", content: "other lineage chat" },
          ]));
        }
        return {
          ok: false,
          status: 404,
          json: async () => ({}),
        };
      }),
    );
    const view = (chatId: string) => wrap(
      client,
      <ThreadShell
        session={session(chatId)}
        title={`Chat ${chatId}`}
        onToggleSidebar={() => {}}
      />,
    );
    const { rerender } = render(view("lineage-chat-a"));

    await waitFor(() => expect(screen.getByText("committed old lineage")).toBeInTheDocument());
    rerender(view("lineage-chat-b"));
    await waitFor(() => expect(screen.getByText("other lineage chat")).toBeInTheDocument());
    rerender(view("lineage-chat-a"));
    await waitFor(() => expect(chatACalls).toBe(2));

    expect(screen.getByText("committed old lineage")).toBeInTheDocument();
    expect(screen.queryByText("disjoint new lineage")).not.toBeInTheDocument();

    act(() => client._emitSessionUpdate("lineage-chat-a", "thread"));

    await waitFor(() => expect(chatACalls).toBe(3));
    await waitFor(() => expect(screen.getByText("disjoint new lineage")).toBeInTheDocument());
    expect(screen.queryByText("committed old lineage")).not.toBeInTheDocument();
  });

  it("does not reset away a durable UI tail that arrives after the request", async () => {
    const client = makeClient();
    let historyCalls = 0;
    let resolveRefresh:
      | ((value: ReturnType<typeof httpJson>) => void)
      | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        if (!String(input).includes("websocket%3Areset-tail-race/webui-thread")) {
          return Promise.resolve({
            ok: false,
            status: 404,
            json: async () => ({}),
          });
        }
        historyCalls += 1;
        if (historyCalls === 1) {
          return Promise.resolve(httpJson(transcriptFromSimpleMessages([
            { id: "old-canonical-replay", role: "assistant", content: "old canonical row" },
          ])));
        }
        return new Promise((resolve) => {
          resolveRefresh = resolve;
        });
      }),
    );

    render(
      wrap(
        client,
        <ThreadShell
          session={session("reset-tail-race")}
          title="Reset tail race"
          onToggleSidebar={() => {}}
        />,
      ),
    );

    await waitFor(() => expect(screen.getByText("old canonical row")).toBeInTheDocument());
    act(() => client._emitSessionUpdate("reset-tail-race", "thread"));
    await waitFor(() => expect(historyCalls).toBe(2));

    act(() => {
      client._emitChat("reset-tail-race", {
        event: "message",
        chat_id: "reset-tail-race",
        text: "local durable row after request", turn_id: "durable-post-request-turn", turn_seq: 2,
      });
    });
    await waitFor(() =>
      expect(screen.getByText("local durable row after request")).toBeInTheDocument(),
    );

    await act(async () => {
      resolveRefresh?.(httpJson({
        ...transcriptFromSimpleMessages([
          { id: "disjoint-canonical-replay", role: "assistant", content: "disjoint canonical reset row" },
        ]),
        has_pending_tool_calls: false,
      }));
      await Promise.resolve();
    });

    expect(screen.getByText("old canonical row")).toBeInTheDocument();
    expect(screen.getByText("local durable row after request")).toBeInTheDocument();
    expect(screen.queryByText("disjoint canonical reset row")).not.toBeInTheDocument();
  });

  it("safely commits an empty canonical reset for a rejected local turn", async () => {
    const client = makeClient();
    let historyCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes("websocket%3Aempty-reset-chat/webui-thread")) {
          historyCalls += 1;
          if (historyCalls > 1) return httpJson({
            schemaVersion: 3, projection: "events", events: [], has_pending_tool_calls: false,
          });
        }
        return {
          ok: false,
          status: 404,
          json: async () => ({}),
        };
      }),
    );

    render(
      wrap(
        client,
        <ThreadShell
          session={session("empty-reset-chat")}
          title="Empty reset"
          onToggleSidebar={() => {}}
        />,
      ),
    );

    await waitFor(() => expect(historyCalls).toBe(1));
    const input = screen.getByRole("textbox", { name: "Message input" });
    fireEvent.change(input, { target: { value: "rejected local turn" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(screen.getByText("rejected local turn")).toBeInTheDocument());
    const rejectedTurnId = client.sendMessage.mock.calls[0]?.[3]?.turnId;
    expect(rejectedTurnId).toBeTruthy();
    act(() => client._emitError({
      kind: "turn_rejected", chatId: "empty-reset-chat", turnId: rejectedTurnId!,
      detail: "message_rejected",
    }));

    act(() => {
      client._emitError({
        kind: "turn_rejected", chatId: "empty-reset-chat",
        turnId: client.sendMessage.mock.calls[0][3]!.turnId!,
      });
      client._emitSessionUpdate("empty-reset-chat", "thread");
    });

    await waitFor(() => expect(historyCalls).toBe(2));
    await waitFor(() =>
      expect(screen.queryByText("rejected local turn")).not.toBeInTheDocument(),
    );
    expect(client.reconcileCanonicalCompletion).toHaveBeenCalledWith(
      "empty-reset-chat",
      expect.any(Number),
      [],
      {
        observedTurnIds: [],
        hasPendingToolCalls: false,
        activeTurnId: null,
        completionIdsProvided: false,
      },
    );
  });

  it("runs canonical reconciliation once when React replays state calculations", async () => {
    const client = makeClient();
    const turnId = "turn-strict-canonical";
    let canonicalComplete = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes("websocket%3Astrict-canonical/webui-thread")) {
          return httpJson({
            ...streamedThreadPayload("strict-canonical",
              canonicalComplete
                ? [
                    { role: "user", content: "strict question", turnId },
                    { role: "assistant", content: "strict canonical answer", turnId, streamId: "strict-answer" },
                  ]
                : [{ role: "user", content: "strict question", turnId }],
              canonicalComplete ? [turnId] : [],
            ),
            has_pending_tool_calls: !canonicalComplete,
          });
        }
        return {
          ok: false,
          status: 404,
          json: async () => ({}),
        };
      }),
    );

    render(
      wrap(
        client,
        <StrictMode>
          <ThreadShell
            session={session("strict-canonical")}
            title="Strict canonical"
            onToggleSidebar={() => {}}
          />
        </StrictMode>,
      ),
    );

    await waitFor(() => expect(screen.getByText("strict question")).toBeInTheDocument());
    act(() => {
      client._emitChat("strict-canonical", {
        event: "goal_status",
        chat_id: "strict-canonical",
        status: "running",
        started_at: 2_100,
        turn_id: turnId,
      });
      client._emitChat("strict-canonical", {
        event: "delta",
        chat_id: "strict-canonical",
        text: "strict partial",
        turn_id: turnId, turn_seq: 2, stream_id: "strict-answer",
      });
    });
    await waitFor(() => expect(screen.getByText("strict partial")).toBeInTheDocument());
    client.reconcileCanonicalCompletion.mockClear();
    canonicalComplete = true;

    act(() => client._emitSessionUpdate("strict-canonical", "thread"));

    await waitFor(() => expect(screen.getByText("strict canonical answer")).toBeInTheDocument());
    expect(client.reconcileCanonicalCompletion).toHaveBeenCalledTimes(1);
    expect(client.canReconcileCanonicalCompletion).toHaveBeenCalled();
  });

  it("keeps completed content while a newer run blocks lifecycle reconciliation", async () => {
    const client = makeClient();
    const chatId = "layout-recheck";
    const turnId = "turn-layout-recheck";
    const newerTurnId = "newer-layout-turn";
    let historyCalls = 0;
    let finishRefresh!: (response: Response) => void;
    const completedBody = (includeNewer: boolean) => {
      const rows: StreamedFixtureRow[] = [
        { role: "user", content: "layout question", turnId },
        { role: "assistant", content: "layout canonical answer", turnId, streamId: "layout-answer" },
      ];
      if (includeNewer) rows.push(
        { role: "user", content: "newer layout question", turnId: newerTurnId },
        { role: "assistant", content: "newer layout complete", turnId: newerTurnId, streamId: "newer-layout-answer" },
      );
      return {
        ...streamedThreadPayload(chatId, rows, includeNewer ? [turnId, newerTurnId] : [turnId]),
        has_pending_tool_calls: false,
      };
    };
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      if (!String(input).includes(`websocket%3A${chatId}/webui-thread`)) {
        return Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
      }
      historyCalls += 1;
      if (historyCalls === 1) return Promise.resolve(httpJson({
        ...streamedThreadPayload(chatId, [{ role: "user", content: "layout question", turnId }]),
        has_pending_tool_calls: true,
      }));
      if (historyCalls === 2) return new Promise<Response>((resolve) => { finishRefresh = resolve; });
      return Promise.resolve(httpJson(completedBody(true)));
    }));
    render(wrap(client, <ThreadShell session={session(chatId)} title="Layout recheck"
      onToggleSidebar={() => {}} />));
    await screen.findByText("layout question");
    act(() => {
      client._emitChat(chatId, {
        event: "goal_status", chat_id: chatId, status: "running", started_at: 2_200, turn_id: turnId,
      });
      client._emitChat(chatId, {
        event: "delta", chat_id: chatId, text: "layout partial", turn_id: turnId,
        turn_seq: 2, stream_id: "layout-answer",
      });
    });
    await screen.findByText("layout partial");
    act(() => client._emitSessionUpdate(chatId, "thread"));
    await waitFor(() => expect(historyCalls).toBe(2));

    // Another tab starts a newer turn while this read is pending. Its running
    // status invalidates settlement before the pure preflight runs.
    act(() => {
      for (const event of streamedThreadPayload(chatId, [
        { role: "user", content: "newer layout question", turnId: newerTurnId },
      ]).events) client._emitChat(chatId, event);
      client._emitChat(chatId, {
        event: "goal_status", chat_id: chatId, status: "running", started_at: 2_300, turn_id: newerTurnId,
      });
      client._emitChat(chatId, {
        event: "delta", chat_id: chatId, text: "newer layout partial", turn_id: newerTurnId,
        turn_seq: 2, stream_id: "newer-layout-answer",
      });
    });
    await screen.findByText("newer layout partial");
    await act(async () => finishRefresh(httpJson(completedBody(false))));
    await screen.findByText("layout canonical answer");
    expect(screen.queryByText("layout partial")).not.toBeInTheDocument();
    expect(screen.getByText("newer layout partial")).toBeInTheDocument();
    expect(client.reconcileCanonicalCompletion).not.toHaveBeenCalled();
    expect(client.isRunCompleted(chatId, turnId)).toBe(true);
    expect(screen.getByRole("button", { name: "Stop response" })).toBeInTheDocument();

    act(() => client._emitSessionUpdate(chatId, "thread"));
    await screen.findByText("newer layout complete");
    expect(historyCalls).toBe(3);
    expect(screen.getByText("layout canonical answer")).toBeInTheDocument();
    expect(screen.queryByText("layout partial")).not.toBeInTheDocument();
    expect(screen.queryByText("newer layout partial")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Stop response" })).not.toBeInTheDocument();
    expect(client.reconcileCanonicalCompletion).toHaveBeenCalledTimes(1);
  });

  it("adopts a completed equal-length history when returning after an inactive outage", async () => {
    const client = makeClient();
    const oldTurnId = "turn-old";
    let newTurnId = "";
    let chatACalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("websocket%3Achat-version-a/webui-thread")) {
          chatACalls += 1;
          const rows: StreamedFixtureRow[] = [
            { role: "user", content: "old question", turnId: oldTurnId },
            { role: "assistant", content: "old answer", turnId: oldTurnId, streamId: "old-answer" },
          ];
          if (chatACalls > 2) rows.push(
            { role: "user", content: "new question", turnId: newTurnId },
            { role: "assistant", content: "partial answer completed", turnId: newTurnId, streamId: "new-answer" },
          );
          return httpJson({
            ...streamedThreadPayload("chat-version-a", rows, chatACalls <= 2 ? [oldTurnId] : [oldTurnId, newTurnId]),
            has_pending_tool_calls: false,
          });
        }
        if (url.includes("websocket%3Achat-version-b/webui-thread")) {
          return httpJson(transcriptFromSimpleMessages([
            { role: "user", content: "other chat" },
          ]));
        }
        return {
          ok: false,
          status: 404,
          json: async () => ({}),
        };
      }),
    );
    const view = (chatId: string) => wrap(
      client,
      <ThreadShell
        session={session(chatId)}
        title={`Chat ${chatId}`}
        onToggleSidebar={() => {}}
      />,
    );
    const { rerender } = render(view("chat-version-a"));

    await waitFor(() => expect(screen.getByText("old answer")).toBeInTheDocument());
    act(() => client._emitSessionUpdate("chat-version-a"));
    await waitFor(() => expect(chatACalls).toBe(2));

    fireEvent.change(screen.getByRole("textbox", { name: "Message input" }), {
      target: { value: "new question" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(client.sendMessage).toHaveBeenCalledTimes(1));
    newTurnId = (
      client.sendMessage.mock.calls[0]?.[3] as { turnId?: string } | undefined
    )?.turnId ?? "";
    expect(newTurnId).not.toBe("");
    act(() => {
      client._emitChat("chat-version-a", {
        event: "goal_status",
        chat_id: "chat-version-a",
        status: "running",
        started_at: 2_000,
        turn_id: newTurnId,
      });
      client._emitChat("chat-version-a", {
        event: "delta",
        chat_id: "chat-version-a",
        text: "partial answer",
        turn_id: newTurnId, turn_seq: 2, stream_id: "new-answer",
      });
    });
    await waitFor(() => expect(screen.getByText("partial answer")).toBeInTheDocument());

    rerender(view("chat-version-b"));
    await waitFor(() => expect(screen.getByText("other chat")).toBeInTheDocument());
    act(() => client._emitStatus("reconnecting"));
    act(() => client._emitStatus("open"));
    rerender(view("chat-version-a"));
    await waitFor(() => expect(chatACalls).toBe(3));
    await waitFor(() =>
      expect(screen.getByText("partial answer completed")).toBeInTheDocument(),
    );
    expect(screen.queryByText("partial answer")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Stop response" })).not.toBeInTheDocument();
  });

  it("does not let an older completed snapshot clear a run that starts in flight", async () => {
    const client = makeClient();
    const oldTurnId = "turn-before-refresh";
    let historyCalls = 0;
    let resolveRefresh:
      | ((value: { ok: boolean; status: number; json: () => Promise<unknown> }) => void)
      | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (!url.includes("websocket%3Arun-generation-chat/webui-thread")) {
          return Promise.resolve({
            ok: false,
            status: 404,
            json: async () => ({}),
          });
        }
        historyCalls += 1;
        if (historyCalls === 1) {
          return Promise.resolve(httpJson(transcriptFromSimpleMessages([
            { role: "user", content: "old question", turnId: oldTurnId },
            { role: "assistant", content: "old answer", turnId: oldTurnId },
          ])));
        }
        return new Promise((resolve) => {
          resolveRefresh = resolve;
        });
      }),
    );

    render(
      wrap(
        client,
        <ThreadShell
          session={session("run-generation-chat")}
          title="Run generation chat"
          onToggleSidebar={() => {}}
        />,
      ),
    );

    await waitFor(() => expect(screen.getByText("old answer")).toBeInTheDocument());
    act(() => client._emitSessionUpdate("run-generation-chat", "thread"));
    await waitFor(() => expect(historyCalls).toBe(2));

    const newTurnId = "turn-started-during-refresh";
    act(() => {
      client._emitChat("run-generation-chat", {
        event: "goal_status",
        chat_id: "run-generation-chat",
        status: "running",
        started_at: 3_000,
        turn_id: newTurnId,
      });
    });
    const input = screen.getByRole("textbox", { name: "Message input" });
    fireEvent.change(input, { target: { value: "queued for the new run" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(client.sendMessage).not.toHaveBeenCalled();

    await act(async () => {
      resolveRefresh?.(httpJson({
        ...transcriptFromSimpleMessages([
          { role: "user", content: "old question", turnId: oldTurnId },
          { role: "assistant", content: "old answer", turnId: oldTurnId },
        ]),
        has_pending_tool_calls: false,
      }));
      await Promise.resolve();
    });

    expect(screen.getByRole("button", { name: "Stop response" })).toBeInTheDocument();
    expect(client.sendMessage).not.toHaveBeenCalled();
  });

  it.each(["raw-turn", "session-message"] as const)("keeps repeated guidance order and newer live output with stable %s sources", async (guidanceIdentity) => {
    const client = makeClient();
    const chatId = "completed-guidance-new-tail";
    const turnId = "completed-guided-turn";
    const guidanceRows = ["guidance-input", "repeated-guidance-input"].map((id): StreamedFixtureRow => ({
      role: "user", content: "supplemental guidance", startsTurn: false, activeTurnId: turnId,
      ...(guidanceIdentity === "raw-turn"
        ? { turnId: id }
        : { sessionMessage: { message_id: id, session: { id: "guidance-session", name: "Guidance" } } }),
    }));
    let historyCalls = 0;
    let resolveRefresh!: (response: ReturnType<typeof httpJson>) => void;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      if (!String(input).includes(`websocket%3A${chatId}/webui-thread`)) {
        return Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
      }
      historyCalls += 1;
      if (historyCalls === 1) return Promise.resolve(httpJson({
        ...streamedThreadPayload(chatId, [{ role: "user", content: "guided question", turnId }]),
        has_pending_tool_calls: true,
      }));
      return new Promise<ReturnType<typeof httpJson>>((resolve) => { resolveRefresh = resolve; });
    }));
    render(wrap(client, <ThreadShell
      session={session(chatId)} title="Guided turn"
      onToggleSidebar={() => {}}
    />));
    await screen.findByText("guided question");
    act(() => {
      client._emitChat(chatId, {
        event: "goal_status", chat_id: chatId, status: "running",
        started_at: 1_700, turn_id: turnId,
      });
      client._emitChat(chatId, {
        event: "delta", chat_id: chatId, text: "first partial segment", turn_id: turnId,
        turn_seq: 2, stream_id: "guided-first-answer",
      });
    });
    await screen.findByText("first partial segment");
    act(() => {
      client._emitChat(chatId, {
        event: "stream_end", chat_id: chatId, turn_id: turnId, resuming: true,
        turn_seq: 3, stream_id: "guided-first-answer", text: "first partial segment",
      });
      for (const event of streamedThreadPayload(chatId, guidanceRows).events) client._emitChat(chatId, event);
      client._emitChat(chatId, {
        event: "delta", chat_id: chatId, turn_id: turnId, text: "last partial segment",
        turn_seq: 4, stream_id: "guided-last-answer",
      });
    });
    await screen.findByText("last partial segment");
    act(() => client._emitSessionUpdate(chatId, "thread"));
    await waitFor(() => expect(historyCalls).toBe(2));
    act(() => client._emitChat(chatId, {
      event: "turn_end", chat_id: chatId, turn_id: turnId, turn_seq: 6,
    }));
    fireEvent.change(screen.getByRole("textbox", { name: "Message input" }), {
      target: { value: "new local question" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    const newerTurnId = client.sendMessage.mock.calls[0]?.[3]?.turnId;
    expect(newerTurnId).toBeTruthy();
    act(() => {
      client._emitChat(chatId, {
        event: "goal_status", chat_id: chatId, status: "running",
        started_at: 2_000, turn_id: newerTurnId,
      });
      client._emitChat(chatId, {
        event: "delta", chat_id: chatId, turn_id: newerTurnId, text: "newer live reply",
        turn_seq: 2, stream_id: "newer-guidance-answer",
      });
    });
    await screen.findByText("newer live reply");
    await act(async () => resolveRefresh(httpJson({
      ...streamedThreadPayload(chatId, [
        { role: "user", content: "guided question", turnId },
        { role: "assistant", content: "canonical first segment", turnId, streamId: "guided-first-answer" },
        ...guidanceRows,
        { role: "assistant", content: "canonical final segment", turnId, streamId: "guided-last-answer", textSeq: 4, endSeq: 5 },
      ], [turnId]),
      has_pending_tool_calls: false,
    })));
    const first = await screen.findByText("canonical first segment");
    const guidance = screen.getAllByText("supplemental guidance");
    const final = screen.getByText("canonical final segment");
    const newer = screen.getByText("newer live reply");
    expect(guidance).toHaveLength(2);
    expect(first.compareDocumentPosition(guidance[0]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(guidance[0].compareDocumentPosition(guidance[1]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(guidance[1].compareDocumentPosition(final) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(final.compareDocumentPosition(newer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByText("first partial segment")).not.toBeInTheDocument();
    expect(screen.queryByText("last partial segment")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop response" })).toBeInTheDocument();
    act(() => {
      client._emitChat(chatId, {
        event: "delta", chat_id: chatId, turn_id: turnId, text: "obsolete delayed delta",
        turn_seq: 7, stream_id: "guided-last-answer",
      });
      client._emitChat(chatId, {
        event: "delta", chat_id: chatId, turn_id: newerTurnId, text: " continued",
        turn_seq: 3, stream_id: "newer-guidance-answer",
      });
    });
    await screen.findByText("newer live reply continued");
    expect(screen.queryByText(/obsolete delayed delta/)).not.toBeInTheDocument();
    expect(screen.queryByText("newer live reply")).not.toBeInTheDocument();
  });

  it("keeps canonical completed turns after an older cached pagination prefix", async () => {
    const client = makeClient();
    const chatId = "completed-window-order";
    const completedTurnId = "completed-cached-turn";
    const unseenTurnId = "other-tab-completed-turn";
    const newerTurnId = "new-local-turn";
    const messageCache = new ThreadMessageCache(() => false);
    const owner = new ThreadTranscript([
      { id: "older-page", role: "assistant", content: "older paginated answer", createdAt: 1 },
    ]);
    const cachedEvents = [
      { event: "user_message", chat_id: chatId, turn_id: completedTurnId, turn_seq: 1,
        text: "completed question", starts_turn: true },
      { event: "delta", chat_id: chatId, turn_id: completedTurnId, turn_seq: 2,
        stream_id: "completed-cached-answer", text: "outdated prefix" },
      { event: "user_message", chat_id: chatId, turn_id: newerTurnId, turn_seq: 1,
        text: "new local question", starts_turn: true },
      { event: "delta", chat_id: chatId, turn_id: newerTurnId, turn_seq: 2,
        stream_id: "new-local-answer", text: "new local stream" },
    ] satisfies ThreadProjectionEvent[];
    cachedEvents.forEach((event, index) => owner.project(event, {
      createId: () => `cached-${index}`, now: index + 2,
    }));
    messageCache.set(chatId, owner.save());
    client._emitChat(chatId, {
      event: "goal_status", chat_id: chatId, turn_id: newerTurnId, status: "running", started_at: 2_000,
    });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (!String(input).includes(`websocket%3A${chatId}/webui-thread`)) {
        return { ok: false, status: 404, json: async () => ({}) };
      }
      return httpJson({
        ...streamedThreadPayload(chatId, [
          { role: "user", content: "completed question", turnId: completedTurnId },
          { role: "assistant", content: "completed reply", turnId: completedTurnId, streamId: "completed-cached-answer" },
          { role: "user", content: "other tab question", turnId: unseenTurnId },
          { role: "assistant", content: "other tab completed reply", turnId: unseenTurnId, streamId: "other-tab-answer" },
        ], [completedTurnId, unseenTurnId]),
        has_pending_tool_calls: false,
        completed_turn_ids: [completedTurnId, unseenTurnId],
        page: { before_cursor: "older-page", has_more_before: true, user_message_offset: 25 },
      });
    }));
    render(wrap(client, <ThreadShell
      session={session(chatId)} title="Completed latest window" messageCache={messageCache}
      onToggleSidebar={() => {}}
    />));
    const completed = await screen.findByText("completed reply");
    const older = screen.getByText("older paginated answer");
    const other = screen.getByText("other tab completed reply");
    const newer = screen.getByText("new local stream");
    expect(older.compareDocumentPosition(completed) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(completed.compareDocumentPosition(other) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(other.compareDocumentPosition(newer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByText("outdated prefix")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop response" })).toBeInTheDocument();
  });

  it.each(["raw-turn", "session-message"] as const)("keeps completed guidance after a paginated prefix with stable %s sources", async (guidanceIdentity) => {
    const client = makeClient();
    const chatId = "completed-guidance-paged-prefix";
    const guidanceRow: StreamedFixtureRow = {
      role: "user", content: "continue", startsTurn: false, activeTurnId: "main",
      ...(guidanceIdentity === "raw-turn"
        ? { turnId: "guidance" }
        : { sessionMessage: { message_id: "cached-guidance", session: { id: "guidance-session", name: "Guidance" } } }),
    };
    const messageCache = new ThreadMessageCache(() => false);
    const owner = new ThreadTranscript([
      { id: "old-user", role: "user", content: "continue", createdAt: 1 },
      { id: "old-answer", role: "assistant", content: "older answer", createdAt: 2 },
    ]);
    const cachedEvents = [
      { event: "user_message", chat_id: chatId, turn_id: "main", turn_seq: 1,
        text: "current question", starts_turn: true },
      { event: "delta", chat_id: chatId, turn_id: "main", turn_seq: 2,
        stream_id: "main-first-answer", text: "first partial" },
      ...streamedThreadPayload(chatId, [guidanceRow]).events,
      { event: "delta", chat_id: chatId, turn_id: "main", turn_seq: 4,
        stream_id: "main-last-answer", text: "last partial" },
      { event: "user_message", chat_id: chatId, turn_id: "new", turn_seq: 1,
        text: "new question", starts_turn: true },
      { event: "delta", chat_id: chatId, turn_id: "new", turn_seq: 2,
        stream_id: "new-live-answer", text: "new live answer" },
    ] satisfies ThreadProjectionEvent[];
    cachedEvents.forEach((event, index) => owner.project(event, {
      createId: () => `cached-${index}`, now: index + 3,
    }));
    messageCache.set(chatId, owner.save());
    client._emitChat(chatId, {
      event: "goal_status", chat_id: chatId, turn_id: "new", status: "running", started_at: 2_000,
    });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (!String(input).includes(`websocket%3A${chatId}/webui-thread`)) {
        return { ok: false, status: 404, json: async () => ({}) };
      }
      return httpJson({
        ...streamedThreadPayload(chatId, [
          { role: "user", content: "current question", turnId: "main" },
          { role: "assistant", content: "completed first", turnId: "main", streamId: "main-first-answer" },
          guidanceRow,
          { role: "assistant", content: "completed last", turnId: "main", streamId: "main-last-answer", textSeq: 4, endSeq: 5 },
        ], ["main"]),
        has_pending_tool_calls: false,
        completed_turn_ids: ["main"],
        page: { before_cursor: "older-page", has_more_before: true, user_message_offset: 25 },
      });
    }));
    render(wrap(client, <ThreadShell
      session={session(chatId)} title="Completed paged guidance" messageCache={messageCache}
      onToggleSidebar={() => {}}
    />));
    await screen.findByText("completed last");
    const messages = [
      ...screen.getAllByText("continue"),
      ...["older answer", "current question", "completed first", "completed last", "new question", "new live answer"]
        .map((text) => screen.getByText(text)),
    ];
    messages.sort((a, b) => a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1);
    expect(messages.map((message) => message.textContent)).toEqual([
      "continue", "older answer", "current question", "completed first",
      "continue", "completed last", "new question", "new live answer",
    ]);
    expect(screen.queryByText("first partial")).not.toBeInTheDocument();
    expect(screen.queryByText("last partial")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop response" })).toBeInTheDocument();
    act(() => client._emitChat(chatId, {
      event: "delta", chat_id: chatId, turn_id: "new", text: " continued",
      turn_seq: 3, stream_id: "new-live-answer",
    }));
    await screen.findByText("new live answer continued");
  });

  it("remembers explicit completed turns on initial history load", async () => {
    const client = makeClient();
    const turnId = "turn-completed-before-load";
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("websocket%3Ainitial-completion/webui-thread")) {
        return httpJson({
          ...transcriptFromSimpleMessages([
            { role: "user", content: "previous question", turnId },
          ]),
          has_pending_tool_calls: false,
          completed_turn_ids: [turnId],
        });
      }
      return { ok: false, status: 404, json: async () => ({}) };
    }));
    render(wrap(client, <ThreadShell
      session={session("initial-completion")}
      title="Initial completion"
      onToggleSidebar={() => {}}
    />));
    await screen.findByText("previous question");
    act(() => client._emitChat("initial-completion", {
      event: "goal_status", chat_id: "initial-completion", turn_id: turnId,
      status: "running", started_at: 4_000,
    }));
    expect(screen.queryByRole("button", { name: "Stop response" })).not.toBeInTheDocument();
    act(() => client._emitChat("initial-completion", {
      event: "goal_status", chat_id: "initial-completion", turn_id: "new-turn",
      status: "running", started_at: 5_000,
    }));
    expect(screen.getByRole("button", { name: "Stop response" })).toBeInTheDocument();
  });

  it("fences websocket frames that arrive after canonical completion", async () => {
    const client = makeClient();
    const turnId = "turn-http-won";
    let historyCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("websocket%3Alate-frame-chat/webui-thread")) {
          historyCalls += 1;
          return httpJson({
            ...streamedThreadPayload("late-frame-chat",
              historyCalls === 1
                ? [{ role: "user", content: "question", turnId }]
                : [
                    { role: "user", content: "question", turnId },
                    { role: "assistant", content: "canonical complete answer", turnId, streamId: "http-won-answer" },
                  ],
              historyCalls === 1 ? [] : [turnId],
            ),
            has_pending_tool_calls: false,
          });
        }
        return {
          ok: false,
          status: 404,
          json: async () => ({}),
        };
      }),
    );

    render(
      wrap(
        client,
        <ThreadShell
          session={session("late-frame-chat")}
          title="Late frame chat"
          onToggleSidebar={() => {}}
        />,
      ),
    );

    await waitFor(() => expect(screen.getByText("question")).toBeInTheDocument());
    act(() => {
      client._emitChat("late-frame-chat", {
        event: "goal_status",
        chat_id: "late-frame-chat",
        status: "running",
        started_at: 4_000,
        turn_id: turnId,
      });
      client._emitChat("late-frame-chat", {
        event: "delta",
        chat_id: "late-frame-chat",
        text: "partial",
        turn_id: turnId, turn_seq: 2, stream_id: "http-won-answer",
      });
    });
    await waitFor(() => expect(screen.getByText("partial")).toBeInTheDocument());

    act(() => client._emitSessionUpdate("late-frame-chat", "thread"));
    await waitFor(() =>
      expect(screen.getByText("canonical complete answer")).toBeInTheDocument(),
    );

    act(() => {
      client._emitChat("late-frame-chat", {
        event: "delta",
        chat_id: "late-frame-chat",
        text: " delayed duplicate",
        turn_id: turnId, turn_seq: 2, stream_id: "http-won-answer",
      });
      client._emitChat("late-frame-chat", {
        event: "turn_end",
        chat_id: "late-frame-chat",
        turn_id: turnId, turn_seq: 4,
      });
      client._emitSessionUpdate("late-frame-chat");
    });

    await waitFor(() => expect(historyCalls).toBe(3));
    expect(screen.getAllByText("canonical complete answer")).toHaveLength(1);
    expect(screen.queryByText("partial")).not.toBeInTheDocument();
    expect(screen.queryByText(" delayed duplicate")).not.toBeInTheDocument();
    expect(screen.queryByText("canonical complete answer delayed duplicate")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Stop response" })).not.toBeInTheDocument();
  });

  it("does not revive a canonically completed run after switching chats", async () => {
    const client = makeClient();
    const turnId = "turn-visibility-complete";
    let chatACalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("websocket%3Avisibility-complete-a/webui-thread")) {
          chatACalls += 1;
          return httpJson({
            ...transcriptFromSimpleMessages(
              chatACalls === 1
                ? [{ role: "user", content: "question", turnId }]
                : [
                    { role: "user", content: "question", turnId },
                    { role: "assistant", content: "completed while hidden", turnId },
                  ],
            ),
            has_pending_tool_calls: false,
          });
        }
        if (url.includes("websocket%3Avisibility-complete-b/webui-thread")) {
          return httpJson(transcriptFromSimpleMessages([
            { role: "user", content: "other thread" },
          ]));
        }
        return {
          ok: false,
          status: 404,
          json: async () => ({}),
        };
      }),
    );
    const view = (chatId: string) => wrap(
      client,
      <ThreadShell
        session={session(chatId)}
        title={`Chat ${chatId}`}
        onToggleSidebar={() => {}}
      />,
    );
    const { rerender } = render(view("visibility-complete-a"));

    await waitFor(() => expect(screen.getByText("question")).toBeInTheDocument());
    act(() => {
      client._emitChat("visibility-complete-a", {
        event: "goal_status",
        chat_id: "visibility-complete-a",
        status: "running",
        started_at: 5_000,
        turn_id: turnId,
      });
    });
    expect(screen.getByRole("button", { name: "Stop response" })).toBeInTheDocument();

    act(() => client._emitSessionUpdate("visibility-complete-a", "thread"));
    await waitFor(() => expect(screen.getByText("completed while hidden")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Stop response" })).not.toBeInTheDocument();
    expect(client.getRunStartedAt("visibility-complete-a")).toBeNull();

    rerender(view("visibility-complete-b"));
    await waitFor(() => expect(screen.getByText("other thread")).toBeInTheDocument());
    rerender(view("visibility-complete-a"));
    await waitFor(() => expect(screen.getByText("completed while hidden")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Stop response" })).not.toBeInTheDocument();
  });

  it("uses explicit completion ids when a completed turn has no assistant row", async () => {
    const client = makeClient();
    const turnId = "turn-empty-answer";
    let historyCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes("websocket%3Aempty-answer/webui-thread")) {
          historyCalls += 1;
          return httpJson({
            ...transcriptFromSimpleMessages([
              { role: "user", content: "stop", turnId },
            ]),
            has_pending_tool_calls: historyCalls === 1,
            completed_turn_ids: historyCalls === 1 ? [] : [turnId],
          });
        }
        return {
          ok: false,
          status: 404,
          json: async () => ({}),
        };
      }),
    );
    render(
      wrap(
        client,
        <ThreadShell
          session={session("empty-answer")}
          title="Empty answer"
          onToggleSidebar={() => {}}
        />,
      ),
    );

    await waitFor(() => expect(screen.getByText("stop")).toBeInTheDocument());
    act(() => {
      client._emitChat("empty-answer", {
        event: "goal_status",
        chat_id: "empty-answer",
        status: "running",
        started_at: 5_000,
        turn_id: turnId,
      });
    });
    expect(screen.getByRole("button", { name: "Stop response" })).toBeInTheDocument();

    act(() => client._emitSessionUpdate("empty-answer", "thread"));

    await waitFor(() => expect(historyCalls).toBe(2));
    await waitFor(() => expect(client.reconcileCanonicalCompletion).toHaveBeenCalledWith(
      "empty-answer",
      expect.any(Number),
      expect.arrayContaining([turnId]),
      expect.objectContaining({
        observedTurnIds: [turnId],
        hasPendingToolCalls: false,
      }),
    ));
    expect(screen.queryByRole("button", { name: "Stop response" })).not.toBeInTheDocument();
  });

  it.each(["persisted-turn", "recovery:restored-turn"])(
    "loads history when opening a running session without settling %s",
    async (turnId) => {
      const client = makeClient();
      const chatId = "running-history";
      client._emitChat(chatId, {
        event: "goal_status", chat_id: chatId, status: "running",
        started_at: 1_700, turn_id: turnId,
      });
      vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes(`websocket%3A${chatId}/webui-thread`)) {
          return httpJson({
            ...streamedThreadPayload(chatId, [
              { role: "user", content: "previous question", turnId: "finished-turn" },
              { role: "assistant", content: "previous answer", turnId: "finished-turn", streamId: "finished-answer" },
              { role: "user", content: "current question", turnId: "persisted-turn" },
              { role: "assistant", content: "saved answer prefix", turnId: "persisted-turn", streamId: "saved-answer" },
            ], ["finished-turn"]),
            completed_turn_ids: ["finished-turn"],
            has_pending_tool_calls: true,
            active_turn_id: turnId,
          });
        }
        return { ok: false, status: 404, json: async () => ({}) };
      }));

      render(wrap(client, <ThreadShell
        session={session(chatId)} title="Running history"
        onToggleSidebar={() => {}}
      />));

      await screen.findByText("previous answer");
      expect(screen.getByText("current question")).toBeInTheDocument();
      expect(screen.getByText("saved answer prefix")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Stop response" })).toBeInTheDocument();
      expect(client.reconcileCanonicalCompletion).not.toHaveBeenCalled();
      expect(client.getRunStartedAt(chatId)).toBe(1_700);

      const input = screen.getByRole("textbox", { name: "Message input" });
      fireEvent.change(input, { target: { value: "queued guidance" } });
      fireEvent.keyDown(input, { key: "Enter" });
      expect(client.sendMessage).not.toHaveBeenCalled();

      act(() => client._emitChat(chatId, {
        event: "delta", chat_id: chatId, turn_id: turnId, text: "continued",
        turn_seq: 4, stream_id: "continued-answer",
      }));
      await screen.findByText("continued");
      act(() => client._emitChat(chatId, {
        event: "delta", chat_id: chatId, turn_id: turnId, text: " answer",
        turn_seq: 5, stream_id: "continued-answer",
      }));
      await screen.findByText("continued answer");
      expect(screen.getByText("saved answer prefix")).toBeInTheDocument();
      expect(client.sendMessage).not.toHaveBeenCalled();
    },
  );

  it.each([
    { name: "visible rows after a hidden command prefix", rows: [
      { role: "user" as const, content: "/model hidden", turnId: "webui-system:model" },
      { role: "assistant" as const, content: "hidden model response", turnId: "webui-system:model" },
      { role: "user" as const, content: "older question", turnId: "older-turn" },
      { role: "assistant" as const, content: "older answer", turnId: "older-turn" },
    ], expectVisible: true },
    { name: "a page containing only hidden command rows", rows: [
      { role: "user" as const, content: "/model hidden", turnId: "webui-system:model" },
      { role: "assistant" as const, content: "hidden model response", turnId: "webui-system:model" },
    ], expectVisible: false },
    { name: "an empty successful page", rows: [], expectVisible: false },
    { name: "a failed page", rows: [], expectVisible: false, error: true },
  ])("atomically publishes older-page rows and loading completion for $name", async ({ rows, expectVisible, error = false }) => {
    const client = makeClient();
    const chatId = `older-projection-${expectVisible ? "visible" : "hidden"}`;
    let resolveOlder!: (response: Response) => void;
    let olderReturned = false;
    const commits: Array<{ loading: boolean; olderVisible: boolean }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (!url.includes(`websocket%3A${chatId}/webui-thread`)) {
        return { ok: false, status: 404, json: async () => ({}) };
      }
      if (url.includes("before=")) {
        return new Promise<Response>((resolve) => { resolveOlder = resolve; });
      }
      return httpJson({
        ...transcriptFromSimpleMessages([
          { role: "user", content: "current question", turnId: "current-turn" },
        ]),
        has_pending_tool_calls: expectVisible,
        active_turn_id: expectVisible ? "current-turn" : null,
        completed_turn_ids: [],
        page: { before_cursor: "older-page", has_more_before: true, user_message_offset: 1 },
      });
    }));
    const capture = () => {
      if (!olderReturned) return;
      commits.push({
        loading: document.querySelector('.thread-history-status[data-state="loading"]') !== null,
        olderVisible: document.body.textContent?.includes("older answer") ?? false,
      });
    };
    const { container } = render(wrap(client, <Profiler id="older-history" onRender={capture}>
      <ThreadShell session={session(chatId)} title="Older projection" onToggleSidebar={() => {}} />
    </Profiler>));
    await screen.findByText("current question");
    const scroller = container.querySelector(".thread-message-viewport") as HTMLElement;
    Object.defineProperties(scroller, {
      scrollHeight: { configurable: true, value: 2400 },
      clientHeight: { configurable: true, value: 600 },
      scrollTop: { configurable: true, writable: true, value: 0 },
    });
    fireEvent.keyDown(scroller, { key: "Home" });
    await waitFor(() => expect(resolveOlder).toBeTypeOf("function"));
    await screen.findByText("Loading earlier messages…");
    if (expectVisible) {
      act(() => client._emitChat(chatId, {
        event: "delta", chat_id: chatId, turn_id: "current-turn", text: "live during pagination",
        turn_seq: 2, stream_id: "pagination-answer",
      }));
      await screen.findByText("live during pagination");
    }
    const olderPayload = rows.length > 0
      ? transcriptFromSimpleMessages(rows)
      : { schemaVersion: 3, projection: "events", events: [], page: { before_cursor: null, has_more_before: false } };
    olderReturned = true;
    await act(async () => {
      resolveOlder(error
        ? new Response("History unavailable", { status: 503 })
        : httpJson({ ...olderPayload, page: { before_cursor: null, has_more_before: false } }));
    });
    if (expectVisible) await screen.findByText("older answer");
    await waitFor(() => expect(container.querySelector('.thread-history-status[data-state="loading"]')).toBeNull());
    expect(commits.length).toBeGreaterThan(0);
    expect(commits.at(-1)?.loading).toBe(false);
    if (expectVisible) {
      expect(commits.some((commit) => !commit.loading && !commit.olderVisible)).toBe(false);
      expect(commits.at(-1)?.olderVisible).toBe(true);
    }
    if (error) {
      expect(container.querySelector('.thread-history-status[data-state="error"]')).toBeInTheDocument();
      expect(container.querySelector(".thread-history-slot")).toBeInTheDocument();
    } else {
      expect(container.querySelector(".thread-history-slot")).not.toBeInTheDocument();
    }
  });

  it("prepends earlier history while preserving the active answer cursor", async () => {
    const client = makeClient();
    const chatId = "running-paged-history";
    const turnId = "current-turn";
    client._emitChat(chatId, {
      event: "goal_status", chat_id: chatId, status: "running",
      started_at: 1_700, turn_id: turnId,
    });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (!url.includes(`websocket%3A${chatId}/webui-thread`)) {
        return { ok: false, status: 404, json: async () => ({}) };
      }
      if (url.includes("before=")) {
        return httpJson(canonicalThreadPayload({
          schemaVersion: 3,
          messages: [
            { id: "older-user", role: "user", content: "older question", turnId: "older-turn", createdAt: 1 },
            { id: "older-answer", role: "assistant", content: "older answer", turnId: "older-turn", createdAt: 2 },
          ],
          has_pending_tool_calls: false,
          completed_turn_ids: ["older-turn"],
          page: { before_cursor: null, has_more_before: false, user_message_offset: 0 },
        }));
      }
      return httpJson({
        ...transcriptFromSimpleMessages([{ role: "user", content: "current question", turnId }]),
        has_pending_tool_calls: true,
        active_turn_id: turnId,
        completed_turn_ids: [],
        page: { before_cursor: "older-page", has_more_before: true, user_message_offset: 1 },
      });
    }));
    const { container } = render(wrap(client, <ThreadShell
      session={session(chatId)} title="Running paged history"
      onToggleSidebar={() => {}}
    />));
    await screen.findByText("current question");
    act(() => client._emitChat(chatId, {
      event: "delta", chat_id: chatId, turn_id: turnId, text: "live answer",
    }));
    await screen.findByText("live answer");

    fireEvent.wheel(container.querySelector(".thread-message-viewport")!, { deltaY: -100 });
    const older = await screen.findByText("older answer");
    const current = screen.getByText("current question");
    expect(older.compareDocumentPosition(current) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText("live answer")).toBeInTheDocument();
    expect(client.reconcileCanonicalCompletion).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Stop response" })).toBeInTheDocument();

    act(() => client._emitChat(chatId, {
      event: "delta", chat_id: chatId, turn_id: turnId, text: " continued",
    }));
    await screen.findByText("live answer continued");
    expect(screen.getAllByText("older answer")).toHaveLength(1);
  });

  it("converges after reconnecting before the first assistant delta", async () => {
    const client = makeClient();
    let historyCalls = 0;
    const turnId = "turn-resume-before-delta";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("websocket%3Abefore-delta-chat/webui-thread")) {
          historyCalls += 1;
          const transcript = streamedThreadPayload("before-delta-chat",
            historyCalls === 1
              ? [{ role: "user", content: "question", turnId }]
              : [
                  { role: "user", content: "question", turnId },
                  {
                    role: "assistant", turnId, streamId: "before-delta-answer",
                    content: historyCalls === 2 ? "missed prefix" : "missed prefix resumed suffix",
                    endSeq: historyCalls === 2 ? 3 : 5,
                    mergeNext: historyCalls === 2,
                  },
                ],
            historyCalls < 3 ? [] : [turnId],
          );
          return httpJson({
            ...transcript,
            has_pending_tool_calls: historyCalls < 3,
            active_turn_id: historyCalls < 3 ? turnId : null,
          });
        }
        return {
          ok: false,
          status: 404,
          json: async () => ({}),
        };
      }),
    );

    render(
      wrap(
        client,
        <ThreadShell
          session={session("before-delta-chat")}
          title="Before delta chat"
          onToggleSidebar={() => {}}
        />,
      ),
    );

    await waitFor(() => expect(screen.getByText("question")).toBeInTheDocument());
    act(() => {
      client._emitChat("before-delta-chat", {
        event: "goal_status",
        chat_id: "before-delta-chat",
        status: "running",
        started_at: 1_700,
        turn_id: turnId,
      });
    });
    const input = screen.getByRole("textbox", { name: "Message input" });
    fireEvent.change(input, { target: { value: "queued guidance" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(client.sendMessage).not.toHaveBeenCalled();

    act(() => client._emitStatus("reconnecting"));
    act(() => client._emitStatus("open"));
    await waitFor(() => expect(historyCalls).toBe(2));
    await screen.findByText("missed prefix");
    expect(screen.getByRole("button", { name: "Stop response" })).toBeInTheDocument();
    expect(client.sendMessage).not.toHaveBeenCalled();

    act(() => {
      client._emitChat("before-delta-chat", {
        event: "delta",
        chat_id: "before-delta-chat",
        text: " resumed suffix",
        turn_id: turnId, turn_seq: 4, stream_id: "before-delta-answer",
      });
    });
    await screen.findByText("missed prefix resumed suffix");
    expect(screen.queryByText("missed prefix")).not.toBeInTheDocument();
    expect(screen.queryByText("resumed suffix")).not.toBeInTheDocument();
    expect(client.sendMessage).not.toHaveBeenCalled();

    act(() => client._emitStatus("reconnecting"));
    act(() => client._emitStatus("open"));
    await waitFor(() => expect(historyCalls).toBe(3));
    await waitFor(() =>
      expect(screen.getByText("missed prefix resumed suffix")).toBeInTheDocument(),
    );
    expect(screen.queryByText("resumed suffix")).not.toBeInTheDocument();
    await waitFor(() => expectSendMessageWithTurn(
      client,
      "before-delta-chat",
      "queued guidance",
    ));
  });

  it("keeps the live answer cursor when a resumed turn is still running", async () => {
    const client = makeClient();
    let historyCalls = 0;
    const turnId = "turn-active-resume";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("websocket%3Aactive-resume-chat/webui-thread")) {
          historyCalls += 1;
          const transcript = streamedThreadPayload("active-resume-chat",
            historyCalls === 1
              ? [{ role: "user", content: "question", turnId }]
              : [
                  { role: "user", content: "question", turnId },
                  {
                    role: "assistant", turnId, streamId: "active-resume-answer",
                    content: historyCalls === 2 ? "partial answer missed" : "partial answer missed resumed",
                    endSeq: historyCalls === 2 ? 4 : 6,
                    mergeNext: historyCalls === 2,
                  },
                ],
            historyCalls < 3 ? [] : [turnId],
          );
          return httpJson({
            ...transcript,
            has_pending_tool_calls: historyCalls < 3,
            active_turn_id: historyCalls < 3 ? turnId : null,
          });
        }
        return {
          ok: false,
          status: 404,
          json: async () => ({}),
        };
      }),
    );

    render(
      wrap(
        client,
        <ThreadShell
          session={session("active-resume-chat")}
          title="Active resume chat"
          onToggleSidebar={() => {}}
        />,
      ),
    );

    await waitFor(() => expect(screen.getByText("question")).toBeInTheDocument());
    act(() => {
      client._emitChat("active-resume-chat", {
        event: "goal_status",
        chat_id: "active-resume-chat",
        status: "running",
        started_at: 1_700,
        turn_id: turnId,
      });
      client._emitChat("active-resume-chat", {
        event: "delta",
        chat_id: "active-resume-chat",
        text: "partial answer",
        turn_id: turnId, turn_seq: 2, stream_id: "active-resume-answer",
      });
    });
    await waitFor(() => expect(screen.getByText("partial answer")).toBeInTheDocument());
    const input = screen.getByRole("textbox", { name: "Message input" });
    fireEvent.change(input, { target: { value: "queued guidance" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByText("queued guidance")).toBeInTheDocument();
    expect(client.sendMessage).not.toHaveBeenCalled();

    act(() => client._emitStatus("reconnecting"));
    expect(client.sendMessage).not.toHaveBeenCalled();
    act(() => client._emitStatus("open"));
    await waitFor(() => expect(historyCalls).toBe(2));
    expect(client.sendMessage).not.toHaveBeenCalled();

    act(() => {
      client._emitChat("active-resume-chat", {
        event: "delta",
        chat_id: "active-resume-chat",
        text: " resumed",
        turn_id: turnId, turn_seq: 5, stream_id: "active-resume-answer",
      });
    });

    await waitFor(() => expect(screen.getByText("partial answer resumed")).toBeInTheDocument());
    expect(screen.queryByText(" resumed")).not.toBeInTheDocument();
    expect(client.sendMessage).not.toHaveBeenCalled();

    act(() => client._emitStatus("reconnecting"));
    expect(client.sendMessage).not.toHaveBeenCalled();
    act(() => client._emitStatus("open"));

    await waitFor(() => expect(historyCalls).toBe(3));
    await waitFor(() =>
      expect(screen.getByText("partial answer missed resumed")).toBeInTheDocument(),
    );
    expect(screen.queryByText("partial answer resumed")).not.toBeInTheDocument();
    await waitFor(() => expectSendMessageWithTurn(
      client,
      "active-resume-chat",
      "queued guidance",
    ));
  });

  it("keeps active-run timing attached to the original turn after guidance", async () => {
    const client = makeClient();
    const turnId = "turn-active-timing";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes("websocket%3Atiming-chat/webui-thread")) {
          return httpJson(transcriptFromSimpleMessages([{
            role: "user",
            content: "research this",
            turnId,
          }]));
        }
        return { ok: false, status: 404, json: async () => ({}) };
      }),
    );

    render(
      wrap(
        client,
        <ThreadShell
          session={session("timing-chat")}
          title="Timing chat"
          onToggleSidebar={() => {}}
        />,
      ),
    );

    await waitFor(() => expect(screen.getByText("research this")).toBeInTheDocument());
    act(() => {
      client._emitChat("timing-chat", {
        event: "goal_status",
        chat_id: "timing-chat",
        status: "running",
        started_at: Date.now() / 1000 - 215,
        turn_id: turnId,
      });
      client._emitChat("timing-chat", {
        event: "message",
        chat_id: "timing-chat",
        kind: "progress",
        text: "web_search()",
        turn_id: turnId,
      });
      client._emitChat("timing-chat", {
        event: "message",
        chat_id: "timing-chat",
        text: "Continuing the search.",
        latency_ms: 1_000,
        turn_id: turnId,
      });
    });

    await waitFor(() => expect(screen.getByText("Continuing the search.")).toBeInTheDocument());
    const input = screen.getByRole("textbox", { name: "Message input" });
    fireEvent.change(input, { target: { value: "How is it going?" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(screen.getByText("How is it going?")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /^Working for / })).toBeInTheDocument();
    expect(screen.queryByText("Worked for 1s")).not.toBeInTheDocument();
    expect(screen.queryByRole("status", { name: /^Thinking for / })).not.toBeInTheDocument();
  });

  it("refreshes the current thread when the page returns to the foreground", async () => {
    const client = makeClient();
    let historyCalls = 0;
    const turnId = "turn-visible-chat";
    const visibilityDescriptor = Object.getOwnPropertyDescriptor(document, "visibilityState");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("websocket%3Avisible-chat/webui-thread")) {
          historyCalls += 1;
          return httpJson({
            ...transcriptFromSimpleMessages(
              historyCalls === 1
                ? [{ role: "user", content: "question", turnId }]
                : [
                    { role: "user", content: "question", turnId },
                    {
                      role: "assistant",
                      content: "answer completed in background",
                      turnId,
                    },
                  ],
            ),
            has_pending_tool_calls: historyCalls === 1,
            completed_turn_ids: historyCalls === 1 ? [] : [turnId],
          });
        }
        return {
          ok: false,
          status: 404,
          json: async () => ({}),
        };
      }),
    );

    try {
      render(
        wrap(
          client,
          <ThreadShell
            session={session("visible-chat")}
            title="Visible chat"
            onToggleSidebar={() => {}}
          />,
        ),
      );
      await waitFor(() => expect(screen.getByText("question")).toBeInTheDocument());
      expect(historyCalls).toBe(1);
      act(() => {
        client._emitChat("visible-chat", {
          event: "goal_status",
          chat_id: "visible-chat",
          status: "running",
          started_at: 6_000,
          turn_id: turnId,
        });
      });

      act(() => {
        setDocumentVisibility("hidden");
      });
      expect(historyCalls).toBe(1);

      await act(async () => {
        setDocumentVisibility("visible");
        await Promise.resolve();
      });

      await waitFor(() => expect(historyCalls).toBe(2));
      await waitFor(() =>
        expect(screen.getByText("answer completed in background")).toBeInTheDocument(),
      );
    } finally {
      restoreDocumentVisibility(visibilityDescriptor);
    }
  });

  it("does not refresh an idle thread for visibility notifications", async () => {
    const client = makeClient();
    let historyCalls = 0;
    const visibilityDescriptor = Object.getOwnPropertyDescriptor(document, "visibilityState");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes("websocket%3Aidle-visible-chat/webui-thread")) {
          historyCalls += 1;
          return httpJson(transcriptFromSimpleMessages([
            { role: "assistant", content: "settled answer" },
          ]));
        }
        return {
          ok: false,
          status: 404,
          json: async () => ({}),
        };
      }),
    );

    try {
      render(
        wrap(
          client,
          <ThreadShell
            session={session("idle-visible-chat")}
            title="Idle visible chat"
            onToggleSidebar={() => {}}
          />,
        ),
      );
      await waitFor(() => expect(screen.getByText("settled answer")).toBeInTheDocument());

      act(() => document.dispatchEvent(new Event("visibilitychange")));
      act(() => {
        setDocumentVisibility("hidden");
      });
      await act(async () => {
        setDocumentVisibility("visible");
        await Promise.resolve();
      });

      expect(historyCalls).toBe(1);
    } finally {
      restoreDocumentVisibility(visibilityDescriptor);
    }
  });

  it("retries a failed hydration when the page returns to the foreground", async () => {
    const client = makeClient();
    let historyCalls = 0;
    const visibilityDescriptor = Object.getOwnPropertyDescriptor(document, "visibilityState");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes("websocket%3Aretry-visible-chat/webui-thread")) {
          historyCalls += 1;
          if (historyCalls === 1) {
            return {
              ok: false,
              status: 500,
              json: async () => ({}),
            };
          }
          return httpJson(transcriptFromSimpleMessages([
            { role: "assistant", content: "recovered answer" },
          ]));
        }
        return {
          ok: false,
          status: 404,
          json: async () => ({}),
        };
      }),
    );

    try {
      render(
        wrap(
          client,
          <ThreadShell
            session={session("retry-visible-chat")}
            title="Retry visible chat"
            onToggleSidebar={() => {}}
          />,
        ),
      );
      await waitFor(() => expect(historyCalls).toBe(1));

      act(() => {
        setDocumentVisibility("hidden");
      });
      await act(async () => {
        setDocumentVisibility("visible");
        await Promise.resolve();
      });

      await waitFor(() => expect(historyCalls).toBe(2));
      expect(await screen.findByText("recovered answer")).toBeInTheDocument();
    } finally {
      restoreDocumentVisibility(visibilityDescriptor);
    }
  });

  it("does not refetch thread history on turn_end", async () => {
    const client = makeClient();
    let historyCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("websocket%3Achat-a/webui-thread")) {
          historyCalls += 1;
          return httpJson(
            transcriptFromSimpleMessages(
              historyCalls === 1
                ? [{ role: "user", content: "question" }]
                : [
                    { role: "user", content: "question" },
                    { role: "assistant", content: "canonical markdown answer" },
                  ],
            ),
          );
        }
        return {
          ok: false,
          status: 404,
          json: async () => ({}),
        };
      }),
    );

    render(
      wrap(
        client,
        <ThreadShell
          session={session("chat-a")}
          title="Chat chat-a"
          onToggleSidebar={() => {}}
        />,
      ),
    );

    await waitFor(() => expect(screen.getByText("question")).toBeInTheDocument());
    await act(async () => {
      client._emitChat("chat-a", {
        event: "delta",
        chat_id: "chat-a",
        text: "live half-parsed | markdown",
      });
      client._emitChat("chat-a", {
        event: "turn_end",
        chat_id: "chat-a",
      });
    });

    await waitFor(() => expect(screen.getByText("live half-parsed | markdown")).toBeInTheDocument());
    expect(screen.queryByText("canonical markdown answer")).not.toBeInTheDocument();
    expect(historyCalls).toBe(1);
  });

  it("keeps rendered media mounted for metadata-only session updates", async () => {
    const client = makeClient();
    let historyCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("websocket%3Achat-a/webui-thread")) {
          historyCalls += 1;
          const thread = transcriptFromSimpleMessages([
            { role: "user", content: "question" },
            { role: "assistant", content: "answer" },
          ]);
          const answer = thread.events.find(
            (event) => event.event === "message" && event.text === "answer",
          );
          if (answer?.event === "message") answer.media_urls = [{
            url: "/api/media/stable/image",
            name: "answer.png",
          }];
          return httpJson(thread);
        }
        return {
          ok: false,
          status: 404,
          json: async () => ({}),
        };
      }),
    );

    render(
      wrap(
        client,
        <ThreadShell
          session={session("chat-a")}
          title="Chat chat-a"
          onToggleSidebar={() => {}}
        />,
      ),
    );

    await waitFor(() => expect(screen.getByText("answer")).toBeInTheDocument());
    const image = screen.getByRole("img", { name: "answer.png" });
    expect(historyCalls).toBe(1);

    await act(async () => {
      client._emitSessionUpdate("chat-a", "metadata");
    });

    expect(historyCalls).toBe(1);
    expect(screen.getByRole("img", { name: "answer.png" })).toBe(image);
  });

  it("keeps rendered media mounted when the auth token rotates", async () => {
    const client = makeClient();
    let historyCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes("websocket%3Atoken-media/webui-thread")) {
          historyCalls += 1;
          const thread = transcriptFromSimpleMessages([
            { role: "user", content: "question" },
            { role: "assistant", content: "answer" },
          ]);
          const answer = thread.events.find(
            (event) => event.event === "message" && event.text === "answer",
          );
          if (answer?.event === "message") answer.media_urls = [{
            url: "/api/media/stable/token-image",
            name: "token-answer.png",
          }];
          return httpJson(thread);
        }
        return {
          ok: false,
          status: 404,
          json: async () => ({}),
        };
      }),
    );
    const view = (token: string) => wrap(
      client,
      <ThreadShell
        session={session("token-media")}
        title="Token media"
        onToggleSidebar={() => {}}
      />,
      null,
      token,
    );
    const { rerender } = render(view("tok-old"));

    await waitFor(() => expect(screen.getByText("answer")).toBeInTheDocument());
    const image = screen.getByRole("img", { name: "token-answer.png" });

    rerender(view("tok-new"));
    await act(async () => Promise.resolve());

    expect(historyCalls).toBe(1);
    expect(screen.getByRole("img", { name: "token-answer.png" })).toBe(image);
  });

  it("does not scroll again when canonical history refreshes after a session update", async () => {
    const client = makeClient();
    const jumpTo = vi.spyOn(ThreadCameraController.prototype, "jumpTo");
    let historyCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("websocket%3Achat-a/webui-thread")) {
          historyCalls += 1;
          return httpJson(
            transcriptFromSimpleMessages(
              historyCalls === 1
                ? [{ role: "user", content: "question" }]
                : [
                    { role: "user", content: "question" },
                    { role: "assistant", content: "canonical answer" },
                  ],
            ),
          );
        }
        return {
          ok: false,
          status: 404,
          json: async () => ({}),
        };
      }),
    );

    try {
      render(
        wrap(
          client,
          <ThreadShell
            session={session("chat-a")}
            title="Chat chat-a"
            onToggleSidebar={() => {}}
          />,
        ),
      );

      await waitFor(() => expect(screen.getByText("question")).toBeInTheDocument());
      await waitFor(() => expect(jumpTo).toHaveBeenCalled());
      await act(async () => {
        for (let i = 0; i < 8; i += 1) {
          await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
        }
      });
      jumpTo.mockClear();

      await act(async () => {
        client._emitSessionUpdate("chat-a");
      });

      await waitFor(() => expect(historyCalls).toBe(2));
      await waitFor(() => expect(screen.getByText("canonical answer")).toBeInTheDocument());
      expect(jumpTo).not.toHaveBeenCalled();
    } finally {
      jumpTo.mockRestore();
    }
  });

  it("keeps an active completion follow alive while canonical history refreshes", async () => {
    const resizeObserver = stubThreadResizeObserver();
    const client = makeClient();
    let historyCalls = 0;
    const pendingRefresh = new Promise<ReturnType<typeof httpJson>>(() => {});
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("websocket%3Achat-follow/webui-thread")) {
          historyCalls += 1;
          if (historyCalls > 1) return pendingRefresh;
          return httpJson(
            transcriptFromSimpleMessages([
              { role: "user", content: "old question" },
              { role: "assistant", content: "old answer" },
            ]),
          );
        }
        return {
          ok: false,
          status: 404,
          json: async () => ({}),
        };
      }),
    );

    const requestFrame = vi.spyOn(window, "requestAnimationFrame");
    const cancelFrame = vi.spyOn(window, "cancelAnimationFrame");
    try {
      const { container } = render(
        wrap(
          client,
          <ThreadShell
            session={session("chat-follow")}
            title="Chat follow"
            onToggleSidebar={() => {}}
          />,
        ),
      );

      await waitFor(() => expect(screen.getByText("old answer")).toBeInTheDocument());
      const scroller = container.querySelector(".thread-viewport-scrollbar") as HTMLElement;
      Object.defineProperties(scroller, {
        scrollHeight: { configurable: true, value: 2_000 },
        clientHeight: { configurable: true, value: 500 },
        scrollTop: { configurable: true, writable: true, value: 1_500 },
        scrollTo: {
          configurable: true,
          value: ({ top }: ScrollToOptions) => {
            if (typeof top === "number") scroller.scrollTop = top;
          },
        },
      });

      fireEvent.change(screen.getByLabelText("Message input"), {
        target: { value: "new question" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Send message" }));
      await waitFor(() => expect(screen.getByText("new question")).toBeInTheDocument());

      await act(async () => {
        client._emitChat("chat-follow", {
          event: "delta",
          chat_id: "chat-follow",
          text: "new answer",
        });
      });
      await waitFor(() => expect(screen.getByText("new answer")).toBeInTheDocument());

      requestFrame.mockImplementation(() => 9_001);
      cancelFrame.mockImplementation(() => undefined);
      cancelFrame.mockClear();
      Object.defineProperty(scroller, "scrollHeight", {
        configurable: true,
        value: 2_120,
      });
      const messageContent = screen.getByTestId("thread-message-region").firstElementChild;
      const contentObserver = resizeObserver.observers.find(
        (observer) => observer.elements.includes(messageContent!),
      );
      expect(contentObserver).toBeDefined();

      act(() => {
        contentObserver!.callback([], contentObserver as unknown as ResizeObserver);
      });
      expect(requestFrame).toHaveBeenCalled();
      cancelFrame.mockClear();

      act(() => {
        client._emitSessionUpdate("chat-follow", "thread");
      });

      expect(cancelFrame).not.toHaveBeenCalledWith(9_001);
      expect(historyCalls).toBe(2);
    } finally {
      requestFrame.mockRestore();
      cancelFrame.mockRestore();
      resizeObserver.restore();
    }
  });

  it("scrolls to the bottom after loading a session from the blank new-chat page", async () => {
    const client = makeClient();
    const scrollTo = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("websocket%3Achat-a/webui-thread")) {
          return httpJson(
            transcriptFromSimpleMessages([
              { role: "user", content: "question" },
              { role: "assistant", content: "loaded answer" },
            ]),
          );
        }
        return {
          ok: false,
          status: 404,
          json: async () => ({}),
        };
      }),
    );

    const { container, rerender } = render(
      wrap(
        client,
        <ThreadShell
          session={null}
          title="nanobot"
          onToggleSidebar={() => {}}
        />,
      ),
    );

    expect(screen.getByText(HERO_GREETING_PATTERN)).toBeInTheDocument();
    const scroller = container.querySelector(".thread-viewport-scrollbar") as HTMLElement;
    Object.defineProperties(scroller, {
      scrollHeight: { configurable: true, value: 2400 },
      clientHeight: { configurable: true, value: 600 },
      scrollTop: { configurable: true, writable: true, value: 0 },
      scrollTo: { configurable: true, value: scrollTo },
    });
    scrollTo.mockClear();

    await act(async () => {
      rerender(
        wrap(
          client,
          <ThreadShell
            session={session("chat-a")}
            title="Chat chat-a"
            onToggleSidebar={() => {}}
          />,
        ),
      );
    });

    await waitFor(() => expect(screen.getByText("loaded answer")).toBeInTheDocument());
    await waitFor(() => expect(scroller.scrollTop).toBe(1800));
  });

  it("opens slash commands on the blank welcome page", async () => {
    const client = makeClient();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/api/commands")) {
          return httpJson({
            commands: [
              {
                command: "/history",
                title: "Show conversation history",
                description: "Print the last N persisted messages.",
                icon: "history",
                arg_hint: "[n]",
                lifecycle: "side_channel",
                accepts_args: true,
              },
            ],
          });
        }
        return {
          ok: false,
          status: 404,
          json: async () => ({}),
        };
      }),
    );

    render(
      wrap(
        client,
        <ThreadShell
          session={null}
          title="nanobot"
          onToggleSidebar={() => {}}
        />,
      ),
    );

    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      "/api/commands",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    ));

    fireEvent.change(screen.getByLabelText("Message input"), {
      target: { value: "/" },
    });

    expect(screen.getByRole("listbox", { name: "Slash commands" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /\/history/i })).toBeInTheDocument();
  });

  it("surfaces a dismissible banner for an uncorrelated message_too_big error", async () => {
    const client = makeClient();

    render(
      wrap(
        client,
        <ThreadShell
          session={session("chat-a")}
          title="Chat chat-a"
          onToggleSidebar={() => {}}
        />,
      ),
    );

    // No banner yet: only appears once the client emits a matching error.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    await act(async () => {});
    await act(async () => {
      client._emitError({ kind: "message_too_big" });
    });

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent("Message too large");

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));

    await waitFor(() => {
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
  });

  it.each([false, true])("keeps one terminal model failure visible until the next user action (recovery: %s)", async (recoverable) => {
    const client = makeClient();
    await act(async () => {
      await i18n.changeLanguage("zh-CN");
    });

    render(
      wrap(
        client,
        <ThreadShell
          session={session("chat-model-failure")}
          title="Chat model failure"
          onToggleSidebar={() => {}}
        />,
      ),
    );

    await act(async () => {});
    act(() => {
      client._emitChat("chat-model-failure", {
        event: "turn_end",
        chat_id: "chat-model-failure",
        turn_id: "turn-model-failure",
        outcome: "failed",
        failure_kind: "model",
        failure_error_kind: "connection",
        failure_attempts: 4,
        failure_message: "Unlocalized server failure",
      });
    });

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent("无法连接模型提供商");
    expect(banner).toHaveTextContent(
      "已尝试 4 次，仍未成功。可稍后继续或切换模型。",
    );
    expect(banner).not.toHaveTextContent("Unlocalized server failure");
    if (recoverable) {
      act(() => {
        client._emitChat("chat-model-failure", {
          event: "recovery_state",
          chat_id: "chat-model-failure",
          recovery_id: "model-recovery",
          status: "awaiting_user",
          reason: "model_request_failed",
          failure_error_kind: "connection",
        });
      });
      expect(screen.getAllByRole("alert")).toHaveLength(1);
      expect(screen.getByRole("alert")).toHaveTextContent("无法连接模型提供商");
      expect(screen.getByRole("button", { name: "继续" })).toBeEnabled();
    }

    fireEvent.change(screen.getByLabelText("消息输入框"), {
      target: { value: "try again" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送消息" }));
    if (recoverable) {
      act(() => {
        client._emitChat("chat-model-failure", {
          event: "recovery_state",
          chat_id: "chat-model-failure",
          recovery_id: "model-recovery",
          status: "recovered",
          reason: "superseded",
        });
      });
    }

    await waitFor(() => {
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "停止响应" })).toBeInTheDocument();
    const nextTurnId = client.getRunTurnId("chat-model-failure")!;
    act(() => {
      client._emitChat("chat-model-failure", {
        event: "goal_status", chat_id: "chat-model-failure", turn_id: nextTurnId,
        status: "running", started_at: 1_700_000_000,
      });
      client._emitChat("chat-model-failure", {
        event: "delta", chat_id: "chat-model-failure", turn_id: nextTurnId,
        text: "New request is running",
      });
    });
    expect(await screen.findByText("New request is running")).toBeVisible();
    expect(client.getRunState("chat-model-failure")).toMatchObject({ active: true, startedAt: 1_700_000_000 });
    act(() => client._emitChat("chat-model-failure", {
      event: "turn_end", chat_id: "chat-model-failure", turn_id: nextTurnId,
    }));
    expect(screen.queryByRole("button", { name: "停止响应" })).not.toBeInTheDocument();
  });

  it("moves a correlated delivery error from the banner into the failed message tooltip", async () => {
    const client = makeClient();

    render(
      wrap(
        client,
        <ThreadShell
          session={session("chat-inline-error")}
          title="Chat inline error"
          onToggleSidebar={() => {}}
        />,
      ),
    );

    fireEvent.change(screen.getByLabelText("Message input"), {
      target: { value: "oversized payload" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(client.sendMessage).toHaveBeenCalledTimes(1));
    const turnId = client.sendMessage.mock.calls[0][3]?.turnId;
    expect(turnId).toEqual(expect.any(String));

    await act(async () => {
      client._emitError({
        kind: "message_too_big",
        chatId: "chat-inline-error",
        turnId,
      });
    });

    expect(screen.queryByRole("button", { name: "Dismiss" })).not.toBeInTheDocument();
    const status = screen.getByRole("button", {
      name: "Not sent: Message too large",
    });
    expect(screen.getByRole("alert")).toHaveClass("sr-only");
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    fireEvent.focus(status);

    expect(await screen.findByRole("tooltip")).toHaveTextContent(
      "The server rejected your last message because it exceeded the size limit.",
    );
  });

  it("clears the stream error banner when the user switches to another chat", async () => {
    const client = makeClient();

    const { rerender } = render(
      wrap(
        client,
        <ThreadShell
          session={session("chat-a")}
          title="Chat chat-a"
          onToggleSidebar={() => {}}
        />,
      ),
    );

    await act(async () => {});
    await act(async () => {
      client._emitError({ kind: "message_too_big" });
    });
    expect(await screen.findByRole("alert")).toBeInTheDocument();

    // Switch to a different chat. The banner was about the *previous* send
    // in chat-a; it must not leak into chat-b's view.
    await act(async () => {
      rerender(
        wrap(
          client,
          <ThreadShell
            session={session("chat-b")}
            title="Chat chat-b"
            onToggleSidebar={() => {}}
          />,
        ),
      );
    });

    await waitFor(() => {
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
  });

  it("clears the previous thread immediately while the next session loads", async () => {
    const client = makeClient();
    let resolveChatB:
      | ((value: { ok: boolean; status: number; json: () => Promise<unknown> }) => void)
      | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("websocket%3Achat-a/webui-thread")) {
          return Promise.resolve(
            httpJson(
              transcriptFromSimpleMessages([{ role: "assistant", content: "from chat a" }]),
            ),
          );
        }
        if (url.includes("websocket%3Achat-b/webui-thread")) {
          return new Promise((resolve) => {
            resolveChatB = resolve;
          });
        }
        return Promise.resolve({
          ok: false,
          status: 404,
          json: async () => ({}),
        });
      }),
    );

    const { rerender } = render(
      wrap(
        client,
        <ThreadShell
          session={session("chat-a")}
          title="Chat chat-a"
          onToggleSidebar={() => {}}
        />,
      ),
    );

    await waitFor(() => expect(screen.getByText("from chat a")).toBeInTheDocument());

    await act(async () => {
      rerender(
        wrap(
          client,
          <ThreadShell
            session={session("chat-b")}
            title="Chat chat-b"
            onToggleSidebar={() => {}}
          />,
        ),
      );
    });

    expect(screen.queryByText("from chat a")).not.toBeInTheDocument();
    const loading = screen.getByRole("status", { name: "Loading conversation…" });
    expect(loading).toHaveAttribute("aria-busy", "true");
    expect(loading.querySelector("[aria-hidden]")).not.toBeEmptyDOMElement();
    expect(screen.getByRole("textbox", { name: "Message input" })).toBeEnabled();
    const header = screen.getByTestId("thread-header");
    const composer = screen.getByTestId("thread-composer-motion");
    expect(composer.closest("[data-layout]")).toHaveAttribute("data-layout", "thread");

    await act(async () => {
      resolveChatB?.(
        httpJson(transcriptFromSimpleMessages([{ role: "assistant", content: "from chat b" }])),
      );
    });

    await waitFor(() => expect(screen.getByText("from chat b")).toBeInTheDocument());
    expect(screen.queryByText("from chat a")).not.toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Loading conversation…" })).not.toBeInTheDocument();
    expect(screen.getByTestId("thread-header")).toBe(header);
    expect(screen.getByTestId("thread-composer-motion")).toBe(composer);
  });

  it.each([false, true])("replaces the initial history skeleton with welcome when no visible history remains (systemOnly=%s)", async (systemOnly) => {
    let resolveHistory!: (response: Response) => void;
    vi.mocked(fetch).mockImplementation((input) => String(input).includes("/webui-thread")
      ? new Promise<Response>((resolve) => { resolveHistory = resolve; })
      : Promise.resolve(new Response(null, { status: 404 })));
    render(wrap(makeClient(), <ThreadShell session={session("empty-topic")} title="Empty topic"
      onToggleSidebar={() => {}} />));

    expect(screen.getByRole("status", { name: "Loading conversation…" })).toHaveAttribute("aria-busy", "true");
    await act(async () => {
      resolveHistory(httpJson(transcriptFromSimpleMessages(systemOnly
        ? [{ role: "assistant", content: "Model selected", turnId: "webui-system:model-preset" }]
        : [])));
    });

    expect(await screen.findByText(HERO_GREETING_PATTERN)).toBeVisible();
    expect(screen.queryByRole("status", { name: "Loading conversation…" })).not.toBeInTheDocument();
    expect(screen.getByTestId("thread-welcome-layout")).toHaveAttribute("data-layout", "hero");
  });

  it("keeps cached messages visible while the first history revalidation is pending", async () => {
    webuiThreadCache.set("websocket:cached-topic", transcriptFromSimpleMessages([
      { role: "assistant", content: "Cached answer" },
    ]));
    vi.mocked(fetch).mockImplementation((input) => String(input).includes("/webui-thread")
      ? new Promise<Response>(() => {})
      : Promise.resolve(new Response(null, { status: 404 })));
    render(wrap(makeClient(), <ThreadShell session={session("cached-topic")} title="Cached topic"
      onToggleSidebar={() => {}} />));

    expect(await screen.findByText("Cached answer")).toBeVisible();
    expect(screen.queryByRole("status", { name: "Loading conversation…" })).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Message input" })).toBeEnabled();
  });

  it("loads mention catalogs only on demand and ignores window focus", async () => {
    const originalFetch = vi.mocked(fetch).getMockImplementation()!;
    vi.mocked(fetch).mockImplementation((input, init) => {
      if (String(input).includes("cli-apps")) return Promise.resolve(httpJson({ apps: [], installed_count: 0 }));
      if (String(input).includes("mcp-presets")) return Promise.resolve(httpJson({ presets: [], installed_count: 0 }));
      return originalFetch(input, init);
    });
    render(wrap(makeClient(), <ThreadShell
      session={session("lazy-mentions")}
      title="Lazy mentions"
      onToggleSidebar={() => {}}
    />));
    const input = await screen.findByLabelText("Message input");
    const catalogCalls = () => vi.mocked(fetch).mock.calls.filter(([url]) =>
      /cli-apps|mcp-presets/.test(String(url)));
    fireEvent.change(input, { target: { value: "hello", selectionStart: 5 } });
    fireEvent(window, new Event("focus"));
    expect(catalogCalls()).toHaveLength(0);
    fireEvent.change(input, { target: { value: "@", selectionStart: 1 } });
    await waitFor(() => expect(catalogCalls()).toHaveLength(2));
    fireEvent(window, new Event("focus"));
    fireEvent.change(input, { target: { value: "@app", selectionStart: 4 } });
    fireEvent.change(input, { target: { value: "", selectionStart: 0 } });
    fireEvent.change(input, { target: { value: "@", selectionStart: 1 } });
    expect(catalogCalls()).toHaveLength(2);
  });

  it("retries a failed mention catalog when the user opens mentions again", async () => {
    vi.mocked(fetch).mockResolvedValue({ ok: false, status: 503, json: async () => ({}) } as Response);
    render(wrap(makeClient(), <ThreadShell
      session={session("retry-mentions")}
      title="Retry mentions"
      onToggleSidebar={() => {}}
    />));
    const input = await screen.findByLabelText("Message input");
    const catalogCalls = () => vi.mocked(fetch).mock.calls.filter(([url]) =>
      /cli-apps|mcp-presets/.test(String(url)));
    await act(async () => {
      fireEvent.change(input, { target: { value: "@", selectionStart: 1 } });
    });
    expect(catalogCalls()).toHaveLength(2);
    fireEvent.change(input, { target: { value: "", selectionStart: 0 } });
    await act(async () => {
      fireEvent.change(input, { target: { value: "@", selectionStart: 1 } });
    });
    expect(catalogCalls()).toHaveLength(4);
  });

  it("updates @ CLI app suggestions when settings broadcasts an install", async () => {
    const client = makeClient();
    render(wrap(
      client,
      <ThreadShell
        session={session("chat-cli-apps")}
        title="Chat chat-cli-apps"
        onToggleSidebar={() => {}}
      />,
    ));

    const input = await screen.findByLabelText("Message input");
    expect(screen.queryByRole("listbox", { name: "Mentions" })).not.toBeInTheDocument();

    const payload: CliAppsPayload = {
      apps: [{
        name: "gimp",
        display_name: "GIMP",
        category: "image",
        description: "Image editing",
        requires: "",
        source: "harness",
        entry_point: "cli-anything-gimp",
        install_supported: true,
        installed: true,
        available: true,
        status: "installed",
        logo_url: null,
        brand_color: "#5C5543",
        skill_installed: true,
      }],
      installed_count: 1,
      catalog_updated_at: "2026-04-18",
    };

    await act(async () => {
      window.dispatchEvent(new CustomEvent(CLI_APPS_CHANGED_EVENT, { detail: payload }));
    });
    fireEvent.change(input, { target: { value: "@", selectionStart: 1 } });

    expect(screen.getByRole("listbox", { name: "Mentions" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /@gimp/i })).toBeInTheDocument();
  });

  it("does not let an older catalog request overwrite a newer install event", async () => {
    const client = makeClient();
    let resolveCatalog!: (response: Response) => void;
    const pendingCatalog = new Promise<Response>((resolve) => {
      resolveCatalog = resolve;
    });
    vi.mocked(fetch).mockImplementation((input) => {
      if (String(input).includes("/api/settings/cli-apps?installed_only=1")) {
        return pendingCatalog;
      }
      return Promise.resolve({
        ok: false,
        status: 404,
        json: async () => ({}),
      } as Response);
    });
    render(wrap(
      client,
      <ThreadShell
        session={session("chat-cli-race")}
        title="Chat chat-cli-race"
        onToggleSidebar={() => {}}
      />,
    ));

    const input = await screen.findByLabelText("Message input");
    fireEvent.change(input, { target: { value: "@", selectionStart: 1 } });
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      "/api/settings/cli-apps?installed_only=1",
      expect.anything(),
    ));
    const payload: CliAppsPayload = {
      apps: [{
        name: "gimp",
        display_name: "GIMP",
        category: "image",
        description: "Image editing",
        requires: "",
        source: "harness",
        entry_point: "cli-anything-gimp",
        install_supported: true,
        installed: true,
        available: true,
        status: "installed",
        logo_url: null,
        brand_color: "#5C5543",
        skill_installed: true,
      }],
      installed_count: 1,
      catalog_updated_at: "2026-07-30",
    };
    await act(async () => {
      window.dispatchEvent(new CustomEvent(CLI_APPS_CHANGED_EVENT, { detail: payload }));
      resolveCatalog(httpJson({ apps: [], installed_count: 0 }));
      await pendingCatalog;
    });

    fireEvent.change(input, { target: { value: "@", selectionStart: 1 } });
    expect(screen.getByRole("option", { name: /@gimp/i })).toBeInTheDocument();
  });

  it("keeps installed app mentions available during transient catalog refresh failures", async () => {
    const client = makeClient();
    const payload: CliAppsPayload = {
      apps: [{
        name: "obsidian-agent-cli",
        display_name: "Obsidian",
        category: "productivity",
        description: "Obsidian automation",
        requires: "",
        source: "harness",
        entry_point: "cli-anything-obsidian",
        install_supported: true,
        installed: true,
        available: true,
        status: "installed",
        logo_url: null,
        brand_color: "#7C3AED",
        skill_installed: true,
      }],
      installed_count: 1,
      catalog_updated_at: "2026-07-14",
    };
    vi.mocked(fetch).mockImplementation(async (input) => {
      if (String(input).includes("/api/settings/cli-apps?installed_only=1")) {
        throw new Error("temporary catalog failure");
      }
      return {
        ok: false,
        status: 404,
        json: async () => ({}),
      } as Response;
    });

    render(wrap(
      client,
      <ThreadShell
        session={session("chat-cli-refresh")}
        title="Chat chat-cli-refresh"
        onToggleSidebar={() => {}}
      />,
    ));

    const input = await screen.findByLabelText("Message input");
    await act(async () => {
      window.dispatchEvent(new CustomEvent(CLI_APPS_CHANGED_EVENT, { detail: payload }));
    });
    const mention = "@obsidian-agent-cli";
    fireEvent.change(input, { target: { value: mention, selectionStart: mention.length } });
    expect(screen.getByRole("option", { name: /@obsidian-agent-cli/i })).toBeInTheDocument();

    await act(async () => {
      window.dispatchEvent(new Event("focus"));
      await Promise.resolve();
    });

    expect(screen.getByRole("option", { name: /@obsidian-agent-cli/i })).toBeInTheDocument();
    expect(screen.getByTestId("composer-cli-mention-obsidian-agent-cli")).toHaveTextContent(
      "@Obsidian",
    );
    expect(input).toHaveValue("@Obsidian");
  });

  it("offers sessions across projects in restricted mode", async () => {
    const client = makeClient();
    const currentScope = {
      project_path: "/projects/current",
      access_mode: "restricted" as const,
    };
    const sameProject = {
      ...session("same-project"),
      title: "Same project",
      workspaceScope: currentScope,
      handle: {
        id: "handle_11111111111111111111111111111111",
        name: "same-1111111111",
      },
    };
    const otherProject = {
      ...session("other-project"),
      title: "Other project",
      workspaceScope: {
        project_path: "/projects/other",
        access_mode: "restricted" as const,
      },
      handle: {
        id: "handle_22222222222222222222222222222222",
        name: "other-2222222222",
      },
    };

    render(wrap(
      client,
      <ThreadShell
        session={session("current")}
        sessions={[sameProject, otherProject]}
        title="Current"
        onToggleSidebar={() => {}}
        workspaceScope={currentScope}
      />,
    ));

    const input = await screen.findByLabelText("Message input");
    fireEvent.change(input, { target: { value: "@", selectionStart: 1 } });

    expect(screen.getByRole("option", { name: /Same project/i })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Other project/i })).toBeInTheDocument();
  });

  it("allows project selection before first input and locks it after acceptance without duplicating the sidebar label", async () => {
    const client = makeClient();
    const scope = { project_path: "/srv/alpha", project_name: "alpha", access_mode: "restricted" as const };
    const props = {
      title: "Project chat", onToggleSidebar: () => {}, workspaceScope: scope,
      workspaceDefaultScope: scope, workspaceControls: { can_change_project: true },
      onWorkspaceScopeChange: vi.fn(),
    };
    const { rerender } = render(wrap(client, <ThreadShell {...props} session={{ ...session("project-chat"), projectLocked: false }} />));
    expect(await screen.findByRole("button", { name: "Switch directory" })).toBeEnabled();
    expect(screen.getByTestId("thread-header")).not.toHaveTextContent("alpha");

    rerender(wrap(client, <ThreadShell {...props} session={{ ...session("project-chat"), projectLocked: true }} />));
    expect(screen.queryByRole("button", { name: "Switch directory" })).not.toBeInTheDocument();
    expect(screen.getByTestId("thread-header")).not.toHaveTextContent("alpha");
    expect(screen.getByRole("button", { name: "Workspace access mode: Default Permission" })).toBeEnabled();
  });

  it("keeps normal running controls when attaching to a resumed task", async () => {
    const client = makeClient();
    render(wrap(
      client,
      <ThreadShell
        session={session("resuming-chat")}
        title="Resuming chat"
        onToggleSidebar={() => {}}
      />,
    ));

    await screen.findByLabelText("Message input");
    act(() => {
      client._emitChat("resuming-chat", {
        event: "attached",
        chat_id: "resuming-chat",
        recovery_state: { recovery_id: "recovery-1", status: "resuming" },
      });
    });

    expect(screen.queryByText("Restoring interrupted task…")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stop response" }));
    expect(client.sendMessage).toHaveBeenCalledWith("resuming-chat", "/stop");
  });

  it.each(["awaiting_user", "failed", "recovered"] as const)("allows a new turn after a %s recovery state", async (status) => {
    const client = makeClient();
    render(wrap(
      client,
      <ThreadShell
        session={session("recovered-chat")}
        title="Recovered chat"
        onToggleSidebar={() => {}}
      />,
    ));

    const input = await screen.findByLabelText("Message input");
    act(() => {
      client._emitChat("recovered-chat", {
        event: "recovery_state",
        chat_id: "recovered-chat",
        recovery_id: "recovery-1",
        status,
      });
    });

    fireEvent.change(input, { target: { value: "start the next task" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(client.sendMessage).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Stop response" })).toBeInTheDocument();
  });

});
