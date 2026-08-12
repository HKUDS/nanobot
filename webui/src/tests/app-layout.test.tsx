import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";
import type {
  ChatSummary,
  ConnectionStatus,
  SessionAutomationJob,
  SidebarStatePayload,
  WorkspaceScopePayload,
} from "@/lib/types";

const connectSpy = vi.fn();
const refreshSpy = vi.fn();
const createChatSpy = vi.fn().mockResolvedValue("chat-1");
const deleteChatSpy = vi.fn();
const getSessionAutomationsSpy = vi.fn<(key: string) => Promise<SessionAutomationJob[]>>();
const toggleThemeSpy = vi.fn();
const updateUrlSpy = vi.fn();
const attachSpy = vi.fn();
const setSidebarStateSpy = vi.fn();
const requestMutationSpy = vi.fn();
const discardTemporaryChatSpy = vi.fn();
const newTemporaryChatSpy = vi.fn<() => Promise<string>>();
const sendMessageSpy = vi.fn();
const statusHandlers = new Set<(status: ConnectionStatus) => void>();
const runStatusHandlers = new Set<(chatId: string, startedAt: number | null) => void>();
const sessionUpdateHandlers = new Set<(
  chatId: string,
  scope?: string,
  workspaceScope?: WorkspaceScopePayload,
) => void>();
const sidebarStateUpdateHandlers = new Set<(state: SidebarStatePayload) => void>();
let mockSessions: ChatSummary[] = [];
const HERO_GREETING_PATTERN =
  /What should we work on\?|Where should we start\?|What are we building today\?|What should we tackle together\?/;

function setNavigatorPlatform(platform: string): void {
  Object.defineProperty(window.navigator, "platform", {
    configurable: true,
    value: platform,
  });
}

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  } as Response;
}

function mockFetchRoutes(routes: Record<string, unknown>): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const route = routes[String(input)];
      const body =
        typeof route === "function"
          ? await (route as () => unknown | Promise<unknown>)()
          : route;
      return body === undefined
        ? ({ ok: false, status: 404, json: async () => ({}) } as Response)
        : jsonResponse(body);
    }),
  );
}

