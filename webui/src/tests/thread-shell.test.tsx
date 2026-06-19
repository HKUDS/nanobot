import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ThreadShell } from "@/components/thread/ThreadShell";
import { CLI_APPS_CHANGED_EVENT } from "@/lib/cli-app-events";
import { ClientProvider } from "@/providers/ClientProvider";
import type { CliAppsPayload, SettingsPayload, UIMessage } from "@/lib/types";

const HERO_GREETING_PATTERN =
  /What should we work on\?|Where should we start\?|What are we building today\?|What should we tackle together\?/;

function makeClient() {
  const errorHandlers = new Set<(err: { kind: string }) => void>();
  const chatHandlers = new Map<string, Set<(ev: import("@/lib/types").InboundEvent) => void>>();
  const sessionUpdateHandlers = new Set<(chatId: string, scope?: string) => void>();
  const goalStateByChatId = new Map<string, import("@/lib/types").GoalStateWsPayload>();
  return {
    status: "open" as const,
    defaultChatId: null as string | null,
    onStatus: () => () => {},
    onRuntimeModelUpdate: () => () => {},
    getRunStartedAt: () => null,
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
    onError: (handler: (err: { kind: string }) => void) => {
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
    _emitError(err: { kind: string }) {
      for (const h of errorHandlers) h(err);
    },
    _emitChat(chatId: string, ev: import("@/lib/types").InboundEvent) {
      if (ev.event === "goal_state") {
        goalStateByChatId.set(chatId, ev.goal_state);
      }
      for (const h of chatHandlers.get(chatId) ?? []) h(ev);
    },
    _emitSessionUpdate(chatId: string, scope?: string) {
      for (const h of sessionUpdateHandlers) h(chatId, scope);
    },
    sendMessage: vi.fn(),
    newChat: vi.fn(),
    forkChat: vi.fn(),
    attach: vi.fn(),
    connect: vi.fn(),
    close: vi.fn(),
    updateUrl: vi.fn(),
  };
}

function wrap(client: ReturnType<typeof makeClient>, children: ReactNode, modelName?: string | null) {
  return (
    <ClientProvider
      client={client as unknown as import("@/lib/nanobot-client").NanobotClient}
      token="tok"
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

function session(chatId: string) {
  return {
    key: `websocket:${chatId}`,
    channel: "websocket" as const,
    chatId,
    createdAt: null,
    updatedAt: null,
    preview: "",
  };
}

function transcriptFromSimpleMessages(
  rows: Array<{ role: "user" | "assistant"; content: string }>,
): { schemaVersion: number; messages: UIMessage[] } {
  return {
    schemaVersion: 3,
    messages: rows.map((m, i) => ({
      id: `m-${i}`,
      role: m.role,
      content: m.content,
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
        max_batch_size: 20,
        max_iterations: 15,
        annotate_line_ages: true,
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

  it("keeps a live first command reply when the initial history snapshot is stale", async () => {
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
    });
    expect(screen.getByText(/Current model/)).toBeInTheDocument();

    await act(async () => {
      resolveThread?.(
        httpJson(transcriptFromSimpleMessages([{ role: "user", content: "/model" }])),
      );
    });

    await waitFor(() => expect(screen.getByText(/Current model/)).toBeInTheDocument());
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

    expect(screen.getByText(HERO_GREETING_PATTERN)).toBeInTheDocument();
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

  it("does not refetch thread history for metadata-only session updates", async () => {
    const client = makeClient();
    let historyCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("websocket%3Achat-a/webui-thread")) {
          historyCalls += 1;
          return httpJson(
            transcriptFromSimpleMessages([
              { role: "user", content: "question" },
              { role: "assistant", content: "answer" },
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
    expect(historyCalls).toBe(1);

    await act(async () => {
      client._emitSessionUpdate("chat-a", "metadata");
    });

    expect(historyCalls).toBe(1);
  });

  it("scrolls to the bottom after loading a session from the blank new-chat page", async () => {
    const client = makeClient();
    const scrollIntoView = vi.fn();
    const originalScrollIntoView = HTMLElement.prototype.scrollIntoView;
    HTMLElement.prototype.scrollIntoView = scrollIntoView;
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

    try {
      const { rerender } = render(
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
      scrollIntoView.mockClear();

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
      await waitFor(() =>
        expect(scrollIntoView).toHaveBeenCalledWith({
          block: "end",
          behavior: "auto",
        }),
      );
    } finally {
      HTMLElement.prototype.scrollIntoView = originalScrollIntoView;
    }
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

  it("surfaces a dismissible banner when the stream reports message_too_big", async () => {
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
});
