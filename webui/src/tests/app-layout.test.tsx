import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ChatSummary } from "@/lib/types";

const connectSpy = vi.fn();
const refreshSpy = vi.fn();
const createChatSpy = vi.fn().mockResolvedValue("chat-1");
const deleteChatSpy = vi.fn();
const toggleThemeSpy = vi.fn();
const updateUrlSpy = vi.fn();
let mockSessions: ChatSummary[] = [];

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
        createChat: createChatSpy,
        deleteChat: async (key: string) => {
          await deleteChatSpy(key);
          setSessions((prev: ChatSummary[]) => prev.filter((s) => s.key !== key));
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
  fetchBootstrap: vi.fn().mockResolvedValue({
    token: "tok",
    ws_path: "/",
    expires_in: 300,
  }),
  deriveWsUrl: vi.fn(() => "ws://test"),
  loadSavedSecret: vi.fn(() => ""),
  saveSecret: vi.fn(),
  clearSavedSecret: vi.fn(),
}));

vi.mock("@/lib/nanobot-client", () => {
  class MockClient {
    status = "idle" as const;
    defaultChatId: string | null = null;
    connect = connectSpy;
    onStatus = () => () => {};
    onRuntimeModelUpdate = () => () => {};
    onError = () => () => {};
    onChat = () => () => {};
    onSessionUpdate = () => () => {};
    getRunStartedAt = () => null;
    getGoalState = () => undefined;
    sendMessage = vi.fn();
    newChat = vi.fn();
    attach = vi.fn();
    close = vi.fn();
    updateUrl = updateUrlSpy;
  }

  return { NanobotClient: MockClient };
});

import { deriveWsUrl, fetchBootstrap } from "@/lib/bootstrap";
import App from "@/App";

describe("App layout", () => {
  beforeEach(() => {
    mockSessions = [];
    connectSpy.mockClear();
    updateUrlSpy.mockClear();
    refreshSpy.mockReset();
    createChatSpy.mockClear();
    deleteChatSpy.mockReset();
    toggleThemeSpy.mockReset();
    vi.mocked(fetchBootstrap).mockReset().mockResolvedValue({
      token: "tok",
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
    vi.useRealTimers();
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

    fireEvent.pointerDown(screen.getByLabelText("Chat actions for First chat"), {
      button: 0,
    });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Delete" }));

    await waitFor(() =>
      expect(screen.getByText("Delete this chat?")).toBeInTheDocument(),
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
    expect(screen.queryByText("Delete this chat?")).not.toBeInTheDocument();
    expect(document.body.style.pointerEvents).not.toBe("none");
  }, 15_000);

  it("opens the settings view from the sidebar footer", async () => {
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
        if (String(input).includes("/api/settings")) {
          return {
            ok: true,
            status: 200,
            json: async () => ({
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
                bot_name: "nanobot",
                bot_icon: "nb",
                tool_hint_max_length: 40,
              },
              model_presets: [
                {
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
                ssrf_whitelist_count: 0,
                mcp_server_count: 0,
                exec_enabled: true,
                exec_sandbox: null,
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
    fireEvent.click(within(sidebar).getByRole("button", { name: "Settings" }));

    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
    expect(document.title).toBe("Settings · nanobot");
    expect(screen.queryByRole("navigation", { name: "Sidebar navigation" })).not.toBeInTheDocument();
    const settingsNav = screen.getByRole("navigation", { name: "Settings sections" });
    expect(within(settingsNav).getByRole("button", { name: "Overview" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(settingsNav).getByRole("button", { name: "Models" })).toBeInTheDocument();
    expect(within(settingsNav).getByRole("button", { name: "Providers" })).toBeInTheDocument();
    expect(within(settingsNav).getByRole("button", { name: "Web" })).toBeInTheDocument();
    expect(within(settingsNav).getByRole("button", { name: "Advanced" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
    fireEvent.click(within(settingsNav).getByRole("button", { name: "Models" }));
    expect(screen.getByText("AI")).toBeInTheDocument();
    expect(screen.getByDisplayValue("openai/gpt-4o")).toBeInTheDocument();
    fireEvent.click(within(settingsNav).getByRole("button", { name: "Providers" }));
    expect(screen.getByText("OpenRouter")).toBeInTheDocument();
    expect(screen.getByText("Ant Ling")).toBeInTheDocument();
    expect(screen.getAllByText("Not configured").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByText("OpenAI"));
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByPlaceholderText("Leave blank to keep the current key"), {
      target: { value: "unsaved-openai-key" },
    });
    fireEvent.click(screen.getByText("OpenRouter"));
    fireEvent.click(screen.getByText("OpenAI"));
    expect(screen.getByText("open••••-key")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("unsaved-openai-key")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Ant Ling"));
    expect(screen.getByDisplayValue("https://api.ant-ling.com/v1")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Atomic Chat"));
    expect(screen.getByDisplayValue("http://localhost:1337/v1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();

    fireEvent.click(within(settingsNav).getByRole("button", { name: "Web" }));
    expect(screen.getByText("Search provider")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Brave Search/ })).toBeInTheDocument();
    expect(screen.getByText("BSAo••••ew20")).toBeInTheDocument();
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
                bot_name: "nanobot",
                bot_icon: "nb",
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
                ssrf_whitelist_count: 0,
                mcp_server_count: 0,
                exec_enabled: true,
                exec_sandbox: null,
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
    fireEvent.click(within(sidebar).getByRole("button", { name: "New chat" }));
    await waitFor(() => expect(document.title).toBe("nanobot"));

    fireEvent.click(within(sidebar).getByRole("button", { name: "Settings" }));
    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back to chat" }));

    await waitFor(() => expect(document.title).toBe("nanobot"));
    expect(screen.getByText("What can I do for you?")).toBeInTheDocument();
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
    const newChatButton = within(sidebar).getByRole("button", { name: "New chat" });
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
    const desktopAside = container.querySelector("aside.lg\\:block") as HTMLElement;
    await waitFor(() => expect(desktopAside.style.width).toBe("0px"));

    expect(screen.queryByRole("button", { name: "Start a new chat" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Toggle sidebar" }));
    await waitFor(() => expect(desktopAside.style.width).toBe("272px"));

    const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    fireEvent.click(within(sidebar).getByRole("button", { name: "New chat" }));
    expect(createChatSpy).not.toHaveBeenCalled();
    expect(screen.getByText("What can I do for you?")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start a new chat" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Toggle theme from header" })).toBeInTheDocument();
    expect(within(sidebar).getByRole("button", { name: "Settings" })).toBeInTheDocument();

    expect(within(sidebar).getByText("Existing chat")).toBeInTheDocument();
  });

  it("refreshes the bootstrap token before REST settings auth expires", async () => {
    vi.useFakeTimers();
    vi.mocked(fetchBootstrap)
      .mockResolvedValueOnce({
        token: "tok-1",
        ws_path: "/",
        expires_in: 30,
      })
      .mockResolvedValueOnce({
        token: "tok-2",
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
});
