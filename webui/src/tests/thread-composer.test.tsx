import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ThreadComposer } from "@/components/thread/ThreadComposer";
import type { CliAppInfo, McpPresetInfo, SlashCommand } from "@/lib/types";

const COMMANDS: SlashCommand[] = [
  {
    command: "/stop",
    title: "Stop current task",
    description: "Cancel the active agent turn.",
    icon: "square",
  },
  {
    command: "/history",
    title: "Show conversation history",
    description: "Print the last N persisted messages.",
    icon: "history",
    argHint: "[n]",
  },
];

const CLI_APPS: CliAppInfo[] = [
  {
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
    logo_url: "https://example.invalid/gimp.svg",
    brand_color: "#5C5543",
    skill_installed: true,
  },
  {
    name: "blender",
    display_name: "Blender",
    category: "3d",
    description: "3D creation",
    requires: "",
    source: "harness",
    entry_point: "cli-anything-blender",
    install_supported: true,
    installed: true,
    available: true,
    status: "installed",
    logo_url: null,
    brand_color: "#E87D0D",
    skill_installed: true,
  },
  {
    name: "krita",
    display_name: "Krita",
    category: "image",
    description: "Painting",
    requires: "",
    source: "harness",
    entry_point: "cli-anything-krita",
    install_supported: true,
    installed: false,
    available: false,
    status: "not_installed",
    logo_url: null,
    brand_color: "#3BABFF",
    skill_installed: false,
  },
];

const MCP_PRESETS: McpPresetInfo[] = [
  {
    name: "browserbase",
    display_name: "Browserbase",
    category: "browser",
    description: "Cloud browser automation",
    docs_url: "https://docs.browserbase.com",
    transport: "streamableHttp",
    requires: "Browserbase API key",
    note: "",
    install_supported: true,
    installed: true,
    configured: true,
    available: true,
    status: "configured",
    logo_url: "https://example.invalid/browserbase.svg",
    brand_color: "#111827",
    required_fields: [],
    connection_summary: "https://mcp.browserbase.com/mcp",
  },
  {
    name: "figma",
    display_name: "Figma",
    category: "design",
    description: "Design context",
    docs_url: "https://figma.com",
    transport: "streamableHttp",
    requires: "Figma desktop",
    note: "",
    install_supported: true,
    installed: true,
    configured: false,
    available: false,
    status: "missing_credentials",
    logo_url: null,
    brand_color: "#F24E1E",
    required_fields: [],
    connection_summary: "",
  },
];
const ORIGINAL_INNER_HEIGHT = window.innerHeight;

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
  Object.defineProperty(window, "innerHeight", {
    value: ORIGINAL_INNER_HEIGHT,
    configurable: true,
  });
});

function rect(init: Partial<DOMRect>): DOMRect {
  const top = init.top ?? 0;
  const left = init.left ?? 0;
  const width = init.width ?? 0;
  const height = init.height ?? 0;
  return {
    x: init.x ?? left,
    y: init.y ?? top,
    top,
    left,
    width,
    height,
    right: init.right ?? left + width,
    bottom: init.bottom ?? top + height,
    toJSON: () => ({}),
  };
}