function baseSettingsPayload() {
  return {
    agent: {
      model: "openai/gpt-4o",
      provider: "auto",
      resolved_provider: "openai",
      has_api_key: true,
      model_preset: "default",
      max_tokens: 8192,
      context_window_tokens: 65536,
      temperature: 0.1,
      reasoning_effort: null,
      timezone: "UTC",
      tool_hint_max_length: 40,
    },
    model_presets: [{
      name: "default",
      label: "Default",
      active: true,
      is_default: true,
      model: "openai/gpt-4o",
      provider: "auto",
      max_tokens: 8192,
      context_window_tokens: 65536,
      temperature: 0.1,
      reasoning_effort: null,
    }],
    model_call_order: [],
    model_call_order_editable: false,
    providers: [],
    web_search: {
      provider: "duckduckgo",
      api_key_hint: null,
      base_url: null,
      max_results: 5,
      timeout: 30,
      providers: [{ name: "duckduckgo", label: "DuckDuckGo", credential: "none" }],
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

vi.mock("@/hooks/useSessions", async (importOriginal) => {
  const React = await import("react");
  const actual = await importOriginal<typeof import("@/hooks/useSessions")>();
  return {
    ...actual,
    useSessions: () => {
      const [sessions, setSessions] = React.useState(mockSessions);
      return {
        sessions,
        loading: false,
        error: null,
        refresh: refreshSpy,
        createChat: async (scope?: WorkspaceScopePayload | null) => {
          const chatId = await createChatSpy(scope);
          const now = new Date().toISOString();
          setSessions((prev: ChatSummary[]) => [
            {
              key: `websocket:${chatId}`,
              channel: "websocket",
              chatId,
              createdAt: now,
              updatedAt: now,
              title: "",
              preview: "",
              workspaceScope: scope ?? null,
            },
            ...prev.filter((session) => session.chatId !== chatId),
          ]);
          return chatId;
        },
        forkChat: async () => "fork-chat",
        getSessionAutomations: getSessionAutomationsSpy,
        deleteChat: async (key: string, options?: { deleteAutomations?: boolean }) => {
          if (options === undefined) await deleteChatSpy(key);
          else await deleteChatSpy(key, options);
          setSessions((prev: ChatSummary[]) => prev.filter((s) => s.key !== key));
          return { deleted: true };
        },
      };
    },
  };
});

vi.mock("@/hooks/useTheme", async () => {
  const React = await import("react");
  return {
    ThemeProvider: ({ children }: { children: React.ReactNode }) =>
      React.createElement(React.Fragment, null, children),
    useTheme: () => ({
      theme: "light" as const,
      toggle: toggleThemeSpy,
    }),
    useThemeValue: () => "light" as const,
  };
});

vi.mock("@/lib/bootstrap", () => ({
  BootstrapAuthRequiredError: class BootstrapAuthRequiredError extends Error {
    constructor(message = "bootstrap authentication required") {
      super(message);
      this.name = "BootstrapAuthRequiredError";
    }
  },
  fetchBootstrap: vi.fn().mockResolvedValue({
    token: "tok",
    api_token: "api-tok",
    ws_path: "/",
    expires_in: 300,
  }),
  deriveWsUrl: vi.fn(() => "ws://test"),
  consumeUrlBootstrapSecret: vi.fn(() => ""),
  loadSavedSecret: vi.fn(() => ""),
  saveSecret: vi.fn(),
  clearSavedSecret: vi.fn(),
}));

vi.mock("@/lib/nanobot-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/nanobot-client")>();
  class MockClient {
    status = "idle" as const;
    defaultChatId: string | null = null;
    connect = connectSpy;
    onStatus = (handler: (status: ConnectionStatus) => void) => {
      statusHandlers.add(handler);
      return () => statusHandlers.delete(handler);
    };
    onRuntimeModelUpdate = () => () => {};
    onError = () => () => {};
    onChat = () => () => {};
    onSessionUpdate = (handler: (
      chatId: string,
      scope?: string,
      workspaceScope?: WorkspaceScopePayload,
    ) => void) => {
      sessionUpdateHandlers.add(handler);
      return () => sessionUpdateHandlers.delete(handler);
    };
    onSidebarStateUpdate = (handler: (state: SidebarStatePayload) => void) => {
      sidebarStateUpdateHandlers.add(handler);
      return () => sidebarStateUpdateHandlers.delete(handler);
    };
    onRunStatus = (handler: (chatId: string, startedAt: number | null) => void) => {
      runStatusHandlers.add(handler);
      return () => runStatusHandlers.delete(handler);
    };
    getRunStartedAt = () => null;
    getGoalState = () => undefined;
    sendMessage = sendMessageSpy;
    newChat = vi.fn();
    newTemporaryChat = newTemporaryChatSpy;
    attach = attachSpy;
    setSidebarState = setSidebarStateSpy;
    requestMutation = requestMutationSpy;
    discardTemporaryChat = discardTemporaryChatSpy;
    close = vi.fn();
    updateUrl = updateUrlSpy;
    updateMaxFrameBytes = vi.fn();
  }

  return { ...actual, NanobotClient: MockClient };
});

import {
  BootstrapAuthRequiredError,
  deriveWsUrl,
  fetchBootstrap,
} from "@/lib/bootstrap";
import App from "@/App";

describe("App layout", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    mockSessions = [];
    connectSpy.mockClear();
    updateUrlSpy.mockClear();
    refreshSpy.mockReset();
    createChatSpy.mockClear();
    deleteChatSpy.mockReset();
    getSessionAutomationsSpy.mockReset().mockResolvedValue([]);
    toggleThemeSpy.mockReset();
    attachSpy.mockReset();
    setSidebarStateSpy.mockReset().mockImplementation(
      async (state: SidebarStatePayload) => state,
    );
    requestMutationSpy.mockReset();
    discardTemporaryChatSpy.mockReset();
    let temporaryChatCounter = 0;
    newTemporaryChatSpy.mockImplementation(async () => (
      `00000000-0000-4000-8000-${String(++temporaryChatCounter).padStart(12, "0")}`
    ));
    sendMessageSpy.mockReset();
    statusHandlers.clear();
    runStatusHandlers.clear();
    sessionUpdateHandlers.clear();
    sidebarStateUpdateHandlers.clear();
    window.history.replaceState(null, "", "/");
    setNavigatorPlatform("Linux x86_64");
    localStorage.removeItem("nanobot-webui.sidebar");
    localStorage.removeItem("nanobot-webui.sidebar.completed-runs.v1");
    localStorage.removeItem("nanobot-webui.sidebar.session-updates.v1");
    localStorage.removeItem("nanobot-webui.collapsed-pane-groups.v1");
    localStorage.removeItem("nanobot-webui.restartStartedAt");
    localStorage.removeItem("nanobot-webui.restartRoute");
    vi.mocked(fetchBootstrap).mockReset().mockResolvedValue({
      token: "tok",
      api_token: "api-tok",
      ws_path: "/",
      expires_in: 300,
    });
    vi.mocked(deriveWsUrl).mockReset().mockReturnValue("ws://test");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
      }),
    );
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("shows the auth form without an invalid-password error on first load", async () => {
    vi.mocked(fetchBootstrap).mockRejectedValueOnce(
      new Error("bootstrap failed: HTTP 401"),
    );

    render(<App />);

    expect(await screen.findByRole("heading", { level: 1, name: "nanobot" }))
      .toBeInTheDocument();
    const password = screen.getByLabelText("Password");
    expect(password).toHaveAttribute(
      "autocomplete",
      "current-password",
    );
    expect(password).not.toHaveAttribute("placeholder");
    expect(password).toHaveClass("bg-background");
    expect(screen.getByTestId("nanobot-particle-mark")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    expect(screen.queryByText("Authentication required")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Incorrect password. Try again."),
    ).not.toBeInTheDocument();
    expect(connectSpy).not.toHaveBeenCalled();
  });

  it("toggles password visibility without changing the password", async () => {
    vi.mocked(fetchBootstrap).mockRejectedValueOnce(
      new Error("bootstrap failed: HTTP 401"),
    );
    const user = userEvent.setup();

    render(<App />);

    const password = await screen.findByLabelText("Password");
    await user.type(password, "correct horse battery staple");
    expect(password).toHaveAttribute("type", "password");

    await user.click(screen.getByRole("button", { name: "Show password" }));

    expect(password).toHaveAttribute("type", "text");
    expect(password).toHaveValue("correct horse battery staple");
    const hidePassword = screen.getByRole("button", { name: "Hide password" });
    expect(hidePassword).toHaveFocus();

    await user.click(hidePassword);

    expect(password).toHaveAttribute("type", "password");
    expect(password).toHaveValue("correct horse battery staple");
    expect(screen.getByRole("button", { name: "Show password" })).toHaveFocus();
  });

  it("explains and focuses an empty auth password", async () => {
    vi.mocked(fetchBootstrap).mockRejectedValue(
      new Error("bootstrap failed: HTTP 401"),
    );

    render(<App />);

    const password = await screen.findByLabelText("Password");
    const connect = screen.getByRole("button", { name: "Connect" });
    expect(connect).toBeEnabled();
    fireEvent.click(connect);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Enter your password.",
    );
    expect(password).toHaveAttribute("aria-invalid", "true");
    expect(password).toHaveAttribute("aria-describedby", "webui-auth-error");
    expect(password).toHaveFocus();
    expect(fetchBootstrap).toHaveBeenCalledTimes(1);
  });

  it("shows the auth form when bootstrap does not issue an API token", async () => {
    vi.mocked(fetchBootstrap).mockRejectedValueOnce(
      new BootstrapAuthRequiredError(
        "bootstrap authentication required: missing api_token",
      ),
    );

    render(<App />);

    expect(await screen.findByRole("heading", { level: 1, name: "nanobot" }))
      .toBeInTheDocument();
    expect(
      screen.queryByText("Incorrect password. Try again."),
    ).not.toBeInTheDocument();
    expect(connectSpy).not.toHaveBeenCalled();
  });

  it("shows an invalid-password error after a submitted password is rejected", async () => {
    vi.mocked(fetchBootstrap).mockRejectedValue(
      new Error("bootstrap failed: HTTP 401"),
    );

    render(<App />);

    const password = await screen.findByLabelText("Password");
    fireEvent.change(password, { target: { value: "wrong-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    const retryPassword = await screen.findByLabelText("Password");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Incorrect password. Try again.",
    );
    expect(retryPassword).toHaveAttribute("aria-invalid", "true");
    expect(retryPassword).toHaveFocus();
    expect(fetchBootstrap).toHaveBeenLastCalledWith("", "wrong-password");
    expect(connectSpy).not.toHaveBeenCalled();
  });

  it("keeps sidebar layout out of the main thread width contract", async () => {
    const { container } = render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());

    const main = container.querySelector("main");
    expect(main).toBeInTheDocument();
    expect(main).not.toHaveAttribute("style");

    const asideClassNames = Array.from(container.querySelectorAll("aside")).map(
      (el) => el.className,
    );
    expect(asideClassNames.some((cls) => cls.includes("lg:block"))).toBe(true);
  });

  it("uses one main landmark and a page heading in desktop settings", async () => {
    mockFetchRoutes({ "/api/settings": baseSettingsPayload() });
    const { container } = render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    fireEvent.click(within(sidebar).getByRole("button", { name: "Settings" }));

    await act(async () => {
      await import("@/components/settings/SettingsView");
    });

    expect(
      screen.getByRole("navigation", { name: "Settings sections" }),
    ).toBeInTheDocument();
    expect(container.querySelectorAll("main")).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
  });

  it("places Automations after Skills in the main sidebar", async () => {
    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    const appsButton = within(sidebar).getByRole("button", { name: "Apps" });
    const skillsButton = within(sidebar).getByRole("button", { name: "Skills" });
    const automationsButton = within(sidebar).getByRole("button", { name: "Automations" });

    expect(appsButton.compareDocumentPosition(skillsButton) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy();
    expect(
      skillsButton.compareDocumentPosition(automationsButton) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("highlights the blank new-topic destination immediately", async () => {
    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    const newTopicButton = within(sidebar).getByRole("button", { name: "New topic" });

    expect(newTopicButton).toHaveAttribute("aria-current", "page");
    expect(newTopicButton).not.toHaveClass("bg-sidebar-accent");
    expect(newTopicButton).toHaveClass("transition-[width,padding,color]");
    expect(within(sidebar).getByTestId("actions-selection-highlight")).toHaveAttribute(
      "data-active-id",
      "new-chat",
    );
  });

  it("keeps a just-created topic route while the session list catches up", async () => {
    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const firstMessage = "keep this first turn visible";
    fireEvent.change(screen.getByRole("textbox", { name: "Message input" }), {
      target: { value: firstMessage },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => expect(createChatSpy).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(window.location.hash).toBe(
        `#/chat/${encodeURIComponent("websocket:chat-1")}`,
      ),
    );
    expect(await screen.findByText(firstMessage)).toBeInTheDocument();
  });

  it("creates a new temporary chat from the hero each time", async () => {
    const { unmount } = render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    expect(within(sidebar).queryByRole("button", { name: "Temporary chat" })).not.toBeInTheDocument();
    const firstToggle = screen.getByRole("button", { name: "Temporary chat" });
    expect(firstToggle).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(firstToggle);
    expect(firstToggle).toHaveAttribute("aria-pressed", "true");
    expect(window.location.hash).toBe("");

    fireEvent.change(screen.getByLabelText("Message input"), {
      target: { value: "first private message" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => expect(window.location.hash).toMatch(/^#\/temporary\/[0-9a-f-]+$/));
    const firstHash = window.location.hash;
    expect(firstHash).toMatch(/^#\/temporary\/[0-9a-f-]+$/);
    expect(screen.queryByRole("button", { name: "Temporary chat" })).not.toBeInTheDocument();
    expect(createChatSpy).not.toHaveBeenCalled();

    fireEvent.click(within(sidebar).getByRole("button", { name: "New topic" }));
    expect(discardTemporaryChatSpy).not.toHaveBeenCalled();
    const secondToggle = screen.getByRole("button", { name: "Temporary chat" });
    expect(secondToggle).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(secondToggle);
    fireEvent.change(screen.getByLabelText("Message input"), {
      target: { value: "second private message" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(window.location.hash).toMatch(/^#\/temporary\/[0-9a-f-]+$/));
    const secondHash = window.location.hash;
    expect(secondHash).toMatch(/^#\/temporary\/[0-9a-f-]+$/);
    expect(secondHash).not.toBe(firstHash);
    expect(screen.queryByRole("button", { name: "Temporary chat" })).not.toBeInTheDocument();
    expect(discardTemporaryChatSpy).not.toHaveBeenCalled();

    expect(within(sidebar).getByText("Temporary chats")).toBeInTheDocument();
    expect(within(sidebar).getByRole("button", {
      name: "first private message",
    })).toBeInTheDocument();
    expect(within(sidebar).getByRole("button", {
      name: "second private message",
    })).toBeInTheDocument();

    fireEvent.click(within(sidebar).getByRole("button", {
      name: "first private message",
    }));
    await waitFor(() => expect(window.location.hash).toBe(firstHash));
    expect(within(screen.getByTestId("thread-header")).getByText(
      "first private message",
    )).toBeInTheDocument();
    await waitFor(() => expect(document.title).toBe("first private message · nanobot"));
    expect(screen.queryByRole("button", { name: "Temporary chat" })).not.toBeInTheDocument();

    fireEvent.click(within(sidebar).getByRole("button", {
      name: "Close temporary chat: first private message",
    }));
    await waitFor(() => expect(window.location.hash).toBe(secondHash));
    expect(within(sidebar).queryByRole("button", {
      name: "first private message",
    })).not.toBeInTheDocument();
    expect(within(sidebar).getByRole("button", {
      name: "second private message",
    })).toBeInTheDocument();
    expect(discardTemporaryChatSpy).toHaveBeenCalledTimes(1);

    unmount();
    await waitFor(() => expect(discardTemporaryChatSpy).toHaveBeenCalledTimes(2));
    const discardedChatIds = discardTemporaryChatSpy.mock.calls.map(([chatId]) => chatId);
    expect(new Set(discardedChatIds).size).toBe(2);
    expect(discardedChatIds).toEqual([
      "00000000-0000-4000-8000-000000000001",
      "00000000-0000-4000-8000-000000000002",
    ]);
  });

  it("shows the temporary-chat control only on the new-topic hero", async () => {
    mockSessions = [{
      key: "websocket:existing-chat",
      channel: "websocket",
      chatId: "existing-chat",
      createdAt: "2026-08-06T10:00:00Z",
      updatedAt: "2026-08-06T10:00:00Z",
      preview: "Existing topic",
    }];
    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    const heroHeader = screen.getByTestId("thread-header");
    const heroTemporaryToggle = within(heroHeader).getByRole("button", {
      name: "Temporary chat",
    });
    const themeToggle = within(heroHeader).getByRole("button", {
      name: "Toggle theme from header",
    });
    expect(within(sidebar).queryByRole("button", { name: "Temporary chat" })).not.toBeInTheDocument();
    expect(within(screen.getByTestId("thread-composer-motion")).queryByRole("button", {
      name: "Temporary chat",
    })).not.toBeInTheDocument();
    expect(heroTemporaryToggle.compareDocumentPosition(themeToggle)
      & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    const user = userEvent.setup();
    await user.hover(heroTemporaryToggle);
    const temporaryTooltip = await screen.findByRole("tooltip");
    expect(temporaryTooltip).toHaveTextContent("Temporary chat");
    expect(temporaryTooltip).toHaveTextContent("Not saved to history or memory");
    expect(within(temporaryTooltip).getByText(
      "Reloading, closing, or losing the connection ends these chats.",
    )).toHaveClass("font-medium");
    await user.unhover(heroTemporaryToggle);

    fireEvent.click(within(sidebar).getByText("Existing topic"));
    expect(window.location.hash).toBe("#/chat/websocket%3Aexisting-chat");
    expect(screen.queryByRole("button", { name: "Temporary chat" })).not.toBeInTheDocument();

    fireEvent.click(within(sidebar).getByRole("button", { name: "New topic" }));
    const temporaryToggle = screen.getByRole("button", { name: "Temporary chat" });
    expect(temporaryToggle).toHaveClass("h-8", "w-8", "rounded-full");
    expect(within(temporaryToggle).queryByText("Temporary chat")).not.toBeInTheDocument();
    fireEvent.click(temporaryToggle);
    expect(temporaryToggle).toHaveAttribute("aria-pressed", "true");
    expect(temporaryToggle).toHaveClass("bg-transparent", "shadow-none", "hover:bg-transparent");
    expect(within(temporaryToggle).getByTestId("temporary-chat-icon")).toHaveClass(
      "motion-safe:duration-150",
      "text-[var(--temporary-control-active)]",
    );
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(screen.queryByTestId("temporary-chat-outline")).not.toBeInTheDocument();
    fireEvent.click(temporaryToggle);
    expect(temporaryToggle).toHaveAttribute("aria-pressed", "false");
    expect(within(temporaryToggle).getByTestId("temporary-chat-icon")).toHaveClass(
      "motion-safe:duration-75",
      "text-current",
    );
    fireEvent.click(temporaryToggle);
    expect(window.location.hash).toBe("#/new");
    expect(temporaryToggle).toHaveAttribute("aria-pressed", "true");

    fireEvent.change(screen.getByLabelText("Message input"), {
      target: { value: "start temporary chat" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(window.location.hash).toMatch(/^#\/temporary\/[0-9a-f-]+$/));

    expect(screen.queryByText("Not saved")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear temporary chat" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Temporary chat" })).not.toBeInTheDocument();
  });

  it("allows leaving a page with temporary chats without blocking", async () => {
    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Temporary chat" }));
    fireEvent.change(screen.getByLabelText("Message input"), {
      target: { value: "do not lose this" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(window.location.hash).toMatch(/^#\/temporary\/[0-9a-f-]+$/));

    const beforeUnload = new Event("beforeunload", { cancelable: true });
    act(() => window.dispatchEvent(beforeUnload));
    expect(beforeUnload.defaultPrevented).toBe(false);
  });

  it("ends temporary chats quietly after a connection interruption", async () => {
    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    act(() => {
      statusHandlers.forEach((handler) => handler("open"));
    });
    fireEvent.click(screen.getByRole("button", { name: "Temporary chat" }));
    fireEvent.change(screen.getByLabelText("Message input"), {
      target: { value: "connection-sensitive message" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(window.location.hash).toMatch(/^#\/temporary\/[0-9a-f-]+$/));

    act(() => {
      statusHandlers.forEach((handler) => handler("reconnecting"));
    });

    await waitFor(() => expect(window.location.hash).toBe("#/new"));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText("connection-sensitive message")).not.toBeInTheDocument();
  });

  it("uses the restricted default scope without offering project selection", async () => {
    mockFetchRoutes({
      "/api/workspaces": {
        schema_version: 1,
        default_access_mode: "full",
        default_scope: {
          project_path: "/tmp/workspace",
          project_name: "workspace",
          access_mode: "full",
          restrict_to_workspace: false,
        },
        controls: { can_change_project: true, can_use_full_access: true },
      },
    });
    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    expect(await screen.findByRole("button", { name: "Choose project" })).toBeInTheDocument();
    act(() => {
      sessionUpdateHandlers.forEach((handler) => handler("selected-chat", "metadata", {
        project_path: "/tmp/selected-project",
        project_name: "selected-project",
        access_mode: "full",
        restrict_to_workspace: false,
      }));
    });
    fireEvent.click(screen.getByRole("button", { name: "Temporary chat" }));

    expect(screen.queryByRole("button", { name: "Choose project" })).not.toBeInTheDocument();
    expect(screen.queryByText("Full Access")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Message input"), {
      target: { value: "temporary project check" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(sendMessageSpy).toHaveBeenCalled());
    const options = sendMessageSpy.mock.calls.at(-1)?.[3];
    expect(options?.workspaceScope).toMatchObject({
      project_path: "/tmp/workspace",
      access_mode: "restricted",
      restrict_to_workspace: true,
    });
  });

  it("preserves the first message when the gateway rejects a project", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    createChatSpy.mockRejectedValueOnce(
      new Error("workspace_scope_rejected:project_path must be an existing directory"),
    );
    mockFetchRoutes({
      "/api/workspaces": {
        schema_version: 1,
        default_access_mode: "restricted",
        default_scope: {
          project_path: "C:\\workspace",
          project_name: "workspace",
          access_mode: "restricted",
          restrict_to_workspace: true,
        },
        controls: { can_change_project: true, can_use_full_access: true },
      },
    });

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    fireEvent.click(await screen.findByRole("button", { name: "Choose project" }));
    fireEvent.change(await screen.findByLabelText("Paste path"), {
      target: { value: "C:\\missing-project" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Use Path" }));

    const message = screen.getByLabelText("Message input");
    fireEvent.change(message, { target: { value: "keep this first message" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => expect(createChatSpy).toHaveBeenCalledTimes(1));
    expect(message).toHaveValue("keep this first message");
    const projectButton = screen.getByRole("button", { name: "Choose project" });
    await waitFor(() => expect(projectButton).toHaveFocus());
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The gateway rejected this project or access mode. Choose an existing project or a different access mode, then try again.",
    );
    fireEvent.click(projectButton);
    const projectPath = await screen.findByLabelText("Paste path");
    expect(projectPath).toHaveValue("C:\\missing-project");
    expect(projectPath).toHaveAttribute("aria-invalid", "true");
    expect(projectPath).toHaveFocus();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The gateway rejected this project or access mode. Choose an existing project or a different access mode, then try again.",
    );
    expect(window.location.hash).toBe("");
    consoleError.mockRestore();
  });

  it("restores the Settings route after a restart fallback hash", async () => {
    localStorage.setItem("nanobot-webui.restartStartedAt", String(Date.now()));
    localStorage.setItem("nanobot-webui.restartRoute", "#/settings?section=channels");
    window.history.replaceState(null, "", "/#/new");
    mockFetchRoutes({
      "/api/settings": baseSettingsPayload(),
      "/api/settings/nanobot-features": {
        features: [{
          name: "websocket",
          display_name: "Websocket",
          type: "channel",
          enabled: true,
          installed: true,
          ready: true,
          status: "enabled",
          install_supported: true,
          requires_restart: true,
        }],
        enabled_count: 1,
      },
    });

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    expect(
      await screen.findByRole("navigation", { name: "Settings sections" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Channels" })).not.toBeInTheDocument();
    expect(window.location.hash).toBe("#/settings?section=channels");
  });

  it("opens Skills from the main sidebar", async () => {
    const longSkillDescription = [
      "Work with GitHub repositories, issues, pull requests, releases, workflows,",
      "and code search through the GitHub CLI.",
      "Use this skill for repository maintenance, review automation, release preparation,",
      "and other GitHub workflows that need authenticated command-line access.",
    ].join(" ");
    mockFetchRoutes({
      "/api/settings": baseSettingsPayload(),
      "/api/settings/cli-apps": { apps: [], installed_count: 0, catalog_updated_at: "2026-04-18" },
      "/api/settings/mcp-presets": { presets: [], installed_count: 0 },
      "/api/webui/skills": {
        skills: [
          {
            name: "cron",
            description: "Schedule reminders.",
            source: "builtin",
            enabled: true,
            deletable: false,
            available: true,
          },
          {
            name: "github",
            description: "Work with GitHub.",
            source: "builtin",
            enabled: true,
            deletable: false,
            available: false,
            unavailable_reason: "CLI: gh",
          },
          {
            name: "custom-skill",
            description: "A workspace skill.",
            source: "workspace",
            enabled: true,
            deletable: true,
            available: true,
          },
        ],
      },
      "/api/webui/skills/github": {
        name: "github",
        description: longSkillDescription,
        source: "builtin",
        enabled: true,
        deletable: false,
        available: false,
        unavailable_reason: "CLI: gh",
        requirements: {
          bins: ["gh"],
          env: [],
          missing_bins: ["gh"],
          missing_env: [],
        },
        install_options: [{
          id: "brew",
          kind: "brew",
          label: "Install GitHub CLI (brew)",
          command: "brew install gh",
        }],
        raw_markdown: "---\nname: github\n---\nUse GitHub CLI.",
      },
    });
    requestMutationSpy.mockResolvedValueOnce({
      skills: [
        {
          name: "cron",
          description: "Schedule reminders.",
          source: "builtin",
          enabled: true,
          deletable: false,
          available: true,
        },
        {
          name: "github",
          description: "Work with GitHub.",
          source: "builtin",
          enabled: false,
          deletable: false,
          available: false,
          unavailable_reason: "CLI: gh",
        },
        {
          name: "custom-skill",
          description: "A workspace skill.",
          source: "workspace",
          enabled: true,
          deletable: true,
          available: true,
        },
      ],
      last_action: { name: "github", enabled: false, deleted: false },
    });

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    const skillsButton = within(sidebar).getByRole("button", { name: "Skills" });

    fireEvent.click(skillsButton);

    expect(await screen.findByRole("heading", { name: "Skills" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Search installed skills" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Custom" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Built-in" })).toBeInTheDocument();
    expect(screen.getByText("cron")).toBeInTheDocument();
    expect(screen.getByText("github")).toBeInTheDocument();
    expect(screen.getByText("Needs setup")).toBeInTheDocument();
    expect(
      screen.queryByText("Review the instruction skills this agent can load during a conversation."),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Sidebar navigation" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Settings sections" })).not.toBeInTheDocument();
    expect(within(sidebar).getByRole("button", { name: "Skills" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(document.title).toBe("Skills · nanobot");

    fireEvent.click(screen.getByRole("button", { name: "Back to chat" }));
    expect(await screen.findByText(HERO_GREETING_PATTERN)).toBeInTheDocument();

    fireEvent.click(within(sidebar).getByRole("button", { name: "Skills" }));
    expect(await screen.findByRole("heading", { name: "Skills" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open details for github" }));

    expect(await screen.findByRole("heading", { name: "github" })).toBeInTheDocument();
    const showMore = await screen.findByRole("button", { name: "Show more" });
    expect(showMore).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(showMore);
    expect(screen.getByRole("button", { name: "Show less" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByText("Setup required")).toBeInTheDocument();
    expect(
      screen.queryByText(
        "Allow the agent to load this skill when its requirements are ready.",
      ),
    ).not.toBeInTheDocument();
    expect(screen.getByText("brew install gh")).toBeInTheDocument();
    expect(screen.queryByText("Unavailable reason")).not.toBeInTheDocument();
    expect(screen.queryByText("Missing CLI")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check again" })).toBeInTheDocument();
    fireEvent.click(screen.getByText("Skill instructions"));
    expect(screen.getByText(/Use GitHub CLI/)).toBeInTheDocument();
    const enabledSwitch = screen.getByRole("switch", { name: "Disable github" });
    expect(enabledSwitch).toHaveAttribute("aria-checked", "true");
    fireEvent.click(enabledSwitch);
    await waitFor(() => {
      expect(screen.getByRole("switch", { name: "Enable github" })).toHaveAttribute(
        "aria-checked",
        "false",
      );
    });
  });

  it("deletes a custom skill from its detail sheet", async () => {
    mockFetchRoutes({
      "/api/settings": baseSettingsPayload(),
      "/api/settings/cli-apps": { apps: [], installed_count: 0, catalog_updated_at: "2026-04-18" },
      "/api/settings/mcp-presets": { presets: [], installed_count: 0 },
      "/api/webui/skills": {
        skills: [
          {
            name: "custom-skill",
            description: "A workspace skill.",
            source: "workspace",
            enabled: true,
            deletable: true,
            available: true,
          },
        ],
      },
      "/api/webui/skills/custom-skill": {
        name: "custom-skill",
        description: "A workspace skill.",
        source: "workspace",
        enabled: true,
        deletable: true,
        available: true,
        requirements: {
          bins: [],
          env: [],
          missing_bins: [],
          missing_env: [],
        },
        raw_markdown: "---\nname: custom-skill\n---\nWorkspace instructions.",
      },
    });
    requestMutationSpy.mockResolvedValueOnce({
      skills: [],
      last_action: { name: "custom-skill", enabled: false, deleted: true },
    });

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    fireEvent.click(within(sidebar).getByRole("button", { name: "Skills" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Open details for custom-skill" }),
    );
    expect(await screen.findByRole("heading", { name: "custom-skill" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(screen.getByRole("heading", { name: "Delete custom-skill?" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete skill" }));

    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: "Open details for custom-skill" }),
      ).not.toBeInTheDocument();
    });
    expect(screen.getByText("No matching skills.")).toBeInTheDocument();
  });

  it("discovers and installs a skill from skills.sh", async () => {
    let finishInstall!: (value: unknown) => void;
    const pendingInstall = new Promise<unknown>((resolve) => {
      finishInstall = resolve;
    });
    const installedPayload = {
      skills: [
        {
          name: "react-testing",
          description: "Test React apps.",
          source: "workspace",
          available: true,
        },
        { name: "cron", description: "Schedule reminders.", source: "builtin", available: true },
      ],
      last_action: {
        installed: true,
        already_installed: false,
        name: "react-testing",
      },
    };
    mockFetchRoutes({
      "/api/settings": baseSettingsPayload(),
      "/api/settings/cli-apps": { apps: [], installed_count: 0, catalog_updated_at: "2026-04-18" },
      "/api/settings/mcp-presets": { presets: [], installed_count: 0 },
      "/api/webui/skills": {
        skills: [
          { name: "cron", description: "Schedule reminders.", source: "builtin", available: true },
        ],
      },
      "/api/webui/skills/trending?provider=all": {
        period: "mixed",
        provider: "all",
        install_supported: true,
        skills: [
          {
            id: "vercel-labs/skills/find-skills",
            skill_id: "find-skills",
            name: "find-skills",
            source: "vercel-labs/skills",
            provider: "skills_sh",
            installs: 14_481,
            url: "https://skills.sh/vercel-labs/skills/find-skills",
            installed: false,
            install_supported: true,
            metric: "installs_24h",
            rank: 18,
          },
          {
            id: "skillhub:ima-skills",
            skill_id: "ima-skills",
            name: "ima-skills",
            source: "@tencent-adm/ima-skills",
            provider: "skillhub",
            installs: 11_831,
            downloads: 142_525,
            url: "https://skillhub.cn/tencent-adm/ima-skills",
            installed: false,
            install_supported: true,
            metric: "installs_total",
            version: "1.1.8",
            verified: true,
            rank: 1,
          },
        ],
      },
      "/api/webui/skills/trends?id=vercel-labs%2Fskills%2Ffind-skills": {
        trends: {
          "vercel-labs/skills/find-skills": [20, 32, 28, 45, 41, 50, 62, 58],
        },
      },
      "/api/webui/skills/search?q=React&provider=all": {
        query: "React",
        provider: "all",
        install_supported: true,
        skills: [
          {
            id: "acme/agent-skills/react-testing",
            skill_id: "react-testing",
            name: "React Testing",
            source: "acme/agent-skills",
            provider: "skills_sh",
            installs: 42,
            url: "https://skills.sh/acme/agent-skills/react-testing",
            installed: false,
            install_supported: true,
            metric: "installs_total",
          },
          {
            id: "skillhub:react",
            skill_id: "react",
            name: "React",
            source: "@ivangdavila/react",
            provider: "skillhub",
            installs: 693,
            downloads: 7_718,
            url: "https://skillhub.cn/ivangdavila/react",
            installed: false,
            install_supported: true,
            metric: "installs_total",
            version: "1.0.4",
          },
        ],
      },
      "/api/webui/skills/trends?id=acme%2Fagent-skills%2Freact-testing": {
        trends: { "acme/agent-skills/react-testing": [] },
      },
    });
    requestMutationSpy.mockImplementationOnce(() => pendingInstall);

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    fireEvent.click(within(sidebar).getByRole("button", { name: "Skills" }));
    const discoverTab = await screen.findByRole("tab", { name: "Discover" });
    expect(discoverTab.querySelector("svg")).toBeNull();
    fireEvent.click(discoverTab);
    expect(
      await screen.findByRole("heading", { name: "Trending by marketplace" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Each marketplace keeps its own ranking and install metrics."),
    ).not.toBeInTheDocument();
    expect(screen.getByText("find-skills")).toBeInTheDocument();
    expect(screen.getByText("ima-skills")).toBeInTheDocument();
    expect(screen.getAllByText("SkillHub")).toHaveLength(2);
    expect(screen.getAllByText("skills.sh")).toHaveLength(2);
    expect(screen.getByText(/14,481 installs \/ 24h/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "SkillHub" }));
    expect(screen.getByText("ima-skills")).toBeInTheDocument();
    expect(screen.queryByText("find-skills")).not.toBeInTheDocument();
    expect(
      vi.mocked(fetch).mock.calls.some(
        ([input]) =>
          String(input) === "/api/webui/skills/trending?provider=skillhub",
      ),
    ).toBe(false);
    fireEvent.click(screen.getByRole("tab", { name: "All" }));
    expect(screen.getByText("find-skills")).toBeInTheDocument();
    expect(screen.getByText("ima-skills")).toBeInTheDocument();
    expect(
      await screen.findByRole("img", { name: "8-week install trend" }),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Search skills" }), {
      target: { value: "React" },
    });

    expect(await screen.findByText("React Testing")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Install React Testing" }));
    expect(
      await screen.findByRole("heading", { name: "Install React Testing?" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Install skill" }));

    await waitFor(() => {
      expect(requestMutationSpy).toHaveBeenCalledWith(
        "skill.install",
        {
          provider: "skills_sh",
          source: "acme/agent-skills",
          skill: "react-testing",
        },
        150_000,
      );
    });
    fireEvent.click(screen.getByRole("tab", { name: "Installed" }));
    fireEvent.click(screen.getByRole("tab", { name: "Discover" }));
    expect(
      await screen.findByRole("button", { name: "Install find-skills" }),
    ).toBeDisabled();

    await act(async () => {
      finishInstall(installedPayload);
      await pendingInstall;
    });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Install find-skills" })).toBeEnabled();
    });
    fireEvent.click(screen.getByRole("tab", { name: "Installed" }));
    expect(screen.getByText("react-testing")).toBeInTheDocument();
  });

  it("opens Automations from the main sidebar", async () => {
    mockFetchRoutes({
      "/api/settings": baseSettingsPayload(),
      "/api/webui/automations": {
        jobs: [
          {
            id: "job-1",
            name: "Daily repo check",
            enabled: true,
            protected: false,
            delete_after_run: false,
            schedule: { kind: "every", every_ms: 86_400_000 },
            payload: {
              message: "Check the repo status",
              kind: "agent_turn",
            },
            state: {
              next_run_at_ms: Date.UTC(2026, 3, 17, 10, 0, 0),
              last_status: "ok",
              pending: false,
              run_history: [],
            },
            origin: {
              session_key: "websocket:chat-a",
              channel: "websocket",
              chat_id: "chat-a",
              title: "Release prep",
              preview: "Check release blockers",
            },
          },
          {
            id: "external-quiz",
            name: "WeChat quiz",
            enabled: true,
            protected: false,
            delete_after_run: false,
            schedule: { kind: "cron", expr: "30 9-23 * * *", tz: "Asia/Shanghai" },
            payload: {
              message: "Send a quiz",
              kind: "agent_turn",
            },
            state: {
              next_run_at_ms: Date.UTC(2026, 3, 17, 11, 30, 0),
              last_status: "ok",
              pending: false,
              run_history: [],
            },
            origin: {
              channel: "weixin",
              title: "",
              preview: "",
            },
          },
          {
            id: "heartbeat",
            name: "heartbeat",
            enabled: true,
            protected: true,
            schedule: { kind: "every", every_ms: 60_000 },
            payload: { message: "", kind: "system_event" },
            state: { next_run_at_ms: null, pending: false, run_history: [] },
            origin: null,
          },
        ],
      },
    });

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    const automationsButton = within(sidebar).getByRole("button", {
      name: "Automations",
    });

    fireEvent.click(automationsButton);

    const heading = await screen.findByRole("heading", { name: "Automations" });
    expect(heading).toBeInTheDocument();
    const automationsMain = heading.closest("main");
    expect(automationsMain).not.toBeNull();
    expect(within(automationsMain as HTMLElement).queryByText("Settings")).not.toBeInTheDocument();
    expect(screen.getAllByText("Daily repo check").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Check the repo status").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Release prep").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("WeChat quiz")).toBeInTheDocument();
    expect(screen.getByText("WeChat")).toBeInTheDocument();
    expect(screen.queryByText("weixin:wx-chat")).not.toBeInTheDocument();
    expect(screen.queryByText("memory with dream state")).not.toBeInTheDocument();
    expect(screen.getByText("heartbeat")).toBeInTheDocument();
    expect(within(sidebar).getByRole("button", { name: "Automations" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(document.title).toBe("Automations · nanobot");

    const searchInput = within(automationsMain as HTMLElement).getByPlaceholderText(
      "Search task, message, linked chat, or schedule",
    );
    fireEvent.change(searchInput, { target: { value: "WeChat" } });
    await waitFor(() => expect(screen.queryByText("Daily repo check")).not.toBeInTheDocument());
    expect(screen.getAllByText("WeChat quiz").length).toBeGreaterThanOrEqual(1);

    fireEvent.change(searchInput, { target: { value: "09-23" } });
    await waitFor(() => expect(screen.queryByText("Daily repo check")).not.toBeInTheDocument());
    expect(screen.getAllByText("WeChat quiz").length).toBeGreaterThanOrEqual(1);
  });

  it("edits a past one-time automation without resubmitting its old schedule", async () => {
    const pastOneShot = {
      id: "past-one-shot",
      name: "Past one-shot",
      enabled: true,
      protected: false,
      delete_after_run: true,
      schedule: { kind: "at", at_ms: 1 },
      payload: {
        message: "Old one-shot message",
        kind: "agent_turn",
      },
      state: {
        next_run_at_ms: null,
        last_status: "ok",
        pending: false,
        run_history: [],
      },
      origin: {
        session_key: "websocket:chat-a",
        channel: "websocket",
        chat_id: "chat-a",
        title: "Release prep",
        preview: "Check release blockers",
      },
    };
    mockFetchRoutes({
      "/api/settings": baseSettingsPayload(),
      "/api/webui/automations": { jobs: [pastOneShot] },
    });
    requestMutationSpy.mockResolvedValueOnce({
      jobs: [{
        ...pastOneShot,
        payload: { ...pastOneShot.payload, message: "Updated one-shot message" },
      }],
    });

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    fireEvent.click(within(sidebar).getByRole("button", { name: "Automations" }));

    expect((await screen.findAllByText("Past one-shot")).length).toBeGreaterThanOrEqual(1);
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(screen.queryByText("Run time must be in the future.")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Update the prompt and schedule. The linked chat stays unchanged."),
    ).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("Old one-shot message")).toHaveClass(
      "min-h-[160px]",
      "resize-none",
    );

    fireEvent.change(screen.getByDisplayValue("Old one-shot message"), {
      target: { value: "Updated one-shot message" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(requestMutationSpy).toHaveBeenCalledWith(
        "automation.update",
        {
          id: "past-one-shot",
          values: {
            name: "Past one-shot",
            message: "Updated one-shot message",
          },
        },
        20_000,
      );
    });
  });

  it("keeps long automation details expandable without nested scrolling", async () => {
    const longMessage = [
      "Review the release plan and prepare a concise status update for the channel.",
      "Include blockers, owners, follow-up dates, and any risky assumptions that changed since yesterday.",
      "Keep the output actionable and avoid repeating context that the team already confirmed in the thread.",
      "If a dependency looks stale, call it out explicitly and ask for a fresh owner update.",
      "This message is intentionally long enough to require progressive disclosure in the automation details panel.",
      "The full content should remain available without forcing the user into a small nested scroll area.",
    ].join("\n");
    const history = [
      { run_at_ms: Date.UTC(2026, 3, 12, 10, 0, 0), status: "error", duration_ms: 900, error: "oldest failure" },
      { run_at_ms: Date.UTC(2026, 3, 13, 10, 0, 0), status: "error", duration_ms: 800, error: "second oldest failure" },
      { run_at_ms: Date.UTC(2026, 3, 14, 10, 0, 0), status: "ok", duration_ms: 700 },
      { run_at_ms: Date.UTC(2026, 3, 15, 10, 0, 0), status: "ok", duration_ms: 600 },
      { run_at_ms: Date.UTC(2026, 3, 16, 10, 0, 0), status: "ok", duration_ms: 500 },
      { run_at_ms: Date.UTC(2026, 3, 17, 10, 0, 0), status: "ok", duration_ms: 400 },
    ];
    mockFetchRoutes({
      "/api/settings": baseSettingsPayload(),
      "/api/webui/automations": {
        jobs: [
          {
            id: "long-details",
            name: "Long detail automation",
            enabled: true,
            protected: false,
            delete_after_run: false,
            schedule: { kind: "every", every_ms: 3_600_000 },
            payload: {
              message: longMessage,
              kind: "agent_turn",
            },
            state: {
              next_run_at_ms: Date.UTC(2026, 3, 18, 10, 0, 0),
              last_status: "ok",
              pending: false,
              run_history: history,
            },
            origin: {
              session_key: "websocket:chat-a",
              channel: "websocket",
              chat_id: "chat-a",
              title: "Release prep",
              preview: "Check release blockers",
            },
          },
        ],
      },
    });

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    fireEvent.click(within(sidebar).getByRole("button", { name: "Automations" }));

    const detailHeading = await screen.findByRole("heading", { name: "Long detail automation" });
    const detailPanel = detailHeading.closest("article") as HTMLElement;
    expect(detailPanel).not.toBeNull();
    const message = Array.from(detailPanel.querySelectorAll("section div")).find(
      (node) => node.textContent === longMessage,
    ) as HTMLElement | undefined;
    expect(message).toBeTruthy();
    expect(message!).toHaveClass("line-clamp-6");

    fireEvent.click(within(detailPanel).getByRole("button", { name: "Show full message" }));
    expect(within(detailPanel).getByRole("button", { name: "Show less" })).toBeInTheDocument();
    expect(message!).not.toHaveClass("line-clamp-6");

    expect(within(detailPanel).queryByText("Recent health")).not.toBeInTheDocument();
    expect(within(detailPanel).queryByRole("button", { name: /Run history/ })).not.toBeInTheDocument();
    expect(within(detailPanel).queryByText(/oldest failure/)).not.toBeInTheDocument();
    expect(within(detailPanel).queryByText("No error recorded")).not.toBeInTheDocument();
  });

  it("localizes the Automations surface", async () => {
    await i18n.changeLanguage("zh-CN");
    mockFetchRoutes({
      "/api/settings": baseSettingsPayload(),
      "/api/webui/automations": {
        jobs: [
          {
            id: "job-zh",
            name: "每日检查",
            enabled: true,
            protected: false,
            delete_after_run: false,
            schedule: { kind: "every", every_ms: 86_400_000 },
            payload: {
              message: "检查仓库状态",
              kind: "agent_turn",
            },
            state: {
              next_run_at_ms: Date.UTC(2026, 3, 17, 10, 0, 0),
              last_run_at_ms: Date.UTC(2026, 3, 16, 10, 0, 0),
              last_status: "ok",
              pending: false,
              run_history: [
                {
                  run_at_ms: Date.UTC(2026, 3, 16, 10, 0, 0),
                  status: "ok",
                  duration_ms: 500,
                },
              ],
            },
            origin: {
              session_key: "websocket:chat-a",
              channel: "websocket",
              chat_id: "chat-a",
              title: "发布准备",
              preview: "检查发布阻塞项",
            },
          },
        ],
      },
    });

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "侧边栏导航" });
    fireEvent.click(within(sidebar).getByRole("button", { name: "自动任务" }));

    const heading = await screen.findByRole("heading", { name: "自动任务" });
    expect(heading).toBeInTheDocument();
    const automationsMain = heading.closest("main");
    expect(automationsMain).not.toBeNull();
    expect(within(automationsMain as HTMLElement).queryByText("设置")).not.toBeInTheDocument();
    expect(screen.getByText("任务队列")).toBeInTheDocument();
    expect(screen.getAllByText("每日检查").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("检查仓库状态").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("每 1天")).toBeInTheDocument();
    expect(screen.queryByText("最近健康状态")).not.toBeInTheDocument();
    expect(screen.queryByText("近期无问题")).not.toBeInTheDocument();
    expect(screen.queryByText("Workspace automations")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "刷新" })).not.toBeInTheDocument();
    expect(document.title).toBe("自动任务 · nanobot");
  });

  it("fully collapses the native host sidebar and previews it on hover", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "Desktop chat",
      },
    ];
    vi.mocked(fetchBootstrap).mockResolvedValue({
      token: "tok",
      api_token: "api-tok",
      ws_path: "/",
      expires_in: 300,
      runtime_surface: "native",
    });

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const flowSidebar = screen.getByTestId("host-sidebar-flow");
    const toggle = screen.getByTestId("host-sidebar-toggle");
    expect(flowSidebar).toHaveStyle({ width: "272px" });
    expect(
      screen.getByRole("navigation", { name: "Sidebar navigation" }),
    ).toBeInTheDocument();

    fireEvent.click(toggle);
    await waitFor(() => expect(flowSidebar).toHaveStyle({ width: "0px" }));
    expect(
      screen.queryByRole("navigation", { name: "Sidebar navigation" }),
    ).not.toBeInTheDocument();

    fireEvent.mouseEnter(toggle);
    const previewSidebar = await screen.findByTestId("host-sidebar-preview");
    expect(flowSidebar).toHaveStyle({ width: "0px" });
    expect(previewSidebar).toHaveStyle({ width: "272px" });
    expect(
      within(previewSidebar).getByRole("navigation", {
        name: "Sidebar navigation",
      }),
    ).toBeInTheDocument();

    fireEvent.click(toggle);
    await waitFor(() =>
      expect(screen.queryByTestId("host-sidebar-preview")).not.toBeInTheDocument(),
    );
    expect(flowSidebar).toHaveStyle({ width: "272px" });
    expect(
      screen.getByRole("navigation", { name: "Sidebar navigation" }),
    ).toBeInTheDocument();
  });

  it("switches to the next session when deleting the active chat", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "First chat",
      },
      {
        key: "websocket:chat-b",
        channel: "websocket",
        chatId: "chat-b",
        createdAt: "2026-04-16T11:00:00Z",
        updatedAt: "2026-04-16T11:00:00Z",
        preview: "Second chat",
      },
    ];

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    await waitFor(() =>
      expect(
        within(sidebar).getByRole("button", { name: /^First chat$/ }),
      ).toBeInTheDocument(),
    );

    fireEvent.pointerDown(screen.getByLabelText("Topic actions for First chat"), {
      button: 0,
    });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Delete" }));

    await waitFor(() =>
      expect(screen.getByText("Delete this topic?")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(deleteChatSpy).toHaveBeenCalledWith("websocket:chat-a"),
    );
    await waitFor(() =>
      expect(
        within(sidebar).getByRole("button", { name: /^Second chat$/ }),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText("Delete this topic?")).not.toBeInTheDocument();
    expect(document.body.style.pointerEvents).not.toBe("none");
  }, 15_000);

  it("deletes multiple selected topics through one confirmation", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "First chat",
      },
      {
        key: "websocket:chat-b",
        channel: "websocket",
        chatId: "chat-b",
        createdAt: "2026-04-16T11:00:00Z",
        updatedAt: "2026-04-16T11:00:00Z",
        preview: "Second chat",
      },
      {
        key: "websocket:chat-c",
        channel: "websocket",
        chatId: "chat-c",
        createdAt: "2026-04-16T12:00:00Z",
        updatedAt: "2026-04-16T12:00:00Z",
        preview: "Third chat",
      },
    ];

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    fireEvent.pointerDown(within(sidebar).getByLabelText(
      "Topic actions for First chat",
    ), { button: 0 });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Select" }));
    fireEvent.click(within(sidebar).getByRole("button", { name: "Second chat" }));
    expect(within(sidebar).getByText("2 selected")).toBeInTheDocument();

    fireEvent.click(within(sidebar).getByRole("button", { name: "Delete" }));
    expect(await screen.findByText("Delete 2 conversations?")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(deleteChatSpy).toHaveBeenCalledTimes(2));
    expect(deleteChatSpy.mock.calls.map(([key]) => key)).toEqual([
      "websocket:chat-a",
      "websocket:chat-b",
    ]);
    expect(getSessionAutomationsSpy).toHaveBeenCalledWith("websocket:chat-a");
    expect(getSessionAutomationsSpy).toHaveBeenCalledWith("websocket:chat-b");
    expect(within(sidebar).getByRole("button", { name: "Third chat" }))
      .toBeInTheDocument();
  }, 15_000);

  it("shows localized bound automations in the first delete confirmation", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "First chat",
      },
      {
        key: "websocket:chat-b",
        channel: "websocket",
        chatId: "chat-b",
        createdAt: "2026-04-16T11:00:00Z",
        updatedAt: "2026-04-16T11:00:00Z",
        preview: "Second chat",
      },
    ];
    getSessionAutomationsSpy.mockResolvedValue([
      {
        id: "job-1",
        name: "Daily repo check",
        enabled: true,
        schedule: { kind: "every", every_ms: 86_400_000 },
        payload: { message: "Check the repo" },
        state: { next_run_at_ms: Date.UTC(2026, 3, 17, 10, 0, 0) },
      },
    ]);
    await i18n.changeLanguage("zh-CN");

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "侧边栏导航" });
    await waitFor(() =>
      expect(
        within(sidebar).getByRole("button", { name: /^First chat$/ }),
      ).toBeInTheDocument(),
    );

    fireEvent.pointerDown(screen.getByLabelText(/First chat.*话题操作/), {
      button: 0,
    });
    fireEvent.click(await screen.findByRole("menuitem", { name: "删除" }));

    await waitFor(() =>
      expect(screen.getByText("Daily repo check")).toBeInTheDocument(),
    );
    expect(getSessionAutomationsSpy).toHaveBeenCalledWith("websocket:chat-a");
    expect(
      screen.getByText("这个话题有关联的自动任务。删除话题也会删除这些自动任务。"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("This chat has scheduled automations. Deleting it will also delete them."),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "删除" }));

    await waitFor(() =>
      expect(deleteChatSpy).toHaveBeenCalledWith("websocket:chat-a", {
        deleteAutomations: true,
      }),
    );
    expect(deleteChatSpy).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Daily repo check")).not.toBeInTheDocument();
  }, 15_000);

  it("keeps the mobile session action menu inside the sidebar sheet", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "Existing chat",
      },
    ];
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockImplementation((query: string) => ({
        matches: !query.includes("1024px"),
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    );

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Toggle sidebar" }));

    const sheet = await screen.findByRole("dialog");
    const mobileSidebar = within(sheet).getByRole("navigation", {
      name: "Sidebar navigation",
    });
    await waitFor(() =>
      expect(
        within(mobileSidebar).getByRole("button", { name: /^Existing chat$/ }),
      ).toBeInTheDocument(),
    );

    fireEvent.pointerDown(
      within(mobileSidebar).getByLabelText("Topic actions for Existing chat"),
      { button: 0 },
    );

    const deleteItem = await within(sheet).findByRole("menuitem", {
      name: "Delete",
    });
    expect(deleteItem).toBeInTheDocument();

    fireEvent.click(deleteItem);
    await waitFor(() =>
      expect(screen.getByText("Delete this topic?")).toBeInTheDocument(),
    );
  }, 15_000);

  it("applies persisted sidebar workspace state from the gateway", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "First chat",
      },
      {
        key: "websocket:chat-b",
        channel: "websocket",
        chatId: "chat-b",
        createdAt: "2026-04-16T11:00:00Z",
        updatedAt: "2026-04-16T11:00:00Z",
        preview: "Second chat",
      },
    ];
    const initialState = {
      schema_version: 1,
      pinned_keys: ["websocket:chat-b"],
      archived_keys: ["websocket:chat-a"],
      title_overrides: { "websocket:chat-b": "Roadmap" },
      tags_by_key: {},
      collapsed_groups: {},
      view: {
        density: "comfortable",
        show_previews: false,
        show_timestamps: false,
        show_archived: false,
        sort: "updated_desc",
      },
      updated_at: null,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async (url: string | URL | Request) => {
        const href = String(url);
        if (href === "/api/webui/sidebar-state") {
          return { ok: true, json: async () => initialState };
        }
        return { ok: false, status: 404 };
      }),
    );

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    act(() => {
      statusHandlers.forEach((handler) => handler("open"));
    });
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    await waitFor(() =>
      expect(within(sidebar).getByText("Pinned")).toBeInTheDocument(),
    );
    expect(within(sidebar).getByRole("button", { name: /^Roadmap$/ })).toBeInTheDocument();
    expect(within(sidebar).queryByRole("button", { name: /^First chat$/ })).not.toBeInTheDocument();

    fireEvent.click(within(sidebar).getByRole("button", { name: "Show archived" }));
    await waitFor(() =>
      expect(within(sidebar).getByText("Archived")).toBeInTheDocument(),
    );
    expect(within(sidebar).getByRole("button", { name: /^First chat$/ })).toBeInTheDocument();
    expect(setSidebarStateSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        view: expect.objectContaining({ show_archived: true }),
      }),
    );

    expect(within(sidebar).queryByRole("button", { name: "View" })).not.toBeInTheDocument();
  });

  it("sorts chats by displayed title when A-Z is persisted", async () => {
    mockSessions = [
      {
        key: "websocket:zulu",
        channel: "websocket",
        chatId: "zulu",
        createdAt: "2026-04-16T12:00:00Z",
        updatedAt: "2026-04-16T12:00:00Z",
        title: "Zulu work",
        preview: "later",
      },
      {
        key: "websocket:new",
        channel: "websocket",
        chatId: "new",
        createdAt: "2026-04-15T12:00:00Z",
        updatedAt: "2026-04-15T12:00:00Z",
        preview: "hi nanobot",
      },
      {
        key: "websocket:alpha",
        channel: "websocket",
        chatId: "alpha",
        createdAt: "2026-04-14T12:00:00Z",
        updatedAt: "2026-04-14T12:00:00Z",
        title: "Alpha plan",
        preview: "earlier",
      },
    ];
    const initialState = {
      schema_version: 1,
      pinned_keys: [],
      archived_keys: [],
      title_overrides: {},
      tags_by_key: {},
      collapsed_groups: {},
      view: {
        density: "comfortable",
        show_previews: false,
        show_timestamps: false,
        show_archived: false,
        sort: "title_asc",
      },
      updated_at: null,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async (url: string | URL | Request) => {
        const href = String(url);
        if (href === "/api/webui/sidebar-state") {
          return { ok: true, json: async () => initialState };
        }
        return { ok: false, status: 404 };
      }),
    );

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    await waitFor(() =>
      expect(within(sidebar).getByText("Topics")).toBeInTheDocument(),
    );
    const group = within(sidebar).getByText("Topics").closest("section");
    expect(group).toBeTruthy();
    const labels = within(group as HTMLElement)
      .getAllByRole("button")
      .map((button) => button.textContent?.trim())
      .filter(Boolean);

    expect(labels).toEqual(["Alpha plan", "New topic", "Zulu work"]);
  });

  it("shows running and completed session indicators in the sidebar", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "Working chat",
      },
      {
        key: "websocket:chat-b",
        channel: "websocket",
        chatId: "chat-b",
        createdAt: "2026-04-16T11:00:00Z",
        updatedAt: "2026-04-16T11:00:00Z",
        preview: "Quiet chat",
      },
    ];

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    await waitFor(() =>
      expect(
        within(sidebar).getByRole("button", { name: /^Working chat$/ }),
      ).toBeInTheDocument(),
    );

    act(() => {
      for (const handler of runStatusHandlers) handler("chat-a", 12_345);
    });
    expect(within(sidebar).getByTitle("Agent running")).toBeInTheDocument();

    act(() => {
      for (const handler of runStatusHandlers) handler("chat-a", null);
    });
    expect(within(sidebar).queryByTitle("Agent running")).not.toBeInTheDocument();
    expect(within(sidebar).getByTitle("New activity")).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(within(sidebar).getByRole("button", { name: /^Working chat$/ }));
    });
    expect(within(sidebar).queryByTitle("New activity")).not.toBeInTheDocument();
  });

  it("does not show an updated dot later when the active session finishes", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "Active work",
      },
      {
        key: "websocket:chat-b",
        channel: "websocket",
        chatId: "chat-b",
        createdAt: "2026-04-16T11:00:00Z",
        updatedAt: "2026-04-16T11:00:00Z",
        preview: "Other chat",
      },
    ];

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    await waitFor(() =>
      expect(
        within(sidebar).getByRole("button", { name: /^Active work$/ }),
      ).toBeInTheDocument(),
    );

    await act(async () => {
      fireEvent.click(within(sidebar).getByRole("button", { name: /^Active work$/ }));
    });
    await waitFor(() => expect(document.title).toContain("Active work"));

    act(() => {
      for (const handler of runStatusHandlers) handler("chat-a", 12_345);
    });
    expect(within(sidebar).getByTitle("Agent running")).toBeInTheDocument();

    act(() => {
      for (const handler of runStatusHandlers) handler("chat-a", null);
    });
    expect(within(sidebar).queryByTitle("Agent running")).not.toBeInTheDocument();
    expect(within(sidebar).queryByTitle("New activity")).not.toBeInTheDocument();

    await act(async () => {
      fireEvent.click(within(sidebar).getByRole("button", { name: /^Other chat$/ }));
    });
    expect(within(sidebar).queryByTitle("New activity")).not.toBeInTheDocument();
  });

  it("marks inactive sessions when a thread update arrives", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "Open chat",
      },
      {
        key: "websocket:chat-b",
        channel: "websocket",
        chatId: "chat-b",
        createdAt: "2026-04-16T11:00:00Z",
        updatedAt: "2026-04-16T11:00:00Z",
        preview: "Scheduled update target",
      },
    ];

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    await act(async () => {
      fireEvent.click(within(sidebar).getByRole("button", { name: /^Open chat$/ }));
    });

    act(() => {
      for (const handler of sessionUpdateHandlers) handler("chat-b", "thread");
    });

    expect(within(sidebar).getByTitle("New activity")).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(within(sidebar).getByRole("button", { name: /^Scheduled update target$/ }));
    });

    expect(within(sidebar).queryByTitle("New activity")).not.toBeInTheDocument();
  });

  it("restores sidebar run indicators after a page reload", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "Running after reload",
        runStartedAt: 12_345,
      },
      {
        key: "websocket:chat-b",
        channel: "websocket",
        chatId: "chat-b",
        createdAt: "2026-04-16T11:00:00Z",
        updatedAt: "2026-04-16T11:00:00Z",
        preview: "Completed after reload",
      },
    ];
    localStorage.setItem(
      "nanobot-webui.sidebar.session-updates.v1",
      JSON.stringify(["chat-b"]),
    );

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    await waitFor(() =>
      expect(within(sidebar).getByTitle("Agent running")).toBeInTheDocument(),
    );
    expect(within(sidebar).getByTitle("New activity")).toBeInTheDocument();
    expect(attachSpy).toHaveBeenCalledWith("chat-a");
  });

  it("restores the active chat from the URL hash after a page reload", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "Active after reload",
      },
      {
        key: "websocket:chat-b",
        channel: "websocket",
        chatId: "chat-b",
        createdAt: "2026-04-16T11:00:00Z",
        updatedAt: "2026-04-16T11:00:00Z",
        preview: "Other chat",
      },
    ];
    window.history.replaceState(
      null,
      "",
      `/#/chat/${encodeURIComponent("websocket:chat-a")}`,
    );

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    await waitFor(() => expect(document.title).toBe("Active after reload · nanobot"));
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    expect(
      within(sidebar).getByRole("button", { name: /^Active after reload$/ }),
    ).toBeInTheDocument();
    expect(window.location.hash).toBe(
      `#/chat/${encodeURIComponent("websocket:chat-a")}`,
    );
  });

  it("opens the settings view from the sidebar footer", async () => {
    const user = userEvent.setup();
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "Existing chat",
      },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const href = String(input);
        if (href === "/api/settings/api-service") {
          return jsonResponse({
            installed: false,
            running: false,
            managed: false,
            host: "127.0.0.1",
            port: 8900,
            timeout: 120,
            endpoint: "http://127.0.0.1:8900/v1",
            command: "nanobot serve",
          });
        }
        if (href === "/api/settings/provider-models?provider=openai") {
          return jsonResponse({
            provider: "openai",
            label: "OpenAI",
            status: "available",
            catalog_kind: "official",
            models: [
              { id: "openai/gpt-4o", owned_by: "openai", context_window: 128000 },
              { id: "openai/gpt-4o-mini", owned_by: "openai", context_window: 128000 },
            ],
            model_count: 2,
            fetched_at: 1,
          });
        }
        if (href.includes("/api/settings")) {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              agent: {
                model: "openai/gpt-4o",
                provider: "auto",
                resolved_provider: "openai",
                has_api_key: true,
                model_preset: "primary",
                max_tokens: 8192,
                context_window_tokens: 65536,
                temperature: 0.1,
                reasoning_effort: null,
                timezone: "UTC",
                tool_hint_max_length: 40,
              },
              model_presets: [
                {
                  name: "primary",
                  label: "Primary",
                  active: true,
                  is_default: false,
                  model: "openai/gpt-4o",
                  provider: "auto",
                  resolved_provider: "openai",
                  max_tokens: 8192,
                  context_window_tokens: 65536,
                  temperature: 0.1,
                  reasoning_effort: null,
                },
                {
                  name: "deep",
                  label: "deep",
                  active: false,
                  is_default: false,
                  model: "anthropic/claude-opus-4-5",
                  provider: "anthropic",
                  max_tokens: 8192,
                  context_window_tokens: 200000,
                  temperature: 0.1,
                  reasoning_effort: "high",
                },
              ],
              model_call_order: ["primary", "deep"],
              model_call_order_editable: true,
              providers: [
                {
                  name: "openai",
                  label: "OpenAI",
                  configured: true,
                  api_key_hint: "open••••-key",
                },
                {
                  name: "openrouter",
                  label: "OpenRouter",
                  configured: false,
                  api_key_required: true,
                  default_api_base: "https://openrouter.ai/api/v1",
                },
                {
                  name: "ant_ling",
                  label: "Ant Ling",
                  configured: false,
                  api_key_required: true,
                  default_api_base: "https://api.ant-ling.com/v1",
                },
                {
                  name: "azure_openai",
                  label: "Azure OpenAI",
                  configured: false,
                  api_key_required: true,
                },
                {
                  name: "huggingface",
                  label: "Hugging Face",
                  configured: false,
                  api_key_required: true,
                },
                {
                  name: "siliconflow",
                  label: "SiliconFlow",
                  configured: false,
                  api_key_required: true,
                },
                {
                  name: "volcengine",
                  label: "VolcEngine",
                  configured: false,
                  api_key_required: true,
                },
                {
                  name: "byteplus",
                  label: "BytePlus",
                  configured: false,
                  api_key_required: true,
                },
                {
                  name: "qianfan",
                  label: "Qianfan",
                  configured: false,
                  api_key_required: true,
                },
                {
                  name: "atomic_chat",
                  label: "Atomic Chat",
                  configured: false,
                  api_key_required: false,
                  default_api_base: "http://localhost:1337/v1",
                },
              ],
              web_search: {
                provider: "brave",
                api_key_hint: "BSAo••••ew20",
                base_url: null,
                max_results: 5,
                timeout: 30,
                providers: [
                  { name: "duckduckgo", label: "DuckDuckGo", credential: "none" },
                  { name: "brave", label: "Brave Search", credential: "api_key" },
                  { name: "tavily", label: "Tavily", credential: "api_key" },
                ],
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
                provider_configured: true,
                model: "openai/gpt-5.4-image-2",
                default_aspect_ratio: "1:1",
                default_image_size: "1K",
                max_images_per_turn: 4,
                save_dir: "generated",
                providers: [
                  {
                    name: "openrouter",
                    label: "OpenRouter",
                    configured: true,
                    api_key_hint: "sk-o••••test",
                    api_base: "https://openrouter.ai/api/v1",
                    default_api_base: "https://openrouter.ai/api/v1",
                  },
                  {
                    name: "gemini",
                    label: "Gemini",
                    configured: false,
                    api_key_hint: null,
                    api_base: null,
                    default_api_base: "https://generativelanguage.googleapis.com/v1beta/openai/",
                  },
                ],
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
            }),
          };
        }
        return { ok: false, status: 404, json: async () => ({}) };
      }),
    );

    localStorage.setItem(
      "nanobot-webui.settings-preferences",
      JSON.stringify({ brandLogos: true }),
    );
    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    const searchButton = within(sidebar).getByRole("button", { name: "Search" });
    const appsButton = within(sidebar).getByRole("button", { name: "Apps" });
    expect(searchButton.compareDocumentPosition(appsButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await user.click(within(sidebar).getByRole("button", { name: "Settings" }));

    expect(
      await screen.findByRole("navigation", { name: "Settings sections" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Overview" })).not.toBeInTheDocument();
    expect(document.title).toBe("Settings · nanobot");
    expect(screen.getByTestId("overview-logo-openai")).toBeInTheDocument();
    expect(screen.getByTestId("overview-logo-brave")).toBeInTheDocument();
    expect(screen.getByTestId("overview-logo-openrouter")).toBeInTheDocument();
    expect(screen.queryByTestId("overview-logo-nanobot-gateway")).not.toBeInTheDocument();
    expect(screen.queryByTestId("overview-logo-nanobot-workspace")).not.toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Sidebar navigation" })).not.toBeInTheDocument();
    const settingsNav = screen.getByRole("navigation", { name: "Settings sections" });
    expect(settingsNav.className).not.toContain("overflow-x-auto");
    expect(within(settingsNav).getByRole("button", { name: "Settings: Overview" })).toBeInTheDocument();
    expect(within(settingsNav).getByRole("button", { name: "Overview" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(settingsNav).getByRole("button", { name: "Models" })).toBeInTheDocument();
    expect(within(settingsNav).queryByRole("button", { name: "Providers" })).not.toBeInTheDocument();
    expect(within(settingsNav).getByRole("button", { name: "Image" })).toBeInTheDocument();
    expect(within(settingsNav).queryByRole("button", { name: "Files" })).not.toBeInTheDocument();
    expect(within(settingsNav).getByRole("button", { name: "Web" })).toBeInTheDocument();
    expect(within(settingsNav).queryByRole("button", { name: "Apps" })).not.toBeInTheDocument();
    expect(within(settingsNav).getByRole("button", { name: "Security" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
    fireEvent.pointerDown(within(settingsNav).getByRole("button", { name: "Settings: Overview" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Appearance" }));
    expect(screen.getByText("Brand logos")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Brand logos" })).toBeInTheDocument();
    expect(
      screen.queryByText("Switch between light and dark appearance."),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Choose the language used by the WebUI.")).not.toBeInTheDocument();
    expect(screen.queryByText("Stored only in this browser.")).not.toBeInTheDocument();
    expect(within(settingsNav).getByRole("button", { name: "Settings: Appearance" })).toBeInTheDocument();
    fireEvent.pointerDown(within(settingsNav).getByRole("button", { name: "Settings: Appearance" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Models" }));
    expect(screen.queryByText("AI")).not.toBeInTheDocument();
    expect(screen.getByText("Model presets")).toBeInTheDocument();
    expect(screen.queryByText("Model call order")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "New model preset" }));
    expect(screen.queryByRole("dialog", { name: "New model preset" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("Fast writing"), {
      target: { value: "Fast writing" },
    });
    expect(
      screen
        .getAllByRole("button", { name: /OpenAI/ })
        .some((button) => button.getAttribute("aria-haspopup") === "menu"),
    ).toBe(true);
    await user.click(screen.getByRole("button", { name: "Select model" }));
    await user.click(await screen.findByRole("option", { name: /openai\/gpt-4o-mini/ }));
    expect(screen.getByRole("button", { name: "Save preset" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByText("Up to date.")).not.toBeInTheDocument();
    fireEvent.click(
      within(screen.getByTestId("model-call-order-row-primary")).getAllByRole("button")[0],
    );
    fireEvent.pointerDown(screen.getByRole("button", { name: /Auto/ }));
    expect(screen.getAllByTestId("provider-picker-logo-openai").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("menuitem", { name: /Auto/ }));
    const openModelPicker = async () => {
      const modelButtons = screen.getAllByRole("button", { name: /openai\/gpt-4o/ });
      await user.click(modelButtons[modelButtons.length - 1]);
    };
    await openModelPicker();
    await user.click(await screen.findByRole("option", { name: /openai\/gpt-4o-mini/ }));
    expect(screen.queryByText("Unsaved changes.")).not.toBeInTheDocument();
    expect(screen.getByText("Model providers")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add your own model provider" })).toBeInTheDocument();
    expect(screen.queryByText("OpenRouter")).not.toBeInTheDocument();
    expect(screen.queryByText("Ant Ling")).not.toBeInTheDocument();
    expect(
      screen.queryByText(
        "Bring your own provider keys. Nanobot reads these values from the current config and only configured providers can be used in model presets.",
      ),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("azure_openai")).not.toBeInTheDocument();
    expect(screen.getByTestId("provider-logo-openai")).toBeInTheDocument();
    expect(screen.queryByText(/Product names, logos, and brands/)).not.toBeInTheDocument();
    expect(screen.queryByText("Not configured")).not.toBeInTheDocument();
    const clickProviderRow = async (label: string) => {
      const providerLabel = (await screen.findAllByText(label))
        .find((element) => element.className.includes("font-semibold"));
      expect(providerLabel).toBeTruthy();
      fireEvent.click(providerLabel!);
    };
    const chooseProvider = async (label: string) => {
      fireEvent.pointerDown(
        screen.getByRole("button", { name: "Add your own model provider" }),
      );
      fireEvent.click(await screen.findByRole("menuitem", { name: label }));
    };
    await clickProviderRow("OpenAI");
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByPlaceholderText("Leave blank to keep the current key"), {
      target: { value: "unsaved-openai-key" },
    });
    await clickProviderRow("OpenAI");
    await chooseProvider("OpenRouter");
    await clickProviderRow("OpenRouter");
    await clickProviderRow("OpenAI");
    expect(screen.getByText("open••••-key")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("unsaved-openai-key")).not.toBeInTheDocument();
    await clickProviderRow("OpenAI");
    await chooseProvider("Ant Ling");
    expect(screen.getByDisplayValue("https://api.ant-ling.com/v1")).toBeInTheDocument();
    await clickProviderRow("Ant Ling");
    await chooseProvider("Atomic Chat");
    expect(screen.getByDisplayValue("http://localhost:1337/v1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save provider" })).toBeEnabled();

    fireEvent.click(within(settingsNav).getByRole("button", { name: "Image" }));
    expect(screen.queryByRole("heading", { name: "Image" })).not.toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Image generation" })).toBeInTheDocument();
    expect(screen.getByText("Provider status")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "openai/gpt-5.4-image-2" })).toBeInTheDocument();
    expect(screen.getByText("Save directory")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(
      screen.queryByText(
        "Expose generate_image in chats when a configured image provider is available.",
      ),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Choose a model supported by the selected image provider."),
    ).not.toBeInTheDocument();

    fireEvent.click(within(settingsNav).getByRole("button", { name: "Web" }));
    expect(screen.getByText("Search provider")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Jina reader" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Brave Search/ })).toBeInTheDocument();
    expect(screen.getByTestId("provider-picker-logo-brave")).toBeInTheDocument();
    expect(screen.getByText("BSAo••••ew20")).toBeInTheDocument();
    expect(
      screen.queryByText("Choose the backend used by the web search tool."),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Results returned by each web_search call."),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByPlaceholderText("Leave blank to keep the current key"), {
      target: { value: "unsaved-brave-key" },
    });
    fireEvent.pointerDown(screen.getByRole("button", { name: /Brave Search/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Tavily" }));
    fireEvent.pointerDown(screen.getByRole("button", { name: /Tavily/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Brave Search" }));
    expect(screen.getByText("BSAo••••ew20")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("unsaved-brave-key")).not.toBeInTheDocument();

    fireEvent.click(within(settingsNav).getByRole("button", { name: "System" }));
    expect(screen.queryByText("Regional")).not.toBeInTheDocument();
    expect(screen.getByText("Timezone")).toBeInTheDocument();
    expect(
      screen.queryByText("Used for schedules and time-aware replies."),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Restart nanobot to apply runtime changes."),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Bot name")).not.toBeInTheDocument();
    expect(screen.queryByText("Bot icon")).not.toBeInTheDocument();
    expect(screen.queryByText("Tool hint length")).not.toBeInTheDocument();
    expect(screen.queryByText("Heartbeat")).not.toBeInTheDocument();
    expect(screen.queryByText("Dream")).not.toBeInTheDocument();
    expect(screen.queryByText("Unified session")).not.toBeInTheDocument();
    expect(screen.getByText("Default workspace")).toBeInTheDocument();
    expect(screen.getByText("UTC")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Search timezone")).not.toBeInTheDocument();
    expect(screen.queryByRole("listbox", { name: "Select timezone" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "UTC" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    expect(
      screen.queryByText("Connect SDKs and agents through a local /v1 endpoint."),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("The API uses this local port.")).not.toBeInTheDocument();
  });

  it("restores the settings section from the URL hash after a page reload", async () => {
    mockFetchRoutes({ "/api/settings": baseSettingsPayload() });
    window.history.replaceState(null, "", "/#/settings?section=voice");

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    expect(await screen.findByRole("heading", { name: "Voice input" })).toBeInTheDocument();
    expect(window.location.hash).toBe("#/settings?section=voice");
  });

  it("keeps the backend timezone without writing settings on mount", async () => {
    const initialSettings = baseSettingsPayload();
    mockFetchRoutes({
      "/api/settings": initialSettings,
    });
    window.history.replaceState(null, "", "/#/settings?section=runtime");

    render(<App />);

    expect(await screen.findByText("UTC")).toBeInTheDocument();
    expect(
      requestMutationSpy.mock.calls.some(([action]) => action === "settings.agent.update"),
    ).toBe(false);
    expect(screen.queryByRole("heading", { name: "Regional" })).not.toBeInTheDocument();
    expect(
      screen.queryByText("Used for schedules and time-aware replies."),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Search timezone")).not.toBeInTheDocument();
    const systemSection = screen.getByRole("heading", { name: "System" }).closest("section");
    expect(systemSection).not.toBeNull();
    const system = within(systemSection as HTMLElement);
    const timezoneLabel = system.getByText("Timezone");
    const restartButton = system.getByRole("button", { name: "Restart nanobot" });
    expect(
      timezoneLabel.compareDocumentPosition(restartButton) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      system.queryByText("Restart nanobot to apply runtime changes."),
    ).not.toBeInTheDocument();
  });

  it("falls back to Overview for the retired Files settings URL", async () => {
    mockFetchRoutes({ "/api/settings": baseSettingsPayload() });
    window.history.replaceState(null, "", "/#/settings?section=files");

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    expect(
      await screen.findByRole("navigation", { name: "Settings sections" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Overview" })).not.toBeInTheDocument();
  });

  it("updates the URL hash when switching settings sections", async () => {
    mockFetchRoutes({ "/api/settings": baseSettingsPayload() });

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    fireEvent.click(within(sidebar).getByRole("button", { name: "Settings" }));
    expect(
      await screen.findByRole("navigation", { name: "Settings sections" }),
    ).toBeInTheDocument();
    expect(window.location.hash).toBe("#/settings");

    const settingsNav = screen.getByRole("navigation", { name: "Settings sections" });
    const overviewButton = within(settingsNav).getByRole("button", {
      name: "Overview",
      exact: true,
    });
    const modelsButton = within(settingsNav).getByRole("button", {
      name: "Models",
      exact: true,
    });
    const settingsHighlight = within(settingsNav).getByTestId(
      "settings-selection-highlight",
    );

    expect(overviewButton).toHaveAttribute("aria-current", "page");
    expect(overviewButton).not.toHaveClass("bg-sidebar-accent");
    expect(overviewButton).toHaveClass("transition-[color]");
    expect(settingsHighlight).toHaveAttribute("data-active-id", "overview");

    fireEvent.click(modelsButton);

    expect(await screen.findByText("Model presets")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Models" })).not.toBeInTheDocument();
    expect(window.location.hash).toBe("#/settings?section=models");
    expect(modelsButton).toHaveAttribute("aria-current", "page");
    expect(settingsHighlight).toHaveAttribute("data-active-id", "models");

    const voiceButton = within(settingsNav).getByRole("button", {
      name: "Voice",
      exact: true,
    });
    fireEvent.click(voiceButton);

    expect(await screen.findByRole("heading", { name: "Voice input" })).toBeInTheDocument();
    expect(window.location.hash).toBe("#/settings?section=voice");
    expect(voiceButton).toHaveAttribute("aria-current", "page");
    expect(settingsHighlight).toHaveAttribute("data-active-id", "voice");
  });

  it("transitions between Apps and Skills without replacing the sidebar", async () => {
    mockFetchRoutes({
      "/api/settings": baseSettingsPayload(),
      "/api/settings/cli-apps": { apps: [], installed_count: 0, catalog_updated_at: "2026-04-18" },
      "/api/settings/mcp-presets": { presets: [], installed_count: 0 },
      "/api/webui/skills": { skills: [] },
    });

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    const appsButton = within(sidebar).getByRole("button", { name: "Apps" });

    fireEvent.click(appsButton);

    expect(await screen.findByRole("heading", { name: "Apps" })).toBeInTheDocument();
    expect(screen.queryByText("Add tools to nanobot, then @ them in chat.")).not.toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Sidebar navigation" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Settings sections" })).not.toBeInTheDocument();
    expect(within(sidebar).getByRole("button", { name: "Apps" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(sidebar).getByTestId("actions-selection-highlight")).toHaveAttribute(
      "data-active-id",
      "utility:apps",
    );
    expect(within(sidebar).queryAllByRole("button", { current: "page" })).toHaveLength(1);
    expect(screen.getByTestId("settings-section-transition")).toHaveAttribute(
      "data-settings-section",
      "apps",
    );
    expect(screen.getByTestId("settings-section-transition")).toHaveClass(
      "animate-in",
      "fade-in-0",
      "slide-in-from-bottom-1",
      "duration-200",
      "motion-reduce:animate-none",
    );
    expect(document.title).toBe("Apps · nanobot");

    fireEvent.click(within(sidebar).getByRole("button", { name: "Skills" }));

    expect(await screen.findByRole("heading", { name: "Skills" })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("settings-section-transition")).toHaveAttribute(
        "data-settings-section",
        "skills",
      );
    });
    expect(screen.getByRole("navigation", { name: "Sidebar navigation" })).toBeInTheDocument();
    expect(within(sidebar).getByRole("button", { name: "Skills" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(sidebar).getByTestId("actions-selection-highlight")).toHaveAttribute(
      "data-active-id",
      "utility:skills",
    );
    expect(document.title).toBe("Skills · nanobot");
  });

  it("returns from settings to the blank start page when no session was active", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "First chat",
      },
      {
        key: "websocket:chat-b",
        channel: "websocket",
        chatId: "chat-b",
        createdAt: "2026-04-16T11:00:00Z",
        updatedAt: "2026-04-16T11:00:00Z",
        preview: "Second chat",
      },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes("/api/settings")) {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              agent: {
                model: "openai/gpt-4o",
                provider: "openai",
                resolved_provider: "openai",
                has_api_key: true,
                model_preset: "default",
                max_tokens: 8192,
                context_window_tokens: 65536,
                temperature: 0.1,
                reasoning_effort: null,
                timezone: "UTC",
                tool_hint_max_length: 40,
              },
              model_presets: [
                {
                  name: "default",
                  label: "Default",
                  active: true,
                  is_default: true,
                  model: "openai/gpt-4o",
                  provider: "openai",
                  max_tokens: 8192,
                  context_window_tokens: 65536,
                  temperature: 0.1,
                  reasoning_effort: null,
                },
              ],
              providers: [{ name: "openai", label: "OpenAI", configured: true }],
              web_search: {
                provider: "duckduckgo",
                api_key_hint: null,
                base_url: null,
                max_results: 5,
                timeout: 30,
                providers: [
                  { name: "duckduckgo", label: "DuckDuckGo", credential: "none" },
                  { name: "brave", label: "Brave Search", credential: "api_key" },
                ],
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
                providers: [
                  {
                    name: "openrouter",
                    label: "OpenRouter",
                    configured: false,
                    api_key_hint: null,
                    api_base: null,
                    default_api_base: "https://openrouter.ai/api/v1",
                  },
                ],
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
            }),
          };
        }
        return { ok: false, status: 404, json: async () => ({}) };
      }),
    );

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    fireEvent.click(within(sidebar).getByRole("button", { name: "New topic" }));
    await waitFor(() => expect(document.title).toBe("nanobot"));

    fireEvent.click(within(sidebar).getByRole("button", { name: "Settings" }));
    expect(
      await screen.findByRole("navigation", { name: "Settings sections" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back to chat" }));

    await waitFor(() => expect(document.title).toBe("nanobot"));
    expect(screen.getByText(HERO_GREETING_PATTERN)).toBeInTheDocument();
  });

  it("filters sessions in the centered search dialog", async () => {
    mockSessions = [
      {
        key: "websocket:chat-alpha",
        channel: "websocket",
        chatId: "chat-alpha",
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        title: "Q2 roadmap",
        preview: "Project planning notes",
      },
      {
        key: "websocket:chat-beta",
        channel: "websocket",
        chatId: "chat-beta",
        createdAt: "2026-04-15T10:00:00Z",
        updatedAt: "2026-04-15T10:00:00Z",
        preview: "Travel ideas",
      },
    ];

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    expect(within(sidebar).getByText("Q2 roadmap")).toBeInTheDocument();
    expect(within(sidebar).getByText("Travel ideas")).toBeInTheDocument();
    const newChatButton = within(sidebar).getByRole("button", { name: "New topic" });
    const searchButton = within(sidebar).getByRole("button", { name: "Search" });
    expect(
      newChatButton.compareDocumentPosition(searchButton) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    fireEvent.click(searchButton);
    const dialog = await screen.findByRole("dialog", { name: "Search" });
    expect(dialog).toHaveClass("origin-center");
    expect(dialog.className).not.toContain("translate-x");
    expect(dialog.className).not.toContain("translate-y");
    expect(dialog.querySelector("kbd")).toBeNull();
    expect(within(dialog).getByText("Q2 roadmap")).toBeInTheDocument();
    expect(within(dialog).getByText("Travel ideas")).toBeInTheDocument();
    expect(within(dialog).queryByText("websocket")).not.toBeInTheDocument();
    expect(within(dialog).queryByText("#1")).not.toBeInTheDocument();

    fireEvent.change(within(dialog).getByRole("textbox", { name: "Search" }), {
      target: { value: "planning" },
    });

    expect(within(dialog).getByText("Q2 roadmap")).toBeInTheDocument();
    expect(within(dialog).queryByText("Travel ideas")).not.toBeInTheDocument();
    expect(within(sidebar).getByText("Travel ideas")).toBeInTheDocument();

    fireEvent.change(within(dialog).getByRole("textbox", { name: "Search" }), {
      target: { value: "road q2" },
    });

    expect(within(dialog).getByText("Q2 roadmap")).toBeInTheDocument();
    expect(within(dialog).queryByText("Travel ideas")).not.toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: /Q2 roadmap/ }));

    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Search" })).not.toBeInTheDocument(),
    );
  });

  it("keeps panes adjacent and orders tabs by their latest updated pane", async () => {
    mockSessions = [
      {
        key: "websocket:alpha",
        channel: "websocket",
        chatId: "alpha",
        createdAt: "2026-08-01T10:00:00Z",
        updatedAt: "2026-08-01T10:00:00Z",
        title: "Alpha tab",
        preview: "",
      },
      {
        key: "websocket:alpha-child",
        channel: "websocket",
        chatId: "alpha-child",
        createdAt: "2026-08-05T10:00:00Z",
        updatedAt: "2026-08-05T10:00:00Z",
        title: "Alpha child",
        preview: "",
      },
      {
        key: "websocket:beta",
        channel: "websocket",
        chatId: "beta",
        createdAt: "2026-08-04T10:00:00Z",
        updatedAt: "2026-08-04T10:00:00Z",
        title: "Beta tab",
        preview: "",
      },
    ];
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string | URL | Request) => {
      if (String(url) === "/api/webui/sidebar-state") {
        return {
          ok: true,
          json: async () => ({
            workbench: {
              version: 1,
              tabs: {
                "tab:websocket:alpha": {
                  explicit: true,
                  title: "Alpha tab",
                  paneKeys: ["websocket:alpha", "websocket:alpha-child"],
                  layout: "columns",
                },
                "tab:websocket:beta": {
                  explicit: false,
                  title: null,
                  paneKeys: ["websocket:beta"],
                  layout: "columns",
                },
              },
            },
          }),
        };
      }
      return { ok: false, status: 404 };
    }));

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    const alphaTab = await within(sidebar).findByRole("button", { name: "Tab: Alpha tab" });
    const betaTab = within(sidebar).getByRole("button", { name: "Beta tab" });
    expect(alphaTab.compareDocumentPosition(betaTab) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy();

    const alphaGroup = alphaTab.closest("[data-sidebar-tab-group]") as HTMLElement;
    const paneTitles = within(alphaGroup)
      .getAllByRole("button")
      .filter((button) => (
        button.closest("[data-sidebar-pane]") && button.hasAttribute("title")
      ))
      .map((button) => button.getAttribute("title"));
    expect(paneTitles).toEqual(["Alpha child", "Alpha tab"]);
  });

  it("uses one active pane without workbench editing controls on mobile", async () => {
    vi.stubGlobal("matchMedia", vi.fn((query: string) => ({
      matches: query.includes("max-width: 767px"),
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));
    mockSessions = [
      {
        key: "websocket:alpha",
        channel: "websocket",
        chatId: "alpha",
        createdAt: "2026-08-01T10:00:00Z",
        updatedAt: "2026-08-01T10:00:00Z",
        title: "Alpha tab",
        preview: "",
      },
      {
        key: "websocket:alpha-child",
        channel: "websocket",
        chatId: "alpha-child",
        createdAt: "2026-08-05T10:00:00Z",
        updatedAt: "2026-08-05T10:00:00Z",
        title: "Alpha child",
        preview: "",
      },
    ];
    window.history.replaceState(
      null,
      "",
      "/#/chat/websocket%3Aalpha-child",
    );
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string | URL | Request) => {
      if (String(url) === "/api/webui/sidebar-state") {
        return {
          ok: true,
          json: async () => ({
            workbench: {
              version: 1,
              tabs: {
                "tab:websocket:alpha": {
                  explicit: true,
                  title: "Alpha tab",
                  paneKeys: ["websocket:alpha", "websocket:alpha-child"],
                  layout: "bsp",
                },
              },
            },
          }),
        };
      }
      return { ok: false, status: 404 };
    }));

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const grid = await screen.findByTestId("pane-grid");
    await waitFor(() => expect(Array.from(grid.children).map(
      (pane) => pane.getAttribute("aria-label"),
    )).toEqual(["Alpha child"]));
    expect(screen.queryByRole("button", { name: "Pane layout" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add pane" })).not.toBeInTheDocument();
    expect(screen.queryByRole("separator")).not.toBeInTheDocument();

    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    fireEvent.pointerDown(within(sidebar).getByRole("button", {
      name: "Alpha child pane actions",
    }), { button: 0, ctrlKey: false });
    expect(await screen.findByRole("menuitem", { name: "Delete" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Remove" })).not.toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Move to" })).not.toBeInTheDocument();
  });

  it("materializes a singleton tab without linking it to another pane", async () => {
    mockSessions = [
      {
        key: "websocket:solo",
        channel: "websocket",
        chatId: "solo",
        createdAt: "2026-08-05T10:00:00Z",
        updatedAt: "2026-08-05T10:00:00Z",
        title: "Solo pane",
        preview: "",
      },
      {
        key: "websocket:other",
        channel: "websocket",
        chatId: "other",
        createdAt: "2026-08-04T10:00:00Z",
        updatedAt: "2026-08-04T10:00:00Z",
        title: "Other pane",
        preview: "",
      },
    ];

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    act(() => {
      statusHandlers.forEach((handler) => handler("open"));
    });
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    expect(within(sidebar).queryByRole("button", { name: "Tab: Solo pane" }))
      .not.toBeInTheDocument();
    setSidebarStateSpy.mockClear();

    fireEvent.pointerDown(within(sidebar).getByRole("button", {
      name: "Topic actions for Solo pane",
    }), { button: 0, ctrlKey: false });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Create group" }));

    const tabButton = await within(sidebar).findByRole("button", {
      name: "Tab: Solo pane",
    });
    const tabGroup = tabButton.closest("[data-sidebar-tab-group]") as HTMLElement;
    expect(within(tabGroup).getByRole("list", { name: "Panes in Solo pane" }))
      .toBeInTheDocument();
    expect(within(tabGroup).getAllByRole("button", { name: "Solo pane" }))
      .toHaveLength(1);
    expect(within(sidebar).queryByRole("button", { name: "Tab: Other pane" }))
      .not.toBeInTheDocument();
    await waitFor(() => expect(setSidebarStateSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        workbench: expect.objectContaining({
          tabs: expect.objectContaining({
            "tab:websocket:solo": expect.objectContaining({ explicit: true }),
          }),
        }),
      }),
    ));
  });

  it("restores a created pane group from gateway state after remount", async () => {
    mockSessions = [
      {
        key: "websocket:solo",
        channel: "websocket",
        chatId: "solo",
        createdAt: "2026-08-05T10:00:00Z",
        updatedAt: "2026-08-05T10:00:00Z",
        title: "Solo pane",
        preview: "",
      },
      {
        key: "websocket:other",
        channel: "websocket",
        chatId: "other",
        createdAt: "2026-08-04T10:00:00Z",
        updatedAt: "2026-08-04T10:00:00Z",
        title: "Other pane",
        preview: "",
      },
    ];
    let persistedState: SidebarStatePayload | null = null;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string | URL | Request) => {
      if (String(url) === "/api/webui/sidebar-state") {
        return {
          ok: true,
          json: async () => persistedState ?? {},
        };
      }
      return { ok: false, status: 404 };
    }));
    setSidebarStateSpy.mockImplementation(async (state: SidebarStatePayload) => {
      persistedState = state;
      return state;
    });

    const firstRender = render(<App />);
    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    act(() => {
      statusHandlers.forEach((handler) => handler("open"));
    });
    const firstSidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    fireEvent.pointerDown(within(firstSidebar).getByRole("button", {
      name: "Topic actions for Solo pane",
    }), { button: 0, ctrlKey: false });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Create group" }));
    await waitFor(() => expect(persistedState?.workbench.tabs["tab:websocket:solo"])
      .toEqual(expect.objectContaining({ explicit: true })));

    firstRender.unmount();
    connectSpy.mockClear();

    render(<App />);
    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const secondSidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    expect(await within(secondSidebar).findByRole("button", { name: "Tab: Solo pane" }))
      .toBeInTheDocument();
  });

  it("keeps panes and layout scoped to the current topic tab", async () => {
    vi.stubGlobal("matchMedia", vi.fn((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));
    createChatSpy.mockResolvedValueOnce("chat-pane");
    mockSessions = [
      {
        key: "websocket:chat-alpha",
        channel: "websocket",
        chatId: "chat-alpha",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        title: "Alpha",
        preview: "Alpha notes",
      },
      {
        key: "websocket:chat-beta",
        channel: "websocket",
        chatId: "chat-beta",
        createdAt: "2026-04-16T11:00:00Z",
        updatedAt: "2026-04-16T11:00:00Z",
        title: "Beta",
        preview: "Beta notes",
      },
    ];
    window.history.replaceState(
      null,
      "",
      "/#/chat/websocket%3Achat-alpha",
    );

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const grid = await screen.findByTestId("pane-grid");
    expect(Array.from(grid.children).map((pane) => pane.getAttribute("aria-label")))
      .toEqual(["Alpha"]);
    expect(screen.queryByRole("button", { name: "Pane layout" }))
      .not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Add pane" }));
    expect(screen.queryByRole("dialog", { name: "Search" })).not.toBeInTheDocument();
    await waitFor(() => expect(createChatSpy).toHaveBeenCalledTimes(1));

    await waitFor(() => expect(grid.children).toHaveLength(2));
    expect(screen.getByRole("button", { name: "Pane layout" })).toBeInTheDocument();
    expect(window.location.hash).toBe("#/chat/websocket%3Achat-pane");
    expect(Array.from(grid.children).map((pane) => pane.getAttribute("aria-label")))
      .toEqual(["Alpha", "New topic"]);

    const activeComposer = screen.getByTestId("active-pane-composer");
    const paneInput = within(activeComposer).getByRole("textbox", {
      name: "Message New topic",
    });
    expect(paneInput).toHaveClass("min-h-[50px]");
    fireEvent.change(paneInput, { target: { value: "route this to the new pane" } });
    fireEvent.keyDown(paneInput, { key: "Enter" });
    await waitFor(() => expect(sendMessageSpy).toHaveBeenCalled());
    expect(sendMessageSpy.mock.calls.at(-1)?.[0]).toBe("chat-pane");

    fireEvent.pointerDown(screen.getByRole("button", { name: "Pane layout" }), {
      button: 0,
      ctrlKey: false,
    });
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Rows" }));
    expect(grid).toHaveAttribute("data-layout", "rows");

    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    const paneTopicButton = within(sidebar)
      .getAllByRole("button", { name: "New topic" })
      .find((button) => button.closest("[data-sidebar-pane]"));
    expect(paneTopicButton).toBeDefined();
    expect(paneTopicButton?.closest("[data-sidebar-pane]"))
      .toHaveAttribute("data-sidebar-pane", "websocket:chat-pane");
    fireEvent.click(within(sidebar).getByRole("button", { name: "Beta" }));
    await waitFor(() => {
      const nextGrid = screen.getByTestId("pane-grid");
      expect(Array.from(nextGrid.children).map((pane) => pane.getAttribute("aria-label")))
        .toEqual(["Beta"]);
      expect(nextGrid).toHaveAttribute("data-layout", "columns");
    });

    fireEvent.click(within(sidebar).getByRole("button", { name: "Alpha" }));
    await waitFor(() => {
      const restoredGrid = screen.getByTestId("pane-grid");
      expect(Array.from(restoredGrid.children).map((pane) => pane.getAttribute("aria-label")))
        .toEqual(["Alpha", "New topic"]);
      expect(restoredGrid).toHaveAttribute("data-layout", "rows");
    });

    fireEvent.pointerDown(within(sidebar).getByRole("button", {
      name: "New topic pane actions",
    }), { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByRole("menuitem", {
      name: "Remove",
    }));
    await waitFor(() => expect(screen.getByTestId("pane-grid").children).toHaveLength(1));
    expect(within(sidebar).getAllByRole("button", { name: "New topic" })).toHaveLength(2);
  });

  it("opens search from the keyboard shortcut", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "Existing chat",
      },
    ];

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    fireEvent.keyDown(window, { key: "k", metaKey: true });

    const dialog = await screen.findByRole("dialog", { name: "Search" });
    expect(within(dialog).queryByText("Global actions")).not.toBeInTheDocument();
    expect(within(dialog).getByText("Existing chat")).toBeInTheDocument();

    const textbox = within(dialog).getByRole("textbox", { name: "Search" });
    fireEvent.change(textbox, { target: { value: "missing" } });
    expect(within(dialog).queryByText("Existing chat")).not.toBeInTheDocument();

    fireEvent.change(textbox, { target: { value: "existing" } });
    expect(within(dialog).getByText("Existing chat")).toBeInTheDocument();

    fireEvent.keyDown(textbox, { key: "Enter" });
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Search" })).not.toBeInTheDocument(),
    );
    expect(createChatSpy).not.toHaveBeenCalled();
  });

  it.each([
    ["Command", { metaKey: true }],
    ["Control", { ctrlKey: true }],
  ])("starts a new chat from the %s keyboard shortcut", async (_label, modifier) => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "Existing chat",
      },
    ];

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    fireEvent.keyDown(window, { key: "O", shiftKey: true, ...modifier });

    expect(window.location.hash).toBe("#/new");
  });

  it("closes search when starting a new chat from the keyboard shortcut", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "Existing chat",
      },
    ];

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(await screen.findByRole("dialog", { name: "Search" })).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "O", shiftKey: true, metaKey: true });

    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Search" })).not.toBeInTheDocument(),
    );
    expect(window.location.hash).toBe("#/new");
  });

  it("exposes the new chat keyboard shortcut in the sidebar title", async () => {
    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });

    const newChatButton = within(sidebar).getByRole("button", { name: "New topic" });
    expect(newChatButton).toHaveAttribute(
      "title",
      "New topic (Ctrl+Shift+O)",
    );
    expect(newChatButton).toHaveAttribute(
      "aria-keyshortcuts",
      "Meta+Shift+O Control+Shift+O",
    );
  });

  it("uses macOS shortcut glyphs in the sidebar title", async () => {
    setNavigatorPlatform("MacIntel");
    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });

    expect(within(sidebar).getByRole("button", { name: "New topic" })).toHaveAttribute(
      "title",
      "New topic (⌘⇧O)",
    );
  });

  it("keeps large sidebars light while search still covers every chat", async () => {
    mockSessions = Array.from({ length: 170 }, (_, index) => {
      const chatId = `chat-${index}`;
      return {
        key: `websocket:${chatId}`,
        channel: "websocket" as const,
        chatId,
        createdAt: new Date(Date.UTC(2026, 3, 16, 12, 0 - index)).toISOString(),
        updatedAt: new Date(Date.UTC(2026, 3, 16, 12, 0 - index)).toISOString(),
        title: index === 169 ? "Hidden target" : `Bulk chat ${index}`,
        preview: "",
      };
    });

    render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());
    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    await waitFor(() =>
      expect(within(sidebar).getByRole("button", { name: "Bulk chat 0" })).toBeInTheDocument(),
    );
    expect(within(sidebar).queryByText("Hidden target")).not.toBeInTheDocument();
    expect(within(sidebar).getByRole("button", { name: "Show 10 more" })).toBeInTheDocument();

    fireEvent.click(within(sidebar).getByRole("button", { name: "Search" }));
    const dialog = await screen.findByRole("dialog", { name: "Search" });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Search" }), {
      target: { value: "hidden" },
    });
    expect(within(dialog).getByText("Hidden target")).toBeInTheDocument();
  });

  it("opens a blank start page without creating an empty chat", async () => {
    mockSessions = [
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "Existing chat",
      },
    ];

    const matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: query.includes("1024px"),
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
    vi.stubGlobal("matchMedia", matchMedia);

    const { container } = render(<App />);

    await waitFor(() => expect(connectSpy).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: "Toggle theme from header" }));
    expect(toggleThemeSpy).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    const sidebarAside = container.querySelector("aside.lg\\:block") as HTMLElement;
    await waitFor(() => expect(sidebarAside.style.width).toBe("56px"));

    expect(screen.queryByRole("button", { name: "Start a new topic" })).not.toBeInTheDocument();
    const rail = screen.getByRole("navigation", { name: "Sidebar navigation" });
    expect(within(rail).getByRole("button", { name: "New topic" })).toBeInTheDocument();
    expect(within(rail).getByRole("button", { name: "Search" })).toBeInTheDocument();
    expect(within(rail).queryByRole("button", { name: "View" })).not.toBeInTheDocument();
    expect(within(rail).queryByText("Existing chat")).not.toBeInTheDocument();

    fireEvent.click(within(rail).getByRole("button", { name: "Toggle sidebar" }));
    await waitFor(() => expect(sidebarAside.style.width).toBe("272px"));

    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    fireEvent.click(within(sidebar).getByRole("button", { name: "New topic" }));
    expect(createChatSpy).not.toHaveBeenCalled();
    expect(screen.getByText(HERO_GREETING_PATTERN)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start a new topic" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Toggle theme from header" })).toBeInTheDocument();
    expect(within(sidebar).getByRole("button", { name: "Settings" })).toBeInTheDocument();

    expect(within(sidebar).getByText("Existing chat")).toBeInTheDocument();
  });

  it("refreshes the bootstrap token before REST settings auth expires", async () => {
    vi.useFakeTimers();
    vi.mocked(fetchBootstrap)
      .mockResolvedValueOnce({
        token: "tok-1",
        api_token: "api-tok-1",
        ws_path: "/",
        expires_in: 30,
      })
      .mockResolvedValueOnce({
        token: "tok-2",
        api_token: "api-tok-2",
        ws_path: "/",
        expires_in: 300,
      });
    vi.mocked(deriveWsUrl).mockImplementation(
      (_wsPath: string, token: string) => `ws://test?token=${token}`,
    );

    const { unmount } = render(<App />);
    await act(async () => {});

    expect(connectSpy).toHaveBeenCalled();
    expect(fetchBootstrap).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });

    expect(fetchBootstrap).toHaveBeenCalledTimes(2);
    expect(updateUrlSpy).toHaveBeenCalledWith("ws://test?token=tok-2");
    unmount();
  });

  it("reuses an in-flight pairing poll when the page becomes visible again", async () => {
    let resolvePairing!: (response: Response) => void;
    const pendingPairing = new Promise<Response>((resolve) => {
      resolvePairing = resolve;
    });
    const fetchMock = vi.fn((input: RequestInfo | URL) => (
      String(input) === "/api/settings/pairing"
        ? pendingPairing
        : Promise.resolve({ ok: false, status: 404 } as Response)
    ));
    vi.stubGlobal("fetch", fetchMock);
    const visibilityDescriptor = Object.getOwnPropertyDescriptor(document, "visibilityState");

    const setVisibility = (state: DocumentVisibilityState) => {
      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        value: state,
      });
      document.dispatchEvent(new Event("visibilitychange"));
    };

    try {
      render(<App />);
      await waitFor(() => {
        expect(fetchMock.mock.calls.filter(([input]) => (
          String(input) === "/api/settings/pairing"
        ))).toHaveLength(1);
      });

      act(() => setVisibility("hidden"));
      act(() => setVisibility("visible"));

      expect(fetchMock.mock.calls.filter(([input]) => (
        String(input) === "/api/settings/pairing"
      ))).toHaveLength(1);
      await act(async () => {
        resolvePairing(jsonResponse({ requests: [] }));
        await pendingPairing;
      });
    } finally {
      if (visibilityDescriptor) {
        Object.defineProperty(document, "visibilityState", visibilityDescriptor);
      } else {
        delete (document as Document & {
          visibilityState?: DocumentVisibilityState;
        }).visibilityState;
      }
    }
  });
});
