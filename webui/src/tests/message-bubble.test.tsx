import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MessageBubble } from "@/components/MessageBubble";
import type { CliAppInfo, McpPresetInfo, UIMessage } from "@/lib/types";

const CLI_APPS: CliAppInfo[] = [
  {
    name: "zoom",
    display_name: "Zoom",
    category: "productivity",
    description: "Meetings",
    requires: "",
    source: "harness",
    entry_point: "cli-anything-zoom",
    install_supported: true,
    installed: true,
    available: true,
    status: "installed",
    logo_url: "https://example.invalid/zoom.svg",
    brand_color: "#0B5CFF",
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
];

describe("MessageBubble", () => {
  it("renders user messages as right-aligned pills", () => {
    const message: UIMessage = {
      id: "u1",
      role: "user",
      content: "hello",
      createdAt: Date.now(),
    };

    const { container } = render(<MessageBubble message={message} />);
    const row = container.firstElementChild;
    const pill = screen.getByText("hello");

    expect(row).toHaveClass("ml-auto", "flex");
    expect(pill).toHaveClass("ml-auto", "w-fit", "rounded-[18px]");
    expect(screen.queryByRole("button", { name: "Fork" })).not.toBeInTheDocument();
  });

  it("renders fork control in completed assistant action rows", () => {
    const onForkFromHere = vi.fn();
    const message: UIMessage = {
      id: "a-fork",
      role: "assistant",
      content: "branch after this answer",
      latencyMs: 1_200,
      createdAt: Date.now(),
    };

    render(<MessageBubble message={message} onForkFromHere={onForkFromHere} />);

    fireEvent.click(screen.getByRole("button", { name: "Fork" }));
    expect(onForkFromHere).toHaveBeenCalledTimes(1);
  });

  it("renders installed CLI app mentions inside sent user messages", () => {
    const message: UIMessage = {
      id: "u-cli",
      role: "user",
      content: "Hi nano, please use @zoom to book a meeting, not @krita",
      createdAt: Date.now(),
    };

    render(<MessageBubble message={message} cliApps={CLI_APPS} />);

    const token = screen.getByTestId("message-cli-mention-zoom");
    expect(token).toHaveTextContent("@zoom");
    expect(token).toHaveAttribute("title", "CLI app: Zoom");
    expect(token.className).not.toContain("rounded");
    expect(token.className).not.toContain("px-");
    expect(token.getAttribute("style")).toContain("color: #0B5CFF");
    expect(token.getAttribute("style")).toContain("text-shadow");
    expect(screen.getByTestId("message-cli-mention-logo-zoom")).toBeInTheDocument();
    expect(screen.queryByTestId("message-cli-mention-krita")).not.toBeInTheDocument();
    expect(screen.getByText(/not @krita/)).toBeInTheDocument();
  });

  it("renders a lightweight automation source label for cron replies", () => {
    const message: UIMessage = {
      id: "a-cron",
      role: "assistant",
      content: "Time to drink water.",
      source: { kind: "cron", label: "drink water" },
      createdAt: Date.now(),
    };

    render(<MessageBubble message={message} />);

    expect(screen.getByText("drink water")).toBeInTheDocument();
    expect(screen.getByText("Triggered automatically")).toBeInTheDocument();
    expect(screen.getByText("Time to drink water.")).toBeInTheDocument();
  });

  it("renders structured CLI app attachments even without the installed catalog", () => {
    const message: UIMessage = {
      id: "u-cli-attached",
      role: "user",
      content: "Please use @drawio for the diagram",
      createdAt: Date.now(),
      cliApps: [{
        name: "drawio",
        display_name: "Draw.io",
        category: "diagram",
        entry_point: "cli-anything-drawio",
        logo_url: "https://example.invalid/drawio.svg",
        brand_color: "#F08705",
      }],
    };

    render(<MessageBubble message={message} cliApps={[]} />);

    const token = screen.getByTestId("message-cli-mention-drawio");
    expect(token).toHaveTextContent("@drawio");
    expect(token.className).not.toContain("rounded");
    expect(token.className).not.toContain("px-");
    expect(token.getAttribute("style")).toContain("color: #F08705");
    expect(screen.getByTestId("message-cli-mention-logo-drawio")).toBeInTheDocument();
  });

  it("renders MCP preset mentions inside sent user messages", () => {
    const message: UIMessage = {
      id: "u-mcp",
      role: "user",
      content: "Use @browserbase to inspect the checkout flow",
      createdAt: Date.now(),
    };

    render(<MessageBubble message={message} mcpPresets={MCP_PRESETS} />);

    const token = screen.getByTestId("message-mcp-mention-browserbase");
    expect(token).toHaveTextContent("@browserbase");
    expect(token).toHaveAttribute("title", "MCP server: Browserbase");
    expect(token.getAttribute("style")).toContain("color: #111827");
    expect(screen.getByTestId("message-mcp-mention-logo-browserbase")).toBeInTheDocument();
  });

  it("copies completed assistant replies from the action row", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    const message: UIMessage = {
      id: "a-copy",
      role: "assistant",
      content: "I can help with the next step.",
      createdAt: Date.now(),
    };

    render(<MessageBubble message={message} />);

    fireEvent.click(screen.getByRole("button", { name: "Copy" }));

    expect(writeText).toHaveBeenCalledWith("I can help with the next step.");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument(),
    );
  });

  it("copies completed assistant replies with the textarea fallback", async () => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: undefined,
    });
    const execCommand = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, "execCommand", {
      configurable: true,
      value: execCommand,
    });
    const message: UIMessage = {
      id: "a-copy-fallback",
      role: "assistant",
      content: "Fallback copy reply.",
      createdAt: Date.now(),
    };

    try {
      render(<MessageBubble message={message} />);

      fireEvent.click(screen.getByRole("button", { name: "Copy" }));

      await waitFor(() => expect(execCommand).toHaveBeenCalledWith("copy"));
      await waitFor(() =>
        expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument(),
      );
    } finally {
      Reflect.deleteProperty(navigator, "clipboard");
      Reflect.deleteProperty(document, "execCommand");
    }
  });

  it("falls back when the Clipboard API rejects assistant reply copy", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("not allowed"));
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    const execCommand = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, "execCommand", {
      configurable: true,
      value: execCommand,
    });
    const message: UIMessage = {
      id: "a-copy-reject",
      role: "assistant",
      content: "Rejected clipboard copy.",
      createdAt: Date.now(),
    };

    try {
      render(<MessageBubble message={message} />);

      fireEvent.click(screen.getByRole("button", { name: "Copy" }));

      expect(writeText).toHaveBeenCalledWith("Rejected clipboard copy.");
      await waitFor(() => expect(execCommand).toHaveBeenCalledWith("copy"));
      await waitFor(() =>
        expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument(),
      );
    } finally {
      Reflect.deleteProperty(navigator, "clipboard");
      Reflect.deleteProperty(document, "execCommand");
    }
  });

  it("does not show copy actions for streaming placeholders", () => {
    const message: UIMessage = {
      id: "a-streaming",
      role: "assistant",
      content: "",
      isStreaming: true,
      createdAt: Date.now(),
    };

    render(<MessageBubble message={message} />);

    expect(screen.queryByRole("button", { name: "Copy" })).not.toBeInTheDocument();
  });

  it("does not show copy when showAssistantCopyAction is false", () => {
    const message: UIMessage = {
      id: "a-mid",
      role: "assistant",
      content: "Mid-turn snippet.",
      createdAt: Date.now(),
    };

    render(<MessageBubble message={message} showAssistantCopyAction={false} />);

    expect(screen.queryByRole("button", { name: "Copy" })).not.toBeInTheDocument();
  });

  it("renders trace messages as collapsible tool groups", () => {
    const message: UIMessage = {
      id: "t1",
      role: "tool",
      kind: "trace",
      content: 'search "hk weather"',
      traces: ['weather("get")', 'search "hk weather"'],
      createdAt: Date.now(),
    };

    render(<MessageBubble message={message} />);
    const toggle = screen.getByRole("button", { name: /used 2 tools/i });

    expect(screen.queryByText('weather("get")')).not.toBeInTheDocument();
    expect(screen.queryByText('search "hk weather"')).not.toBeInTheDocument();

    fireEvent.click(toggle);
    expect(screen.getByText('weather("get")')).toBeInTheDocument();
    expect(screen.getByText('search "hk weather"')).toBeInTheDocument();
  });

  it("renders video media as an inline player", () => {
    const message: UIMessage = {
      id: "a1",
      role: "assistant",
      content: "here is the clip",
      createdAt: Date.now(),
      media: [
        {
          kind: "video",
          url: "/api/media/sig/payload",
          name: "demo.mp4",
        },
      ],
    };

    const { container } = render(<MessageBubble message={message} />);

    expect(screen.getByText("here is the clip")).toBeInTheDocument();
    const video = screen.getByLabelText(/video attachment/i);
    expect(video.tagName).toBe("VIDEO");
    expect(video).toHaveAttribute("src", "/api/media/sig/payload");
    expect(video).toHaveAttribute("preload", "auto");
    expect(container.querySelector("video[controls]")).toBeInTheDocument();
    expect(screen.queryByText("Preview")).not.toBeInTheDocument();
    expect(screen.queryByText("Code")).not.toBeInTheDocument();
  });

  it("auto-expands the reasoning trace while streaming with a shimmer header", () => {
    const message: UIMessage = {
      id: "a-reasoning-streaming",
      role: "assistant",
      content: "",
      createdAt: Date.now(),
      reasoning: "Step 1: parse intent. Step 2: compute.",
      reasoningStreaming: true,
    };

    const { container } = render(<MessageBubble message={message} />);

    expect(screen.getByText("Thinking…")).toBeInTheDocument();
    expect(screen.getByText(/Step 1: parse intent\./)).toBeInTheDocument();
    expect(container.querySelector(".reasoning-sheen-stripe")).not.toBeInTheDocument();
    expect(screen.getByText("Thinking…")).toHaveClass("streaming-text-sheen");
    expect(screen.getByText("Thinking…")).toHaveAttribute("data-sheen-text", "Thinking…");
    expect(screen.getByRole("button", { name: /thinking/i }).parentElement).not.toHaveClass("mb-2");
  });

  it("collapses the reasoning section by default once streaming ends", () => {
    const message: UIMessage = {
      id: "a-reasoning-done",
      role: "assistant",
      content: "The answer is 42.",
      createdAt: Date.now(),
      reasoning: "hidden until expanded",
      reasoningStreaming: false,
    };

    render(<MessageBubble message={message} />);

    expect(screen.getByText("Thinking")).toBeInTheDocument();
    expect(screen.getByText("The answer is 42.")).toBeInTheDocument();
    expect(screen.queryByText("hidden until expanded")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /thinking/i }).parentElement).toHaveClass("mb-2");

    fireEvent.click(screen.getByRole("button", { name: /thinking/i }));
    expect(screen.getByText("hidden until expanded")).toBeInTheDocument();
  });

  it("renders reasoning body as markdown so headings are not left as raw ###", async () => {
    await import("@/components/MarkdownTextRenderer");
    const message: UIMessage = {
      id: "a-reasoning-md",
      role: "assistant",
      content: "",
      createdAt: Date.now(),
      reasoning: "### Section title\n\nBody line.",
      reasoningStreaming: false,
    };

    const { container } = render(<MessageBubble message={message} />);
    fireEvent.click(screen.getByRole("button", { name: /thinking/i }));

    await waitFor(() => {
      expect(container.querySelector("h3")?.textContent).toBe("Section title");
    });
    expect(container.textContent).not.toContain("###");
    expect(screen.getByText("Body line.")).toBeInTheDocument();
  });

  it("renders inline file paths as compact file references", async () => {
    await import("@/components/MarkdownTextRenderer");
    const message: UIMessage = {
      id: "a-file-path",
      role: "assistant",
      content:
        "改动在 `webui/src/components/MarkdownTextRenderer.tsx` 和 `/Users/renxubin/.nanobot/workspace/minecraft-fps/index.html`。",
      createdAt: Date.now(),
    };

    try {
      render(<MessageBubble message={message} />);

      const references = await screen.findAllByTestId("inline-file-path");
      expect(references).toHaveLength(2);
      expect(references[0].parentElement).not.toHaveClass("translate-y-[0.08em]");
      expect(references[0].parentElement).toHaveClass("align-baseline");
      expect(references[0].parentElement).toHaveClass("leading-[inherit]");
      expect(references[0]).toHaveClass("items-baseline");
      expect(references[0]).toHaveTextContent("MarkdownTextRenderer.tsx");
      expect(references[0]).not.toHaveTextContent("webui/src/components");
      expect(screen.getByText("index.html")).toBeInTheDocument();
      expect(references[1]).not.toHaveTextContent("/Users/renxubin");
      expect(references[1]).not.toHaveAttribute("title");
      expect(references[1]).toHaveAttribute(
        "aria-label",
        "/Users/renxubin/.nanobot/workspace/minecraft-fps/index.html",
      );

      vi.useFakeTimers();
      fireEvent.pointerMove(references[1].parentElement!);
      await act(async () => {
        vi.advanceTimersByTime(500);
      });
      const tooltip = screen.getByRole("tooltip");
      expect(tooltip).toHaveTextContent(
        "/Users/renxubin/.nanobot/workspace/minecraft-fps/index.html",
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it("renders assistant image media as a larger generated result", () => {
    const message: UIMessage = {
      id: "a-image",
      role: "assistant",
      content: "done",
      createdAt: Date.now(),
      media: [
        {
          kind: "image",
          url: "/api/media/sig/image",
          name: "generated.png",
        },
      ],
    };

    const { container } = render(<MessageBubble message={message} />);

    const imageButton = screen.getByRole("button", { name: /view image/i });
    expect(imageButton).toHaveClass("w-[min(100%,34rem)]", "rounded-[20px]");
    expect(imageButton).not.toHaveAttribute("title");
    expect(container.querySelector("img")).toHaveClass("h-auto", "w-full", "object-contain");
  });

  it("renders mislabeled html assistant media as a file attachment", () => {
    const message: UIMessage = {
      id: "a-html",
      role: "assistant",
      content: "file ready",
      createdAt: Date.now(),
      media: [
        {
          kind: "image",
          url: "/api/media/sig/html",
          name: "index.html",
        },
      ],
    };

    const { container } = render(<MessageBubble message={message} />);

    expect(screen.getByLabelText("File attachment")).toHaveTextContent("index.html");
    expect(container.querySelector("img")).not.toBeInTheDocument();
  });

  it("renders assistant svg media as an image preview", () => {
    const message: UIMessage = {
      id: "a-svg",
      role: "assistant",
      content: "chart ready",
      createdAt: Date.now(),
      media: [
        {
          kind: "file",
          url: "/api/media/sig/svg",
          name: "growth.svg",
        },
      ],
    };

    const { container } = render(<MessageBubble message={message} />);

    expect(screen.getByRole("button", { name: /view image: growth.svg/i })).toBeInTheDocument();
    expect(container.querySelector('img[src="/api/media/sig/svg"]')).toBeInTheDocument();
    expect(screen.queryByLabelText("File attachment")).not.toBeInTheDocument();
  });
});
