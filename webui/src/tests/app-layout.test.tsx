import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ChatSummary } from "@/lib/types";

const connectSpy = vi.fn();
const refreshSpy = vi.fn();
const createChatSpy = vi.fn().mockResolvedValue("chat-1");
const deleteChatSpy = vi.fn();
const toggleThemeSpy = vi.fn();
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

vi.mock("@/hooks/useTheme", () => ({
  useTheme: () => ({
    theme: "light" as const,
    toggle: toggleThemeSpy,
  }),
}));

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
    sendMessage = vi.fn();
    newChat = vi.fn();
    attach = vi.fn();
    close = vi.fn();
    updateUrl = vi.fn();
  }

  return { NanobotClient: MockClient };
});

import App from "@/App";

describe("App layout", () => {
  beforeEach(() => {
    mockSessions = [];
    connectSpy.mockClear();
    refreshSpy.mockReset();
    createChatSpy.mockClear();
    deleteChatSpy.mockReset();
    toggleThemeSpy.mockReset();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
      }),
    );
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
              },
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
                  default_api_base: "https://openrouter.ai/api/v1",
                },
              ],
              web_search: {
                provider: "brave",
                api_key_hint: "BSAo••••ew20",
                base_url: null,
                providers: [
                  { name: "duckduckgo", label: "DuckDuckGo", credential: "none" },
                  { name: "brave", label: "Brave Search", credential: "api_key" },
                  { name: "tavily", label: "Tavily", credential: "api_key" },
                ],
              },
              runtime: {
                config_path: "/tmp/config.json",
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

    expect(await screen.findByRole("heading", { name: "General" })).toBeInTheDocument();
    expect(document.title).toBe("Settings · nanobot");
    expect(screen.queryByRole("navigation", { name: "Sidebar navigation" })).not.toBeInTheDocument();
    const settingsNav = screen.getByRole("navigation", { name: "Settings sections" });
    expect(within(settingsNav).getByRole("button", { name: "General" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(settingsNav).getByRole("button", { name: "BYOK" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
    expect(screen.getByText("AI")).toBeInTheDocument();
    expect(screen.getByDisplayValue("openai/gpt-4o")).toBeInTheDocument();
    fireEvent.click(within(settingsNav).getByRole("button", { name: "BYOK" }));
    expect(screen.getByRole("tab", { name: "LLM" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Web Search" })).toBeInTheDocument();
    expect(screen.getByText("OpenRouter")).toBeInTheDocument();
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

    fireEvent.click(screen.getByRole("tab", { name: "Web Search" }));
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

  it("returns from settings to an available chat instead of the blank start page", async () => {
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
              },
              providers: [{ name: "openai", label: "OpenAI", configured: true }],
              web_search: {
                provider: "duckduckgo",
                api_key_hint: null,
                base_url: null,
                providers: [
                  { name: "duckduckgo", label: "DuckDuckGo", credential: "none" },
                  { name: "brave", label: "Brave Search", credential: "api_key" },
                ],
              },
              runtime: {
                config_path: "/tmp/config.json",
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
    expect(await screen.findByRole("heading", { name: "General" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back to chat" }));

    await waitFor(() => expect(document.title).toBe("First chat · nanobot"));
    const restoredSidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
    fireEvent.click(within(restoredSidebar).getByRole("button", { name: /^Second chat$/ }));
    await waitFor(() => expect(document.title).toBe("Second chat · nanobot"));
  });

  it("filters sidebar sessions through the lightweight search row", async () => {
    mockSessions = [
      {
        key: "websocket:chat-alpha",
        channel: "websocket",
        chatId: "chat-alpha",
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
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
    expect(within(sidebar).getByText("Project planning notes")).toBeInTheDocument();
    expect(within(sidebar).getByText("Travel ideas")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("textbox", { name: "Search chats" }), {
      target: { value: "travel" },
    });

    expect(within(sidebar).queryByText("Project planning notes")).not.toBeInTheDocument();
    expect(within(sidebar).getByText("Travel ideas")).toBeInTheDocument();
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
});