describe("ThreadComposer", () => {
  it("renders a readonly hero model composer when provided", () => {
    render(
      <ThreadComposer
        onSend={vi.fn()}
        modelLabel="claude-opus-4-5"
        placeholder="Ask anything..."
        variant="hero"
      />,
    );

    expect(screen.getByText("claude-opus-4-5")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Search" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reason" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Deep research" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Voice input" })).not.toBeInTheDocument();
    const input = screen.getByPlaceholderText("Ask anything...");
    expect(input).toBeInTheDocument();
    expect(input.className).toContain("min-h-[78px]");
    expect(input.parentElement?.parentElement?.className).toContain("max-w-[58rem]");
  });

  it("keeps the thread composer compact while matching the hero style", () => {
    render(
      <ThreadComposer
        onSend={vi.fn()}
        modelLabel="gpt-4o"
        modelProvider="openai"
        modelProviderLabel="OpenAI"
        placeholder="Type your message..."
      />,
    );

    expect(screen.getByText("gpt-4o")).toBeInTheDocument();
    expect(screen.getByTestId("composer-model-logo-openai")).toBeInTheDocument();
    const input = screen.getByPlaceholderText("Type your message...");
    expect(input.className).toContain("min-h-[50px]");
    expect(input.parentElement?.parentElement?.className).toContain("max-w-[49.5rem]");
    expect(input.parentElement?.parentElement?.className).toContain("rounded-[22px]");
    expect(input.parentElement?.parentElement?.className).toContain("shadow-[0_12px_30px_rgba(15,23,42,0.07)]");
    expect(screen.getByRole("button", { name: "Attach image" }).className).toContain("bg-card");
    expect(screen.getByRole("button", { name: "Send message" }).className).toContain("bg-foreground");
  });

  it("shows turn run timer when runStartedAt is set", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date((1_000 + 125) * 1000));

    render(
      <ThreadComposer
        onSend={vi.fn()}
        placeholder="Type your message..."
        runStartedAt={1000}
      />,
    );

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent(/Running/);
    expect(status).toHaveTextContent(/2:05/);

    vi.useRealTimers();
  });

  it("opens an upward anchored goal panel with markdown content when expand is clicked", async () => {
    const longObjective =
      "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefghijklmnopqrstuvwxyz0123456789GoalTail";
    render(
      <ThreadComposer
        onSend={vi.fn()}
        placeholder="Type your message..."
        goalState={{
          active: true,
          objective: longObjective,
          ui_summary: "Short summary for strip",
        }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Show full goal" }));

    const dialog = await screen.findByRole("dialog", { name: "Goal" });
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveTextContent("Short summary for strip");
    expect(dialog).toHaveTextContent(longObjective);
  });

  it("opens a slash command palette and inserts the selected command", () => {
    const onSend = vi.fn();
    render(
      <ThreadComposer
        onSend={onSend}
        placeholder="Type your message..."
        slashCommands={COMMANDS}
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "/" } });

    const palette = screen.getByRole("listbox", { name: "Slash commands" });
    expect(palette).toBeInTheDocument();
    expect(palette).toHaveStyle({ maxHeight: "288px" });
    expect(screen.getByRole("option", { name: /\/stop/i })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(screen.getByRole("option", { name: /\/history/i })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    fireEvent.keyDown(input, { key: "Enter" });

    expect(input).toHaveValue("/history ");
    expect(onSend).not.toHaveBeenCalled();
    expect(screen.queryByRole("listbox", { name: "Slash commands" })).not.toBeInTheDocument();
  });

  it("renders slash commands as direct actions with current status", () => {
    render(
      <ThreadComposer
        onSend={vi.fn()}
        placeholder="Type your message..."
        modelLabel="deepseek-v4-pro"
        slashCommands={[
          {
            command: "/model",
            title: "Switch model preset",
            description: "Show or switch the active model preset.",
            icon: "brain",
            argHint: "[preset]",
          },
          COMMANDS[1],
        ]}
      />,
    );

    fireEvent.change(screen.getByLabelText("Message input"), {
      target: { value: "/" },
    });

    expect(screen.getByRole("option", { name: /Model deepseek-v4-pro/i })).toBeInTheDocument();
    expect(screen.getByText("Current")).toBeInTheDocument();
    expect(screen.getByText("/model [preset]")).toBeInTheDocument();
  });

  it("prioritizes stop as an immediate slash action while streaming", () => {
    const onStop = vi.fn();
    render(
      <ThreadComposer
        onSend={vi.fn()}
        onStop={onStop}
        isStreaming
        placeholder="Type your message..."
        slashCommands={[COMMANDS[1]]}
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "/" } });

    expect(screen.getByRole("option", { name: /Stop current task/i })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onStop).toHaveBeenCalledTimes(1);
    expect(input).toHaveValue("");
  });

  it("orders recent slash commands first for the blank slash menu", () => {
    window.localStorage.setItem("nanobot.webui.slashCommandRecents", JSON.stringify(["/history"]));
    render(
      <ThreadComposer
        onSend={vi.fn()}
        placeholder="Type your message..."
        slashCommands={COMMANDS}
      />,
    );

    fireEvent.change(screen.getByLabelText("Message input"), {
      target: { value: "/" },
    });

    expect(screen.getByRole("option", { name: /\/history/i })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByText("Recent")).toBeInTheDocument();
  });

  it("opens the CLI app mention palette and inserts the selected app", () => {
    const onSend = vi.fn();
    render(
      <ThreadComposer
        onSend={onSend}
        placeholder="Type your message..."
        cliApps={CLI_APPS}
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "@", selectionStart: 1 } });

    const palette = screen.getByRole("listbox", { name: "Apps and MCP" });
    expect(palette).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /@gimp/i })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.queryByRole("option", { name: /@krita/i })).not.toBeInTheDocument();

    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(screen.getByRole("option", { name: /@blender/i })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    fireEvent.keyDown(input, { key: "Enter" });

    expect(input).toHaveValue("@blender ");
    expect(screen.getByTestId("composer-cli-mention-blender")).toHaveTextContent("@blender");
    expect(screen.queryByTestId("composer-cli-app-tray")).not.toBeInTheDocument();
    expect(onSend).not.toHaveBeenCalled();
    expect(screen.queryByRole("listbox", { name: "Apps and MCP" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(onSend).toHaveBeenCalledWith("@blender", undefined, {
      cliApps: [{
        name: "blender",
        display_name: "Blender",
        category: "3d",
        entry_point: "cli-anything-blender",
        logo_url: null,
        brand_color: "#E87D0D",
      }],
    });
  });

  it("completes a CLI app mention with Tab and adds exactly one trailing space", () => {
    render(
      <ThreadComposer
        onSend={vi.fn()}
        placeholder="Type your message..."
        cliApps={CLI_APPS}
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, {
      target: { value: "use @ble", selectionStart: 8 },
    });

    fireEvent.keyDown(input, { key: "Tab" });

    expect(input).toHaveValue("use @blender ");
    expect(screen.getByTestId("composer-cli-mention-blender")).toHaveTextContent("@blender");
  });

  it("shows configured MCP presets in the mention palette and submits metadata", () => {
    const onSend = vi.fn();
    render(
      <ThreadComposer
        onSend={onSend}
        placeholder="Type your message..."
        cliApps={CLI_APPS}
        mcpPresets={MCP_PRESETS}
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, {
      target: { value: "use @bro", selectionStart: 8 },
    });

    expect(screen.getByRole("option", { name: /@browserbase/i })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /@figma/i })).not.toBeInTheDocument();

    fireEvent.keyDown(input, { key: "Tab" });

    expect(input).toHaveValue("use @browserbase ");
    expect(screen.getByTestId("composer-mcp-mention-browserbase")).toHaveTextContent("@browserbase");

    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(onSend).toHaveBeenCalledWith("use @browserbase", undefined, {
      mcpPresets: [{
        name: "browserbase",
        display_name: "Browserbase",
        category: "browser",
        transport: "streamableHttp",
        status: "configured",
        configured: true,
        logo_url: "https://example.invalid/browserbase.svg",
        brand_color: "#111827",
      }],
    });
  });

  it("shows right-side source badges so users can distinguish CLI apps from MCP servers", () => {
    render(
      <ThreadComposer
        onSend={vi.fn()}
        placeholder="Type your message..."
        cliApps={CLI_APPS}
        mcpPresets={MCP_PRESETS}
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "@", selectionStart: 1 } });

    expect(screen.queryByText("CLI Apps")).not.toBeInTheDocument();
    expect(screen.queryByText("MCP servers")).not.toBeInTheDocument();
    const gimp = screen.getByRole("option", { name: /GIMP @gimp .* CLI/i });
    const browserbase = screen.getByRole("option", { name: /Browserbase @browserbase .* MCP/i });
    expect(within(gimp).getByText("CLI")).toBeInTheDocument();
    expect(within(browserbase).getByText("MCP")).toBeInTheDocument();
    expect(within(gimp).getByText("@gimp")).toBeInTheDocument();
    expect(within(browserbase).getByText("@browserbase")).toBeInTheDocument();
  });

  it("does not duplicate the next word separator when completing a CLI app mention", () => {
    render(
      <ThreadComposer
        onSend={vi.fn()}
        placeholder="Type your message..."
        cliApps={CLI_APPS}
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, {
      target: { value: "use @ble tonight", selectionStart: 8 },
    });

    fireEvent.keyDown(input, { key: "Tab" });

    expect(input).toHaveValue("use @blender tonight");
  });

  it("renders a CLI app mention logo inline without moving the text cursor slot", () => {
    render(
      <ThreadComposer
        onSend={vi.fn()}
        placeholder="Type your message..."
        cliApps={CLI_APPS}
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, {
      target: { value: "meeting in @gimp", selectionStart: 16 },
    });

    expect(input).toHaveValue("meeting in @gimp");
    const token = screen.getByTestId("composer-cli-mention-gimp");
    expect(token).toHaveTextContent("@gimp");
    expect(token.className).not.toContain("font-semibold");
    expect(token.className).not.toContain("zoom-in");
    expect(token.className).not.toContain("px-");
    expect(token.className).not.toContain("mx-");
    expect(token.getAttribute("style")).toContain("color: #5C5543");
    expect(token.getAttribute("style")).toContain("text-shadow");
    expect(screen.queryByTestId("composer-cli-app-tray")).not.toBeInTheDocument();
    const logo = screen.getByTestId("composer-cli-mention-logo-gimp");
    expect(logo.className).toContain("top-1/2");
    expect(logo.className).toContain("left-1/2");
    expect(logo.className).not.toContain("-top-");
  });

  it("opens the slash command palette downward when there is more room below", async () => {
    vi.spyOn(HTMLFormElement.prototype, "getBoundingClientRect").mockReturnValue(
      rect({ top: 40, bottom: 160, width: 800, height: 120 }),
    );
    Object.defineProperty(window, "innerHeight", {
      value: 330,
      configurable: true,
    });
    render(
      <ThreadComposer
        onSend={vi.fn()}
        placeholder="Ask anything..."
        slashCommands={COMMANDS}
        variant="hero"
      />,
    );
    const input = screen.getByLabelText("Message input");

    fireEvent.change(input, { target: { value: "/" } });

    await waitFor(() => {
      const palette = screen.getByRole("listbox", { name: "Slash commands" });
      expect(palette.className).toContain("top-full");
      expect(palette).toHaveStyle({ maxHeight: "162px" });
    });
  });

  it("dismisses the slash command palette on outside click", () => {
    render(
      <div>
        <button type="button">outside</button>
        <ThreadComposer
          onSend={vi.fn()}
          placeholder="Type your message..."
          slashCommands={COMMANDS}
        />
      </div>,
    );

    fireEvent.change(screen.getByLabelText("Message input"), {
      target: { value: "/" },
    });
    expect(screen.getByRole("listbox", { name: "Slash commands" })).toBeInTheDocument();

    fireEvent.pointerDown(screen.getByRole("button", { name: "outside" }));

    expect(screen.queryByRole("listbox", { name: "Slash commands" })).not.toBeInTheDocument();
  });

  it("sends image generation mode with automatic aspect ratio", () => {
    const onSend = vi.fn();
    render(
      <ThreadComposer
        onSend={onSend}
        placeholder="Type your message..."
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Toggle image generation mode" }));
    expect(screen.getByPlaceholderText("Describe or edit an image…")).toBeInTheDocument();

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "Draw a friendly robot" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(onSend).toHaveBeenCalledWith(
      "Draw a friendly robot",
      undefined,
      { imageGeneration: { enabled: true, aspect_ratio: null } },
    );
  });

  it("shows a stop button while streaming", () => {
    const onStop = vi.fn();
    render(
      <ThreadComposer
        onSend={vi.fn()}
        onStop={onStop}
        isStreaming
        placeholder="Type your message..."
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Stop response" }));

    expect(onStop).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Send message" })).not.toBeInTheDocument();
  });

  it("lets users select a concrete image aspect ratio", () => {
    const onSend = vi.fn();
    render(
      <ThreadComposer
        onSend={onSend}
        placeholder="Type your message..."
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Toggle image generation mode" }));
    fireEvent.click(screen.getByRole("button", { name: "Image aspect ratio" }));
    expect(screen.getByRole("listbox", { name: "Image aspect ratio" }).className).toContain(
      "bottom-full",
    );
    fireEvent.mouseDown(screen.getByRole("option", { name: "Wide 16:9" }));

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "Draw a banner" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(onSend).toHaveBeenCalledWith(
      "Draw a banner",
      undefined,
      { imageGeneration: { enabled: true, aspect_ratio: "16:9" } },
    );
  });

  it("opens the hero image aspect menu downward", () => {
    render(
      <ThreadComposer
        onSend={vi.fn()}
        placeholder="Ask anything..."
        variant="hero"
        imageMode
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Image aspect ratio" }));

    expect(screen.getByRole("listbox", { name: "Image aspect ratio" }).className).toContain(
      "top-full",
    );
  });

  it("dismisses the image aspect menu on outside click, escape, and wheel", () => {
    render(
      <div>
        <button type="button">outside</button>
        <ThreadComposer
          onSend={vi.fn()}
          placeholder="Type your message..."
          imageMode
        />
      </div>,
    );

    const aspectButton = screen.getByRole("button", { name: "Image aspect ratio" });
    fireEvent.click(aspectButton);
    expect(screen.getByRole("listbox", { name: "Image aspect ratio" })).toBeInTheDocument();

    fireEvent.pointerDown(screen.getByRole("button", { name: "outside" }));
    expect(screen.queryByRole("listbox", { name: "Image aspect ratio" })).not.toBeInTheDocument();

    fireEvent.click(aspectButton);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("listbox", { name: "Image aspect ratio" })).not.toBeInTheDocument();

    fireEvent.click(aspectButton);
    fireEvent.wheel(screen.getByRole("listbox", { name: "Image aspect ratio" }), { deltaY: 120 });
    expect(screen.queryByRole("listbox", { name: "Image aspect ratio" })).not.toBeInTheDocument();
  });
});
