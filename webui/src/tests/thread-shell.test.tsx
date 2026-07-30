import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { StrictMode, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { preloadMarkdownText } from "@/components/MarkdownText";
import { ThreadCameraController } from "@/components/thread/thread-camera";
import { ThreadShell } from "@/components/thread/ThreadShell";
import { CLI_APPS_CHANGED_EVENT } from "@/lib/cli-app-events";
import type { CanonicalRunSnapshot, StreamError } from "@/lib/nanobot-client";
import { ClientProvider } from "@/providers/ClientProvider";
import type { CliAppsPayload, ConnectionStatus, SettingsPayload, UIMessage } from "@/lib/types";

const HERO_GREETING_PATTERN =
  /What should we work on\?|Where should we start\?|What are we building today\?|What should we tackle together\?/;

function makeClient() {
  const errorHandlers = new Set<(err: StreamError) => void>();
  const statusHandlers = new Set<(status: ConnectionStatus) => void>();
  const chatHandlers = new Map<string, Set<(ev: import("@/lib/types").InboundEvent) => void>>();
  const runtimeModelHandlers = new Set<
    (modelName: string | null, modelPreset?: string | null) => void
  >();
  const sessionUpdateHandlers = new Set<(chatId: string, scope?: string) => void>();
  const runStartedAtByChatId = new Map<string, number>();
  const runGenerationByChatId = new Map<string, number>();
  const latestRunTurnIdByChatId = new Map<string, string>();
  const completedTurnIdsByChatId = new Map<string, Set<string>>();
  const goalStateByChatId = new Map<string, import("@/lib/types").GoalStateWsPayload>();
  let status: ConnectionStatus = "open";
  const advanceRunGeneration = (chatId: string, turnId?: string) => {
    runGenerationByChatId.set(chatId, (runGenerationByChatId.get(chatId) ?? 0) + 1);
    if (turnId) latestRunTurnIdByChatId.set(chatId, turnId);
    else latestRunTurnIdByChatId.delete(chatId);
  };
  const sendMessage = vi.fn((
    chatId: string,
    _content: string,
    _media?: unknown,
    options?: { turnId?: string; startsNewRun?: boolean },
  ) => {
    if (options?.turnId && options.startsNewRun !== false) {
      advanceRunGeneration(chatId, options.turnId);
    }
  });
  const canReconcileCanonicalCompletion = vi.fn((
    chatId: string,
    expectedRunGeneration: number,
    completedTurnIds: readonly string[],
    snapshot?: CanonicalRunSnapshot,
  ) => {
    const existingFences = completedTurnIdsByChatId.get(chatId);
    const prospectiveFences = new Set(completedTurnIds);
    const observedTurnIds = new Set(snapshot?.observedTurnIds ?? []);
    const isRepresented = (turnId: string) => (
      prospectiveFences.has(turnId)
      || existingFences?.has(turnId) === true
      || (
        snapshot?.hasPendingToolCalls === false
        && observedTurnIds.has(turnId)
      )
    );
    const currentGeneration = runGenerationByChatId.get(chatId) ?? 0;
    const latestTurnId = latestRunTurnIdByChatId.get(chatId);
    return (
      currentGeneration === expectedRunGeneration
      || (typeof latestTurnId === "string" && isRepresented(latestTurnId))
    );
  });
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
    const fences = completedTurnIdsByChatId.get(chatId) ?? new Set<string>();
    for (const turnId of completedTurnIds) fences.add(turnId);
    completedTurnIdsByChatId.set(chatId, fences);
    runStartedAtByChatId.delete(chatId);
    return true;
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
    onRuntimeModelUpdate: (
      handler: (modelName: string | null, modelPreset?: string | null) => void,
    ) => {
      runtimeModelHandlers.add(handler);
      return () => {
        runtimeModelHandlers.delete(handler);
      };
    },
    getRunStartedAt: (chatId: string) => runStartedAtByChatId.get(chatId) ?? null,
    hasUnsettledRun: () => false,
    getRunGeneration: (chatId: string) => runGenerationByChatId.get(chatId) ?? 0,
    canReconcileCanonicalCompletion,
    reconcileCanonicalCompletion,
    getGoalState: (chatId: string) => goalStateByChatId.get(chatId),
    onChat: (chatId: string, handler: (ev: import("@/lib/types").InboundEvent) => void) => {
      let handlers = chatHandlers.get(chatId);
      if (!handlers) {
        handlers = new Set();
        chatHandlers.set(chatId, handlers);
      }
      handlers.add(handler);
      return () => {
        handlers?.delete(handler);
      };
    },
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
      for (const h of errorHandlers) h(err);
    },
    _emitStatus(nextStatus: ConnectionStatus) {
      status = nextStatus;
      for (const h of statusHandlers) h(status);
    },
    _emitChat(chatId: string, ev: import("@/lib/types").InboundEvent) {
      const turnId = "turn_id" in ev && typeof ev.turn_id === "string" ? ev.turn_id : null;
      if (turnId && completedTurnIdsByChatId.get(chatId)?.has(turnId)) return;
      if (
        ev.event === "goal_status"
        && ev.status === "running"
        && typeof ev.started_at === "number"
      ) {
        advanceRunGeneration(chatId, ev.turn_id);
        runStartedAtByChatId.set(chatId, ev.started_at);
      } else if (
        (ev.event === "goal_status" && ev.status === "idle")
        || ev.event === "turn_end"
      ) {
        runStartedAtByChatId.delete(chatId);
      }
      if (ev.event === "goal_state") {
        goalStateByChatId.set(chatId, ev.goal_state);
      }
      for (const h of chatHandlers.get(chatId) ?? []) h(ev);
    },
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
) {
  return (
    <ClientProvider
      client={client as unknown as import("@/lib/nanobot-client").NanobotClient}
      token={token}
      modelName={modelName ?? null}
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
  rows: Array<{ role: "user" | "assistant"; content: string; turnId?: string }>,
): { schemaVersion: number; messages: UIMessage[] } {
  return {
    schemaVersion: 3,
    messages: rows.map((m, i) => ({
      id: `m-${i}`,
      role: m.role,
      content: m.content,
      ...(m.turnId ? { turnId: m.turnId } : {}),
      createdAt: 1000 + i,
    })),
  };
}

function httpJson(body: unknown) {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  };
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
    delete (document as Document & {
      visibilityState?: DocumentVisibilityState;
    }).visibilityState;
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
      bot_name: "nanobot",
      bot_icon: "",
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
      proxy: null,
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
        keep_recent_messages: 8,
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
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        json: async () => ({}),
      }),
    );
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

  it("does not navigate away when clicking the chat title", async () => {
    const client = makeClient();
    const onGoHome = vi.fn();
    render(wrap(
      client,
      <ThreadShell
        session={session("chat-title")}
        title="Important conversation"
        onToggleSidebar={() => {}}
        onGoHome={onGoHome}
        onNewChat={() => {}}
      />,
    ));

    await waitFor(() => expect(screen.getByText("Important conversation")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Important conversation"));

    expect(onGoHome).not.toHaveBeenCalled();
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

    expect(await screen.findByTitle("Fast · gpt-5.5 · OpenAI Codex")).toBeInTheDocument();
    expect(screen.queryByTitle("Default · deepseek-v4-pro · DeepSeek")).not.toBeInTheDocument();
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

    const badge = await screen.findByRole("spinbutton", { name: "Default" });
    expect(badge).toHaveTextContent("Default");
    fireEvent.keyDown(badge, { key: "ArrowDown" });

    expect(client.sendSystemCommand).toHaveBeenCalledWith(
      "preset-order",
      "/model fast",
    );
    expect(await screen.findByText("Fast")).toBeInTheDocument();
    fireEvent.keyDown(
      screen.getByRole("spinbutton", { name: "Fast" }),
      { key: "End" },
    );
    expect(client.sendSystemCommand).toHaveBeenLastCalledWith(
      "preset-order",
      "/model extra",
    );
    expect(await screen.findByText("Extra")).toBeInTheDocument();

    rerender(view("fast"));
    expect(await screen.findByText("Fast")).toBeInTheDocument();
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

    expect(await screen.findByTitle("Fast · gpt-4 · Company Proxy")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Model not configured" })).not.toBeInTheDocument();
  });

  it("highlights the configured model badge without replacing the preset label", async () => {
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
    const configuredBadge = screen.getByTestId("composer-model-logo-openai_codex").parentElement;
    expect(configuredBadge).not.toBeNull();
    expect(configuredBadge).toHaveClass("composer-model-badge");
    expect(configuredBadge).not.toHaveAttribute("data-fallback");

    act(() => {
      client._emitChat("fallback-model", {
        event: "turn_model_updated",
        chat_id: "fallback-model",
        model_name: "deepseek/deepseek-chat",
      });
    });

    const logo = screen.getByTestId("composer-model-logo-openai_codex");
    const badge = logo.parentElement;
    expect(badge).not.toBeNull();
    expect(badge).toBe(configuredBadge);
    expect(screen.getByText("Default")).toBeInTheDocument();
    expect(screen.queryByText("deepseek-chat")).not.toBeInTheDocument();
    expect(badge).toHaveAttribute("data-fallback", "true");
    expect(badge).toHaveAttribute(
      "title",
      "deepseek/deepseek-chat",
    );
    expect(logo).not.toHaveAttribute("data-fallback");

    act(() => {
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
    expect(
      screen.getByTestId("composer-model-logo-openai_codex").parentElement,
    ).toHaveAttribute("title", "Default · gpt-5.5 · OpenAI Codex");
    expect(
      screen.getByTestId("composer-model-logo-openai_codex").parentElement,
    ).toBe(badge);
  });

  it("opens model settings from the unconfigured model badge", async () => {
    const client = makeClient();
    const settings = modelSettings("openai-codex/gpt-5.1-codex", "openai_codex");
    settings.agent.has_api_key = false;
    settings.providers = settings.providers.map((provider) =>
      provider.name === "openai_codex"
        ? { ...provider, auth_type: "oauth", configured: false }
        : provider,
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

    const badge = await screen.findByRole("button", { name: "Model not configured" });
    expect(screen.getByTestId("composer-model-setup-icon")).toBeInTheDocument();
    expect(screen.queryByTestId("composer-model-logo-openai_codex")).not.toBeInTheDocument();
    fireEvent.click(badge);
    expect(onOpenModelSettings).toHaveBeenCalledTimes(1);

    fireEvent.change(screen.getByRole("textbox", { name: "Message input" }), {
      target: { value: "hello" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Configure model" }));
    expect(onOpenModelSettings).toHaveBeenCalledTimes(2);
    expect(client.sendMessage).not.toHaveBeenCalled();
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
    expect(screen.queryByRole("button", { name: "Toggle image generation mode" })).not.toBeInTheDocument();

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

    expect(screen.queryByRole("button", { name: "Toggle image generation mode" })).not.toBeInTheDocument();
  });

  it("restores in-memory messages when switching away and back to a session", async () => {
    const client = makeClient();
    const onNewChat = vi.fn().mockResolvedValue("chat-a");

    const { rerender } = render(
      wrap(
        client,
        <ThreadShell
          session={session("chat-a")}
          title="Chat chat-a"
          onToggleSidebar={() => {}}
          onGoHome={() => {}}
          onNewChat={onNewChat}
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
            onGoHome={() => {}}
            onNewChat={onNewChat}
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
            onGoHome={() => {}}
            onNewChat={onNewChat}
          />,
        ),
      );
    });

    expect(screen.getByText("persist me across tabs")).toBeInTheDocument();
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
      .toHaveTextContent("$github");
  });

  it("clears the old thread when the active session is removed", async () => {
    const client = makeClient();
    const onNewChat = vi.fn().mockResolvedValue("chat-a");

    const { rerender } = render(
      wrap(
        client,
        <ThreadShell
          session={session("chat-a")}
          title="Chat chat-a"
          onToggleSidebar={() => {}}
          onGoHome={() => {}}
          onNewChat={onNewChat}
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
            onGoHome={() => {}}
            onNewChat={onNewChat}
          />,
        ),
      );
    });

    await waitFor(() => {
      expect(screen.queryByText("delete me cleanly")).not.toBeInTheDocument();
    });
    expect(screen.getByPlaceholderText("Ask anything...")).toBeInTheDocument();
  });

  it("creates a chat only when the blank landing sends a first message", async () => {
    const client = makeClient();
    const onNewChat = vi.fn();
    const onCreateChat = vi.fn().mockResolvedValue("chat-new");

    render(
      wrap(
        client,
        <ThreadShell
          session={null}
          title="nanobot"
          onToggleSidebar={() => {}}
          onGoHome={() => {}}
          onNewChat={onNewChat}
          onCreateChat={onCreateChat}
        />,
      ),
    );

    fireEvent.change(screen.getByLabelText("Message input"), {
      target: { value: "start for real" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => expect(onCreateChat).toHaveBeenCalledTimes(1));
    expect(onNewChat).not.toHaveBeenCalled();
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

    fireEvent.keyDown(
      await screen.findByRole("spinbutton", { name: "Default" }),
      { key: "ArrowDown" },
    );
    expect(await screen.findByText("Fast")).toBeInTheDocument();
    expect(client.sendSystemCommand).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Message input"), {
      target: { value: "use the selected model" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => expect(client.sendSystemCommand).toHaveBeenCalledWith(
      "chat-new",
      "/model fast",
    ));

    rerender(view(session("chat-new")));
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
          onGoHome={() => {}}
          onNewChat={() => {}}
        />,
      ),
    );
    await act(async () => {});

    const greeting = screen.getByRole("heading", { level: 1, name: HERO_GREETING_PATTERN });
    expect(greeting).toHaveAttribute("data-testid", "hero-greeting");
    expect(greeting).toHaveClass("whitespace-nowrap");
    expect(screen.getByPlaceholderText("Ask anything...")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Write code" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create a project plan" })).not.toBeInTheDocument();
  });

  it("does not leak the previous thread when opening a brand-new chat", async () => {
    const client = makeClient();
    const onNewChat = vi.fn().mockResolvedValue("chat-new");
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
          onGoHome={() => {}}
          onNewChat={onNewChat}
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
            onGoHome={() => {}}
            onNewChat={onNewChat}
          />,
        ),
      );
    });

    expect(screen.queryByText("old answer")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByPlaceholderText("Ask anything...")).toBeInTheDocument(),
    );
    const input = screen.getByPlaceholderText("Ask anything...");
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

    const targetText = await screen.findByText("answer 100");
    fireEvent.click(within(targetText.closest(".w-full") as HTMLElement).getByRole("button", {
      name: "Fork",
    }));

    await waitFor(() =>
      expect(onForkChat).toHaveBeenCalledWith("long-chat", 101),
    );
  });

  it("does not cache optimistic messages under the next chat during a session switch", async () => {
    const client = makeClient();
    const onNewChat = vi.fn().mockResolvedValue("chat-b");

    const { rerender } = render(
      wrap(
        client,
        <ThreadShell
          session={session("chat-a")}
          title="Chat chat-a"
          onToggleSidebar={() => {}}
          onGoHome={() => {}}
          onNewChat={onNewChat}
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
            onGoHome={() => {}}
            onNewChat={onNewChat}
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
            onGoHome={() => {}}
            onNewChat={onNewChat}
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
            onGoHome={() => {}}
            onNewChat={onNewChat}
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
          onNewChat={() => {}}
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
            onNewChat={() => {}}
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
            onNewChat={() => {}}
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
        onNewChat={() => {}}
      />,
    );
    const { rerender } = render(view("chat-a"));

    await act(async () => {
      client._emitChat("chat-a", {
        event: "goal_status",
        chat_id: "chat-a",
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
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("websocket%3Achat-fork/webui-thread")) {
          historyCalls += 1;
          return httpJson(
            transcriptFromSimpleMessages(
              historyCalls === 1
                ? [{ role: "user", content: "first fork question" }]
                : [
                    { role: "user", content: "first fork question" },
                    { role: "user", content: "second fork question" },
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
          onNewChat={() => {}}
        />,
      ),
    );

    await waitFor(() => expect(screen.getByText("first fork question")).toBeInTheDocument());
    await act(async () => {
      client._emitChat("chat-fork", {
        event: "message",
        chat_id: "chat-fork",
        text: "first fork answer",
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
    expect(screen.getByText("second fork question")).toBeInTheDocument();

    await act(async () => {
      client._emitSessionUpdate("chat-fork");
    });

    await waitFor(() => expect(historyCalls).toBe(2));
    expect(screen.getByText("first fork question")).toBeInTheDocument();
    expect(screen.getByText("first fork answer")).toBeInTheDocument();
    expect(screen.getByText("second fork question")).toBeInTheDocument();
  });

  it("recovers a truncated streamed answer after reconnecting", async () => {
    const client = makeClient();
    let historyCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("websocket%3Aresume-chat/webui-thread")) {
          historyCalls += 1;
          return httpJson(
            transcriptFromSimpleMessages(
              historyCalls === 1
                ? [{ role: "user", content: "question" }]
                : [
                    { role: "user", content: "question" },
                    { role: "assistant", content: "partial answer completed while away" },
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
          session={session("resume-chat")}
          title="Resume chat"
          onToggleSidebar={() => {}}
          onNewChat={() => {}}
        />,
      ),
    );

    await waitFor(() => expect(screen.getByText("question")).toBeInTheDocument());
    act(() => {
      client._emitChat("resume-chat", {
        event: "goal_status",
        chat_id: "resume-chat",
        status: "running",
        started_at: 1_700,
      });
      client._emitChat("resume-chat", {
        event: "delta",
        chat_id: "resume-chat",
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
          onNewChat={() => {}}
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
                      role: "assistant",
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
                      role: "assistant",
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
          onNewChat={() => {}}
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
                ? [{ role: "assistant", content: "committed old lineage" }]
                : [{ role: "assistant", content: "disjoint new lineage" }],
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
        onNewChat={() => {}}
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
            { role: "assistant", content: "old canonical row" },
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
          onNewChat={() => {}}
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
        text: "local durable row after request",
      });
    });
    await waitFor(() =>
      expect(screen.getByText("local durable row after request")).toBeInTheDocument(),
    );

    await act(async () => {
      resolveRefresh?.(httpJson({
        ...transcriptFromSimpleMessages([
          { role: "assistant", content: "disjoint canonical reset row" },
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
          onNewChat={() => {}}
        />,
      ),
    );

    await waitFor(() => expect(historyCalls).toBe(1));
    const input = screen.getByRole("textbox", { name: "Message input" });
    fireEvent.change(input, { target: { value: "rejected local turn" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(screen.getByText("rejected local turn")).toBeInTheDocument());

    act(() => client._emitSessionUpdate("empty-reset-chat", "thread"));

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
            ...transcriptFromSimpleMessages(
              canonicalComplete
                ? [
                    { role: "user", content: "strict question", turnId },
                    { role: "assistant", content: "strict canonical answer", turnId },
                  ]
                : [{ role: "user", content: "strict question", turnId }],
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
            onNewChat={() => {}}
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
        turn_id: turnId,
      });
    });
    await waitFor(() => expect(screen.getByText("strict partial")).toBeInTheDocument());
    client.reconcileCanonicalCompletion.mockClear();
    const reconcileAfterCommit = client.reconcileCanonicalCompletion.getMockImplementation();
    client.reconcileCanonicalCompletion.mockImplementation((...args) => {
      expect(screen.getByText("strict canonical answer")).toBeInTheDocument();
      return reconcileAfterCommit?.(...args) ?? false;
    });
    canonicalComplete = true;

    act(() => client._emitSessionUpdate("strict-canonical", "thread"));

    await waitFor(() => expect(screen.getByText("strict canonical answer")).toBeInTheDocument());
    expect(client.reconcileCanonicalCompletion).toHaveBeenCalledTimes(1);
    expect(client.canReconcileCanonicalCompletion).toHaveBeenCalled();
  });

  it("rolls back a committed candidate when the final lifecycle recheck loses", async () => {
    const client = makeClient();
    const turnId = "turn-layout-recheck";
    let historyCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes("websocket%3Alayout-recheck/webui-thread")) {
          historyCalls += 1;
          return httpJson({
            ...transcriptFromSimpleMessages(
              historyCalls === 1
                ? [{ role: "user", content: "layout question", turnId }]
                : [
                    { role: "user", content: "layout question", turnId },
                    { role: "assistant", content: "layout canonical answer", turnId },
                  ],
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
          session={session("layout-recheck")}
          title="Layout recheck"
          onToggleSidebar={() => {}}
          onNewChat={() => {}}
        />,
      ),
    );

    await waitFor(() => expect(screen.getByText("layout question")).toBeInTheDocument());
    act(() => {
      client._emitChat("layout-recheck", {
        event: "goal_status",
        chat_id: "layout-recheck",
        status: "running",
        started_at: 2_200,
        turn_id: turnId,
      });
      client._emitChat("layout-recheck", {
        event: "delta",
        chat_id: "layout-recheck",
        text: "layout partial",
        turn_id: turnId,
      });
    });
    await waitFor(() => expect(screen.getByText("layout partial")).toBeInTheDocument());

    const reconcileAfterReject = client.reconcileCanonicalCompletion.getMockImplementation();
    client.reconcileCanonicalCompletion
      .mockImplementationOnce(() => false)
      .mockImplementation((...args) => reconcileAfterReject?.(...args) ?? false);

    act(() => client._emitSessionUpdate("layout-recheck", "thread"));

    await waitFor(() => expect(historyCalls).toBe(2));
    await waitFor(() =>
      expect(client.reconcileCanonicalCompletion).toHaveBeenCalledTimes(1),
    );
    expect(screen.getByText("layout partial")).toBeInTheDocument();
    expect(screen.queryByText("layout canonical answer")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop response" })).toBeInTheDocument();

    act(() => client._emitSessionUpdate("layout-recheck", "thread"));

    await waitFor(() => expect(historyCalls).toBe(3));
    await waitFor(() => expect(screen.getByText("layout canonical answer")).toBeInTheDocument());
    expect(screen.queryByText("layout partial")).not.toBeInTheDocument();
    expect(client.reconcileCanonicalCompletion).toHaveBeenCalledTimes(2);
  });

  it("accepts the first reconnect refresh after switching away and back", async () => {
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
          const rows = chatACalls <= 2
            ? [
                { role: "user" as const, content: "old question", turnId: oldTurnId },
                { role: "assistant" as const, content: "old answer", turnId: oldTurnId },
              ]
            : [
                { role: "user" as const, content: "old question", turnId: oldTurnId },
                { role: "assistant" as const, content: "old answer", turnId: oldTurnId },
                { role: "user" as const, content: "new question", turnId: newTurnId },
                {
                  role: "assistant" as const,
                  content: "partial answer completed",
                  turnId: newTurnId,
                },
              ];
          return httpJson({
            ...transcriptFromSimpleMessages(rows),
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
        onNewChat={() => {}}
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
        turn_id: newTurnId,
      });
    });
    await waitFor(() => expect(screen.getByText("partial answer")).toBeInTheDocument());

    rerender(view("chat-version-b"));
    await waitFor(() => expect(screen.getByText("other chat")).toBeInTheDocument());
    rerender(view("chat-version-a"));
    await waitFor(() => expect(chatACalls).toBe(3));
    expect(screen.getByText("partial answer")).toBeInTheDocument();
    expect(screen.queryByText("partial answer completed")).not.toBeInTheDocument();

    act(() => client._emitStatus("reconnecting"));
    act(() => client._emitStatus("open"));

    await waitFor(() => expect(chatACalls).toBe(4));
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
          onNewChat={() => {}}
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
            ...transcriptFromSimpleMessages(
              historyCalls === 1
                ? [{ role: "user", content: "question", turnId }]
                : [
                    { role: "user", content: "question", turnId },
                    { role: "assistant", content: "canonical complete answer", turnId },
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
          session={session("late-frame-chat")}
          title="Late frame chat"
          onToggleSidebar={() => {}}
          onNewChat={() => {}}
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
        turn_id: turnId,
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
        turn_id: turnId,
      });
      client._emitChat("late-frame-chat", {
        event: "turn_end",
        chat_id: "late-frame-chat",
        turn_id: turnId,
      });
      client._emitSessionUpdate("late-frame-chat");
    });

    await waitFor(() => expect(historyCalls).toBe(3));
    expect(screen.getAllByText("canonical complete answer")).toHaveLength(1);
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
        onNewChat={() => {}}
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
          onNewChat={() => {}}
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
          const transcript = transcriptFromSimpleMessages(
            historyCalls === 1
              ? [{ role: "user", content: "question", turnId }]
              : [
                  { role: "user", content: "question", turnId },
                  {
                    role: "assistant",
                    content: historyCalls === 2
                      ? "missed prefix"
                      : "missed prefix resumed suffix",
                    turnId,
                  },
                ],
          );
          return httpJson({
            ...transcript,
            has_pending_tool_calls: historyCalls === 2,
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
          onGoHome={() => {}}
          onNewChat={() => {}}
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
    expect(screen.queryByText("missed prefix")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop response" })).toBeInTheDocument();
    expect(client.sendMessage).not.toHaveBeenCalled();

    act(() => {
      client._emitChat("before-delta-chat", {
        event: "delta",
        chat_id: "before-delta-chat",
        text: "resumed suffix",
        turn_id: turnId,
      });
    });
    await waitFor(() => expect(screen.getByText("resumed suffix")).toBeInTheDocument());

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
          const transcript = transcriptFromSimpleMessages(
            historyCalls === 1
              ? [{ role: "user", content: "question", turnId }]
              : [
                  { role: "user", content: "question", turnId },
                  {
                    role: "assistant",
                    content: historyCalls === 2
                      ? "partial answer missed"
                      : "partial answer missed resumed",
                    turnId,
                  },
                ],
          );
          return httpJson(
            historyCalls === 1
              ? transcript
              : { ...transcript, has_pending_tool_calls: historyCalls === 2 },
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
          session={session("active-resume-chat")}
          title="Active resume chat"
          onToggleSidebar={() => {}}
          onNewChat={() => {}}
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
        turn_id: turnId,
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
        turn_id: turnId,
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
            onNewChat={() => {}}
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
            onNewChat={() => {}}
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
            onNewChat={() => {}}
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
          onNewChat={() => {}}
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
          thread.messages[1]!.media = [{
            kind: "image",
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
          onNewChat={() => {}}
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
          thread.messages[1]!.media = [{
            kind: "image",
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
        onNewChat={() => {}}
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
            onNewChat={() => {}}
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
            onNewChat={() => {}}
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
          onNewChat={() => {}}
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
            onNewChat={() => {}}
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
          onNewChat={() => {}}
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

  it("does not bring back welcome cards when image mode is enabled", async () => {
    const client = makeClient();
    const settings = modelSettings("deepseek-v4-pro", "deepseek");
    render(
      wrap(
        client,
        <ThreadShell
          session={null}
          title="nanobot"
          onToggleSidebar={() => {}}
          onNewChat={() => {}}
          settingsSnapshot={{
            ...settings,
            image_generation: {
              ...settings.image_generation,
              enabled: true,
              provider_configured: true,
            },
          }}
        />,
      ),
    );
    await act(async () => {});

    expect(screen.queryByText("Design an app icon")).not.toBeInTheDocument();
    expect(screen.queryByText("Write code")).not.toBeInTheDocument();

    expect(screen.queryByText("Design an app icon")).not.toBeInTheDocument();
    expect(screen.queryByText("Write code")).not.toBeInTheDocument();
  });

  it("surfaces a dismissible banner for an uncorrelated message_too_big error", async () => {
    const client = makeClient();
    const onNewChat = vi.fn().mockResolvedValue("chat-a");

    render(
      wrap(
        client,
        <ThreadShell
          session={session("chat-a")}
          title="Chat chat-a"
          onToggleSidebar={() => {}}
          onGoHome={() => {}}
          onNewChat={onNewChat}
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

  it("moves a correlated delivery error from the banner into the failed message tooltip", async () => {
    const client = makeClient();

    render(
      wrap(
        client,
        <ThreadShell
          session={session("chat-inline-error")}
          title="Chat inline error"
          onToggleSidebar={() => {}}
          onGoHome={() => {}}
          onNewChat={() => {}}
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
    const onNewChat = vi.fn().mockResolvedValue("chat-a");

    const { rerender } = render(
      wrap(
        client,
        <ThreadShell
          session={session("chat-a")}
          title="Chat chat-a"
          onToggleSidebar={() => {}}
          onGoHome={() => {}}
          onNewChat={onNewChat}
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
            onGoHome={() => {}}
            onNewChat={onNewChat}
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
    const onNewChat = vi.fn().mockResolvedValue("chat-b");
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
          onGoHome={() => {}}
          onNewChat={onNewChat}
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
            onGoHome={() => {}}
            onNewChat={onNewChat}
          />,
        ),
      );
    });

    expect(screen.queryByText("from chat a")).not.toBeInTheDocument();
    expect(screen.getByText("Loading conversation…")).toBeInTheDocument();

    await act(async () => {
      resolveChatB?.(
        httpJson(transcriptFromSimpleMessages([{ role: "assistant", content: "from chat b" }])),
      );
    });

    await waitFor(() => expect(screen.getByText("from chat b")).toBeInTheDocument());
    expect(screen.queryByText("from chat a")).not.toBeInTheDocument();
  });

  it("updates @ CLI app suggestions when settings broadcasts an install", async () => {
    const client = makeClient();
    render(wrap(
      client,
      <ThreadShell
        session={session("chat-cli-apps")}
        title="Chat chat-cli-apps"
        onToggleSidebar={() => {}}
        onGoHome={() => {}}
        onNewChat={() => {}}
      />,
    ));

    const input = await screen.findByLabelText("Message input");
    expect(screen.queryByRole("listbox", { name: "Apps" })).not.toBeInTheDocument();

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

    expect(screen.getByRole("listbox", { name: "Apps" })).toBeInTheDocument();
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
        onGoHome={() => {}}
        onNewChat={() => {}}
      />,
    ));

    const input = await screen.findByLabelText("Message input");
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
        onGoHome={() => {}}
        onNewChat={() => {}}
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
      "@obsidian-agent-cli",
    );
  });
});
