import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ThreadComposer } from "@/components/thread/ThreadComposer";
import { SESSION_DRAG_TYPE } from "@/lib/session-drag";
import type { ChatSummary, CliAppInfo, McpPresetInfo, SlashCommand } from "@/lib/types";

vi.mock("@/lib/imageEncode", () => ({
  encodeImage: vi.fn(async (file: File) => ({
    ok: true,
    dataUrl: `data:${file.type || "image/png"};base64,aW1hZ2U=`,
    bytes: Math.max(1, file.size),
    normalized: false,
  })),
}));

const COMMANDS: SlashCommand[] = [
  {
    command: "/stop",
    title: "Stop current task",
    description: "Cancel the active agent turn.",
    icon: "square",
    lifecycle: "stop_active_turn",
    acceptsArgs: false,
  },
  {
    command: "/history",
    title: "Show conversation history",
    description: "Print the last N persisted messages.",
    icon: "history",
    argHint: "[n]",
    lifecycle: "side_channel",
    acceptsArgs: true,
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
    requires: "Figma local app",
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

function session(chatId: string, title: string, preview = ""): ChatSummary {
  const key = `websocket:${chatId}`;
  const handleId = Array.from(chatId)
    .map((character) => character.codePointAt(0)?.toString(16).padStart(4, "0") ?? "0000")
    .join("")
    .padEnd(32, "0")
    .slice(0, 32);
  return {
    key,
    channel: "websocket",
    chatId,
    createdAt: null,
    updatedAt: null,
    title,
    preview,
    handle: {
      id: `handle_${handleId}`,
      name: title,
    },
  };
}

const ORIGINAL_INNER_HEIGHT = window.innerHeight;
const ORIGINAL_MEDIA_DEVICES = navigator.mediaDevices;

function mockBlobUrls() {
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: vi.fn(() => "blob:composer-test"),
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    value: vi.fn(),
  });
}

function stubVisualViewport({
  height,
  offsetTop = 0,
}: {
  height: number;
  offsetTop?: number;
}) {
  const target = new EventTarget();
  vi.stubGlobal("visualViewport", {
    width: 390,
    height,
    offsetTop,
    offsetLeft: 0,
    pageTop: offsetTop,
    pageLeft: 0,
    scale: 1,
    addEventListener: target.addEventListener.bind(target),
    removeEventListener: target.removeEventListener.bind(target),
    dispatchEvent: target.dispatchEvent.bind(target),
  } as unknown as VisualViewport);
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  Reflect.deleteProperty(window, "nanobotHost");
  if (ORIGINAL_MEDIA_DEVICES) {
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: ORIGINAL_MEDIA_DEVICES,
    });
  } else {
    Reflect.deleteProperty(navigator, "mediaDevices");
  }
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

function mockVoiceRecorder(blob = new Blob(["voice"], { type: "audio/webm" })) {
  const stopTrack = vi.fn();
  const getUserMedia = vi.fn(async () => ({
    getTracks: () => [{ stop: stopTrack }],
  }));
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia },
  });

  class FakeMediaRecorder {
    static isTypeSupported = vi.fn((type: string) => type === "audio/webm");

    state: RecordingState = "inactive";
    mimeType = blob.type;
    ondataavailable: ((event: BlobEvent) => void) | null = null;
    onstop: (() => void) | null = null;

    start() {
      this.state = "recording";
    }

    stop() {
      this.state = "inactive";
      this.ondataavailable?.({ data: blob } as BlobEvent);
      this.onstop?.();
    }
  }

  vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
  return { getUserMedia, stopTrack };
}

function mockVoiceAudioInput(
  sample = 128,
  state: AudioContextState = "running",
  decodedChannels?: Float32Array[],
) {
  const decodeAudioDataMock = vi.fn(async () => {
    if (!decodedChannels) throw new Error("decodeAudioData not mocked");
    return {
      numberOfChannels: decodedChannels.length,
      sampleRate: 16_000,
      getChannelData: (channel: number) => decodedChannels[channel],
    } as AudioBuffer;
  });

  class FakeAudioContext {
    state = state;

    createMediaStreamSource() {
      return { connect: vi.fn(), disconnect: vi.fn() };
    }

    createAnalyser() {
      return {
        fftSize: 256,
        smoothingTimeConstant: 0,
        disconnect: vi.fn(),
        getByteTimeDomainData: (data: Uint8Array) => data.fill(sample),
      };
    }

    close = vi.fn(async () => undefined);
    decodeAudioData = decodeAudioDataMock;
    resume = vi.fn(async () => undefined);
  }

  vi.stubGlobal("AudioContext", FakeAudioContext);
  vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) =>
    window.setTimeout(() => callback(performance.now()), 16) as unknown as number
  );
  vi.spyOn(window, "cancelAnimationFrame").mockImplementation((id) =>
    window.clearTimeout(id as unknown as number)
  );
  return { decodeAudioData: decodeAudioDataMock };
}

async function waitForVoiceCapture(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 700));
  });
}

function bytesFromDataUrl(dataUrl: string): Uint8Array {
  const [, base64 = ""] = dataUrl.split(",");
  return Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));
}

function ascii(bytes: Uint8Array, offset: number, length: number): string {
  return String.fromCharCode(...bytes.slice(offset, offset + length));
}

const MODEL_PRESETS = [
  { name: "kimi", model: "moonshot/kimi-k2.5", provider: "moonshot" },
  { name: "dflash", model: "deepseek/deepseek-v4-flash", provider: "deepseek" },
  { name: "dspro", model: "deepseek/deepseek-v4-pro", provider: "deepseek" },
];

function renderPresetComposer(
  variant: "thread" | "hero" = "thread",
  onManageModels?: () => void,
) {
  const onPresetChange = vi.fn();
  render(
    <ThreadComposer
      onSend={vi.fn()}
      modelLabel="kimi"
      modelPreset="kimi"
      modelProvider="moonshot"
      modelPresets={MODEL_PRESETS}
      onModelPresetChange={onPresetChange}
      onManageModels={onManageModels}
      placeholder={variant === "hero" ? "Ask anything..." : "Type your message..."}
      variant={variant}
    />,
  );
  return {
    badge: screen.getByRole("button", { name: "kimi" }),
    onPresetChange,
  };
}

describe("ThreadComposer", () => {
  it("locks an async send and keeps the draft when it is rejected", async () => {
    let resolveSend!: (accepted: boolean) => void;
    const onSend = vi.fn(() => new Promise<boolean>((resolve) => {
      resolveSend = resolve;
    }));
    render(
      <ThreadComposer
        onSend={onSend}
        placeholder="Type your message..."
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "keep this pending draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(input).toBeDisabled();
    expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();
    await act(async () => resolveSend(false));

    await waitFor(() => expect(input).toBeEnabled());
    expect(input).toHaveValue("keep this pending draft");
  });

  it("dismisses the touch keyboard after a successful send", async () => {
    vi.stubGlobal("matchMedia", vi.fn((query: string) => ({
      matches: query === "(hover: none) and (pointer: coarse)",
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));
    const onSend = vi.fn();
    render(
      <ThreadComposer
        onSend={onSend}
        placeholder="Type your message..."
      />,
    );

    const input = screen.getByLabelText("Message input");
    await act(async () => {
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    });
    expect(input).not.toHaveFocus();
    input.focus();
    expect(input).toHaveFocus();
    fireEvent.change(input, { target: { value: "hello from mobile" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await act(async () => {
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    });

    expect(onSend).toHaveBeenCalledWith("hello from mobile", undefined, undefined);
    expect(input).toHaveValue("");
    expect(input).not.toHaveFocus();
  });

  it("focuses and sends a removable quoted answer excerpt", async () => {
    const onSend = vi.fn();
    const onQuotedContextChange = vi.fn();
    render(
      <ThreadComposer
        onSend={onSend}
        placeholder="Type your message..."
        quotedContext="selected answer excerpt"
        focusRequest={1}
        onQuotedContextChange={onQuotedContextChange}
      />,
    );

    const input = screen.getByLabelText("Message input");
    await waitFor(() => expect(input).toHaveFocus());
    expect(screen.getByLabelText("Quoted context")).toHaveTextContent("selected answer excerpt");

    fireEvent.change(input, { target: { value: "What does this mean?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(onSend).toHaveBeenCalledWith("What does this mean?", undefined, {
      quotedContext: "selected answer excerpt",
    });
    expect(onQuotedContextChange).toHaveBeenCalledWith(null);
  });

  it("removes quoted context without clearing the draft", () => {
    const onQuotedContextChange = vi.fn();
    render(
      <ThreadComposer
        onSend={vi.fn()}
        placeholder="Type your message..."
        quotedContext="selected answer excerpt"
        onQuotedContextChange={onQuotedContextChange}
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "keep this draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Remove quoted context" }));

    expect(onQuotedContextChange).toHaveBeenCalledWith(null);
    expect(input).toHaveValue("keep this draft");
  });

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
    expect(input.className).toContain("text-[16px]");
    expect(input.className).toContain("pt-[27px]");
    fireEvent.change(input, { target: { value: "1" } });
    expect(input.className).toContain("pt-[27px]");
    expect(input.parentElement?.parentElement?.className).toContain("max-w-[58rem]");
  });

  it("defers textarea autosizing until IME composition commits", () => {
    render(
      <ThreadComposer
        onSend={vi.fn()}
        placeholder="Type your message..."
      />,
    );
    const input = screen.getByLabelText("Message input") as HTMLTextAreaElement;
    Object.defineProperty(input, "scrollHeight", {
      configurable: true,
      value: 120,
    });
    input.style.height = "50px";

    fireEvent.input(input, {
      target: { value: "zhongwen" },
      isComposing: true,
    });
    expect(input.style.height).toBe("50px");

    fireEvent.input(input, {
      target: { value: "中文" },
      isComposing: false,
    });
    expect(input.style.height).toBe("120px");
  });

  it("lets long model preset labels use their intrinsic width", () => {
    render(
      <ThreadComposer
        onSend={vi.fn()}
        modelLabel="gpt-5.6-sol"
        modelPreset="gpt-5-6-sol"
        modelProvider="openai_codex"
        modelPresets={[
          {
            name: "gpt-5-6-sol",
            label: "gpt-5.6-sol",
            model: "openai-codex/gpt-5.6-sol",
            provider: "openai_codex",
          },
          ...MODEL_PRESETS,
        ]}
        onModelPresetChange={vi.fn()}
        placeholder="Ask anything..."
        variant="hero"
      />,
    );

    const badge = screen.getByRole("button", { name: "gpt-5.6-sol" });
    expect(badge).toHaveClass("w-fit", "max-w-[min(18rem,44vw)]");
    expect(badge).not.toHaveClass("w-[5.75rem]");
    expect(screen.getByText("gpt-5.6-sol")).toBeInTheDocument();
  });

  it("shows a compact context meter beside the model selector", async () => {
    render(
      <ThreadComposer
        onSend={vi.fn()}
        modelLabel="gpt-5.6-sol"
        modelPreset="gpt-5-6-sol"
        modelProvider="openai_codex"
        contextUsage={{
          contextTokens: 74_900,
          contextWindowTokens: 1_000_000,
        }}
        placeholder="Ask anything..."
      />,
    );

    const context = screen.getByTestId("composer-context-usage");
    expect(context).toHaveClass("size-5", "rounded-full");
    expect(context).not.toHaveTextContent("Context 74.9K / 1M");
    expect(screen.getByTestId("composer-context-meter")).toBeInTheDocument();
    expect(context).toHaveAccessibleName(
      "Context 7%. Open context usage",
    );

    fireEvent.focus(context);
    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent("Context 7%");
    expect(tooltip.parentElement).toHaveClass("rounded-full", "px-2.5", "py-1");
    expect(tooltip.parentElement).not.toHaveTextContent("Available");
  });

  it("opens an input-token chart with one bar for each logical round", () => {
    render(
      <ThreadComposer
        onSend={vi.fn()}
        modelLabel="gpt-5.6-sol"
        modelPreset="gpt-5-6-sol"
        modelProvider="openai_codex"
        contextUsage={{
          contextTokens: 14_700,
          contextWindowTokens: 200_000,
        }}
        recentRoundUsage={[
          {
            id: "turn-1",
            timestamp: Date.UTC(2026, 8, 3, 7, 20),
            inputTokens: 18_000,
            outputTokens: 280,
            cachedTokens: 12_000,
            generationMs: 12_000,
          },
          {
            id: "turn-2",
            timestamp: Date.UTC(2026, 8, 3, 8, 22),
            inputTokens: 29_400,
            outputTokens: 416,
            cachedTokens: 26_180,
            generationMs: 40_000,
          },
        ]}
        placeholder="Ask anything..."
      />,
    );

    fireEvent.click(screen.getByTestId("composer-context-usage"));

    expect(screen.getByText("Context")).toBeInTheDocument();
    expect(screen.getByText("14.7K / 200K")).toBeInTheDocument();
    expect(screen.getByText("Recent rounds")).toBeInTheDocument();
    expect(screen.getByText("Input tokens")).toBeInTheDocument();
    expect(screen.getAllByTestId("round-usage-bar")).toHaveLength(2);
    const [smallerBar, largerBar] = screen.getAllByTestId("round-usage-bar");
    expect(
      Number.parseFloat(smallerBar.style.height) / Number.parseFloat(largerBar.style.height),
    ).toBeCloseTo(18_000 / 29_400, 5);
    expect(largerBar.querySelector(".kv-cache-reused")).toBeInTheDocument();
    expect(largerBar.querySelector(".kv-cache-not-reused")).toBeInTheDocument();
    expect(screen.queryByText("Reused")).not.toBeInTheDocument();
    expect(screen.queryByText("Not reused")).not.toBeInTheDocument();
    expect(screen.getByRole("img", {
      name: /input tokens 29,400.*KV cache hit rate 89%.*output tokens 416.*generation time 40/i,
    })).toBeInTheDocument();
  });

  it("uses each visible bar as its round detail trigger", async () => {
    const user = userEvent.setup();
    render(
      <ThreadComposer
        onSend={vi.fn()}
        contextUsage={{ contextTokens: 14_700, contextWindowTokens: 200_000 }}
        recentRoundUsage={[
          {
            id: "turn-1",
            timestamp: Date.UTC(2026, 8, 3, 7, 20),
            inputTokens: 18_000,
            outputTokens: 280,
            cachedTokens: 12_000,
          },
          {
            id: "turn-2",
            timestamp: Date.UTC(2026, 8, 3, 8, 22),
            inputTokens: 29_400,
            outputTokens: 416,
            cachedTokens: 26_180,
          },
        ]}
        placeholder="Ask anything..."
      />,
    );

    await user.click(screen.getByTestId("composer-context-usage"));
    const firstBar = screen.getByRole("img", { name: /input tokens 18,000/i });
    const secondBar = screen.getByRole("img", { name: /input tokens 29,400/i });
    expect(firstBar).toHaveAttribute("data-testid", "round-usage-bar");
    expect(secondBar).toHaveAttribute("data-testid", "round-usage-bar");
    await user.hover(firstBar);
    const firstTooltip = await screen.findByRole("tooltip");
    expect(within(firstTooltip).getByText("Input tokens")).toBeInTheDocument();
    expect(within(firstTooltip).getByText("18,000")).toBeInTheDocument();
    await user.click(firstBar);
    await user.unhover(firstBar);
    await user.hover(secondBar);
    const secondTooltip = await screen.findByRole("tooltip");
    expect(within(secondTooltip).getByText("Input tokens")).toBeInTheDocument();
    expect(within(secondTooltip).getByText("29,400")).toBeInTheDocument();
  });

  it("keeps context usage visible when the provider omits cache metrics", () => {
    render(
      <ThreadComposer
        onSend={() => {}}
        contextUsage={{ contextTokens: 14_700, contextWindowTokens: 200_000 }}
        recentRoundUsage={[{
          id: "turn-without-cache-metrics",
          timestamp: new Date(2026, 8, 3, 16, 22).getTime(),
          inputTokens: 29_400,
          outputTokens: 416,
        }]}
        placeholder="Ask anything..."
      />,
    );

    fireEvent.click(screen.getByTestId("composer-context-usage"));

    expect(screen.getByRole("progressbar", { name: "Context 7%" })).toHaveAttribute(
      "aria-valuenow",
      "7",
    );
    const [bar] = screen.getAllByTestId("round-usage-bar");
    expect(bar.firstElementChild).toHaveClass("bg-muted-foreground/25");
    expect(screen.queryByText("Reused")).not.toBeInTheDocument();
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
    const modelPill = screen.getByText("gpt-4o").closest(".composer-model-pill");
    expect(modelPill).toHaveClass("font-medium", "text-foreground/70");
    expect(modelPill).not.toHaveClass("font-semibold");
    const providerLogo = screen.getByTestId("composer-model-logo-openai");
    expect(providerLogo).toBeInTheDocument();
    expect(providerLogo).not.toHaveClass("border", "bg-background");
    const input = screen.getByPlaceholderText("Type your message...");
    expect(input.className).toContain("min-h-[50px]");
    expect(input.className).toContain("text-[16px]");
    expect(input.parentElement?.parentElement?.className).toContain("max-w-[49.5rem]");
    expect(input.parentElement?.parentElement?.className).toContain("rounded-panel");
    expect(input.parentElement?.parentElement?.className).not.toContain("shadow-");
    expect(screen.getByRole("button", { name: "Attach files" }).className).toContain("bg-card");
    expect(screen.getByRole("button", { name: "Send message" }).className).toContain("bg-foreground");
    expect(screen.queryByText(/Enter to send/)).not.toBeInTheDocument();
  });

  it("opens a model picker and switches presets with one click", async () => {
    const { badge, onPresetChange } = renderPresetComposer();
    expect(badge).toHaveClass("h-9");
    expect(badge).toHaveClass("w-fit");
    fireEvent.click(badge);
    const picker = screen.getByRole("dialog", { name: "Switch model for this chat" });
    expect(picker).toHaveClass("w-[min(18rem,calc(100vw-2rem))]");
    expect(badge).toHaveClass("w-fit");
    expect(badge.querySelector(".composer-model-pill")).not.toHaveClass("w-full");
    expect(within(picker).getAllByRole("option")).toHaveLength(3);
    expect(within(picker).getByRole("option", { name: "dflash" })).toHaveTextContent(
      /dflash\s*deepseek-v4-flash/,
    );
    expect(within(picker).getByRole("option", { name: "kimi" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(document.activeElement).toBe(within(picker).getByRole("option", { name: "kimi" }));
    fireEvent.click(within(picker).getByRole("option", { name: "dspro" }));
    expect(onPresetChange).toHaveBeenCalledWith("dspro");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(badge).toHaveClass("w-fit");
  });

  it("opens model settings from the picker footer", async () => {
    const onManageModels = vi.fn();
    const { badge } = renderPresetComposer("thread", onManageModels);

    fireEvent.click(badge);
    const picker = screen.getByRole("dialog", { name: "Switch model for this chat" });
    fireEvent.click(within(picker).getByRole("button", { name: "Manage models" }));

    expect(onManageModels).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("keeps long-press drag switching alongside the click picker", () => {
    vi.useFakeTimers();
    const { badge, onPresetChange } = renderPresetComposer();

    fireEvent.pointerDown(badge, { pointerId: 1, pointerType: "touch", clientY: 100 });
    act(() => vi.advanceTimersByTime(400));
    expect(screen.getByTestId("composer-model-pill-viewport")).toBeInTheDocument();
    expect(screen.getByTestId("composer-model-pill-layout")).toHaveClass("invisible");
    expect(screen.getByTestId("composer-model-pill-track")).not.toHaveClass("transition-transform");

    fireEvent.pointerMove(badge, { pointerId: 1, pointerType: "touch", clientY: 56 });
    fireEvent.pointerUp(badge, { pointerId: 1, pointerType: "touch", clientY: 56 });
    expect(onPresetChange).toHaveBeenCalledWith("dflash");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    vi.useRealTimers();
  });

  it("uses the same click picker in hero mode", () => {
    const { badge, onPresetChange } = renderPresetComposer("hero");
    expect(badge).toHaveClass("h-8");
    fireEvent.click(badge);
    fireEvent.click(screen.getByRole("option", { name: "dflash" }));
    expect(onPresetChange).toHaveBeenCalledWith("dflash");
  });

  it("transcribes voice input into the composer without sending", async () => {
    mockVoiceRecorder();
    const onSend = vi.fn();
    const onTranscribeAudio = vi.fn(async () => "hello voice");
    render(
      <ThreadComposer
        onSend={onSend}
        onTranscribeAudio={onTranscribeAudio}
        placeholder="Type your message..."
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Voice input" }));
    expect(await screen.findByLabelText("Recording 0:00")).toBeInTheDocument();
    await waitForVoiceCapture();
    fireEvent.click(await screen.findByRole("button", { name: "Stop recording" }));

    await waitFor(() => expect(onTranscribeAudio).toHaveBeenCalledWith(
      expect.stringMatching(/^data:audio\/webm;base64,/),
      expect.objectContaining({ durationMs: expect.any(Number) }),
    ));
    await waitFor(() => expect(screen.getByLabelText("Message input")).toHaveValue("hello voice"));
    expect(onSend).not.toHaveBeenCalled();
  });

  it("explains the HTTPS requirement for voice input on an insecure origin", async () => {
    const { getUserMedia } = mockVoiceRecorder();
    vi.stubGlobal("isSecureContext", false);
    render(
      <ThreadComposer
        onSend={vi.fn()}
        onTranscribeAudio={vi.fn(async () => "unused")}
        placeholder="Type your message..."
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Voice input" }));

    expect(
      await screen.findByText(
        "Chrome and other browsers block microphone access on remote HTTP pages for security. "
          + "Open this WebUI over HTTPS to use voice input.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveClass("max-h-24");
    expect(getUserMedia).not.toHaveBeenCalled();
  });

  it("keeps the unsupported-browser error for secure origins without recording support", async () => {
    const { getUserMedia } = mockVoiceRecorder();
    vi.stubGlobal("isSecureContext", true);
    vi.stubGlobal("MediaRecorder", undefined);
    render(
      <ThreadComposer
        onSend={vi.fn()}
        onTranscribeAudio={vi.fn(async () => "unused")}
        placeholder="Type your message..."
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Voice input" }));

    expect(
      await screen.findByText("Voice input is not supported in this browser."),
    ).toBeInTheDocument();
    expect(getUserMedia).not.toHaveBeenCalled();
  });

  it("converts voice recordings to wav for Xiaomi MiMo transcription", async () => {
    mockVoiceRecorder(new Blob([new Uint8Array([1, 2, 3, 4])], { type: "audio/webm" }));
    const { decodeAudioData } = mockVoiceAudioInput(
      180,
      "running",
      [new Float32Array([0, 0.5, -0.5])],
    );
    const onTranscribeAudio = vi.fn(async () => "mimo voice");
    render(
      <ThreadComposer
        onSend={vi.fn()}
        onTranscribeAudio={onTranscribeAudio}
        placeholder="Type your message..."
        transcriptionProvider="xiaomi_mimo"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Voice input" }));
    expect(await screen.findByLabelText("Recording 0:00")).toBeInTheDocument();
    await waitForVoiceCapture();
    fireEvent.click(await screen.findByRole("button", { name: "Stop recording" }));

    await waitFor(() => expect(onTranscribeAudio).toHaveBeenCalledTimes(1));
    const [dataUrl, options] = onTranscribeAudio.mock.calls[0];
    expect(dataUrl).toMatch(/^data:audio\/wav;base64,/);
    expect(options).toEqual(expect.objectContaining({ durationMs: expect.any(Number) }));
    expect(decodeAudioData).toHaveBeenCalledTimes(1);

    const bytes = bytesFromDataUrl(dataUrl);
    const view = new DataView(bytes.buffer);
    expect(ascii(bytes, 0, 4)).toBe("RIFF");
    expect(ascii(bytes, 8, 4)).toBe("WAVE");
    expect(ascii(bytes, 12, 4)).toBe("fmt ");
    expect(view.getUint16(20, true)).toBe(1);
    expect(view.getUint16(22, true)).toBe(1);
    expect(view.getUint32(24, true)).toBe(16_000);
    expect(view.getUint16(34, true)).toBe(16);
    expect(ascii(bytes, 36, 4)).toBe("data");
    await waitFor(() => expect(screen.getByLabelText("Message input")).toHaveValue("mimo voice"));
  });

  it("does not start duplicate voice recordings while microphone access is pending", async () => {
    const { getUserMedia, stopTrack } = mockVoiceRecorder();
    let resolveStream: ((stream: MediaStream) => void) | undefined;
    getUserMedia.mockImplementation(() => new Promise((resolve) => {
      resolveStream = resolve as (stream: MediaStream) => void;
    }));
    const onTranscribeAudio = vi.fn(async () => "one recording");
    render(
      <ThreadComposer
        onSend={vi.fn()}
        onTranscribeAudio={onTranscribeAudio}
        placeholder="Type your message..."
      />,
    );

    const voiceButton = screen.getByRole("button", { name: "Voice input" });
    fireEvent.click(voiceButton);
    fireEvent.click(voiceButton);

    expect(getUserMedia).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveStream?.({ getTracks: () => [{ stop: stopTrack }] } as unknown as MediaStream);
    });
    expect(await screen.findByLabelText("Recording 0:00")).toBeInTheDocument();
    await waitForVoiceCapture();
    fireEvent.click(await screen.findByRole("button", { name: "Stop recording" }));

    await waitFor(() => expect(onTranscribeAudio).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByLabelText("Message input")).toHaveValue("one recording"));
  });

  it("distinguishes a missing microphone from a blocked permission", async () => {
    const { getUserMedia } = mockVoiceRecorder();
    getUserMedia.mockRejectedValue(Object.assign(new Error("no microphone"), {
      name: "NotFoundError",
    }));
    render(
      <ThreadComposer
        onSend={vi.fn()}
        onTranscribeAudio={vi.fn(async () => "unused")}
        placeholder="Type your message..."
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Voice input" }));

    await waitFor(() => {
      expect(screen.getByText("No microphone was found. Connect a microphone and try again.")).toBeInTheDocument();
    });
  });

  it("clears a previous voice error when retrying microphone access", async () => {
    const { getUserMedia } = mockVoiceRecorder();
    getUserMedia.mockRejectedValueOnce(new Error("permission denied"));
    const onTranscribeAudio = vi.fn(async () => "voice retry");
    render(
      <ThreadComposer
        onSend={vi.fn()}
        onTranscribeAudio={onTranscribeAudio}
        placeholder="Type your message..."
      />,
    );

    const voiceButton = screen.getByRole("button", { name: "Voice input" });
    fireEvent.click(voiceButton);
    await waitFor(() => expect(screen.getByText("Allow microphone access in the address bar, then retry.")).toBeInTheDocument());

    fireEvent.click(voiceButton);

    await waitFor(() => expect(screen.queryByText("Allow microphone access in the address bar, then retry.")).not.toBeInTheDocument());
    expect(await screen.findByLabelText("Recording 0:00")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Stop recording" }));
  });

  it("supports press-and-hold voice recording", async () => {
    mockVoiceRecorder();
    const onSend = vi.fn();
    const onTranscribeAudio = vi.fn(async () => "held voice");
    render(
      <ThreadComposer
        onSend={onSend}
        onTranscribeAudio={onTranscribeAudio}
        placeholder="Type your message..."
      />,
    );

    const voiceButton = screen.getByRole("button", { name: "Voice input" });
    fireEvent.pointerDown(voiceButton, { button: 0, pointerId: 1, pointerType: "touch" });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 180));
    });
    expect(await screen.findByLabelText("Recording 0:00")).toBeInTheDocument();
    await waitForVoiceCapture();
    fireEvent.pointerUp(screen.getByRole("button", { name: "Stop recording" }), {
      pointerId: 1,
      pointerType: "touch",
    });

    await waitFor(() => expect(onTranscribeAudio).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByLabelText("Message input")).toHaveValue("held voice"));
    expect(onSend).not.toHaveBeenCalled();
  });

  it("supports keyboard hold voice recording", async () => {
    mockVoiceRecorder();
    const onSend = vi.fn();
    const onTranscribeAudio = vi.fn(async () => "shortcut voice");
    render(
      <ThreadComposer
        onSend={onSend}
        onTranscribeAudio={onTranscribeAudio}
        placeholder="Type your message..."
      />,
    );

    const voiceButton = screen.getByRole("button", { name: "Voice input" });
    expect(voiceButton).toHaveAttribute("title", "Click to dictate or hold");
    expect(voiceButton).toHaveAttribute("aria-keyshortcuts", "Control+Shift+D");
    fireEvent.keyDown(window, { code: "KeyD", ctrlKey: true, key: "D", shiftKey: true });
    expect(await screen.findByLabelText("Recording 0:00")).toBeInTheDocument();
    await waitForVoiceCapture();
    fireEvent.keyUp(window, { code: "KeyD", ctrlKey: true, key: "D", shiftKey: true });

    await waitFor(() => expect(onTranscribeAudio).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByLabelText("Message input")).toHaveValue("shortcut voice"));
    expect(onSend).not.toHaveBeenCalled();
  });

  it("ignores the delayed click emitted after a long-press voice recording", async () => {
    const { getUserMedia } = mockVoiceRecorder();
    const onTranscribeAudio = vi.fn(async () => "held once");
    render(
      <ThreadComposer
        onSend={vi.fn()}
        onTranscribeAudio={onTranscribeAudio}
        placeholder="Type your message..."
      />,
    );

    const voiceButton = screen.getByRole("button", { name: "Voice input" });
    fireEvent.pointerDown(voiceButton, { button: 0, pointerId: 1, pointerType: "touch" });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 180));
    });
    expect(await screen.findByLabelText("Recording 0:00")).toBeInTheDocument();
    await waitForVoiceCapture();
    fireEvent.pointerUp(screen.getByRole("button", { name: "Stop recording" }), {
      pointerId: 1,
      pointerType: "touch",
    });
    await waitFor(() => expect(screen.getByLabelText("Message input")).toHaveValue("held once"));

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    fireEvent.click(screen.getByRole("button", { name: "Voice input" }));

    expect(getUserMedia).toHaveBeenCalledTimes(1);
    expect(onTranscribeAudio).toHaveBeenCalledTimes(1);
  });

  it("keeps existing text when voice transcription fails", async () => {
    mockVoiceRecorder();
    const onSend = vi.fn();
    const onTranscribeAudio = vi.fn(async () => {
      throw new Error("not_configured");
    });
    render(
      <ThreadComposer
        onSend={onSend}
        onTranscribeAudio={onTranscribeAudio}
        placeholder="Type your message..."
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Voice input" }));
    await waitForVoiceCapture();
    fireEvent.click(await screen.findByRole("button", { name: "Stop recording" }));

    await waitFor(() => {
      expect(screen.getByText("Configure a transcription provider first.")).toBeInTheDocument();
    });
    expect(input).toHaveValue("draft");
    expect(onSend).not.toHaveBeenCalled();
  });

  it("does not transcribe recordings that are too short", async () => {
    mockVoiceRecorder();
    const onTranscribeAudio = vi.fn(async () => "should not appear");
    render(
      <ThreadComposer
        onSend={vi.fn()}
        onTranscribeAudio={onTranscribeAudio}
        placeholder="Type your message..."
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Voice input" }));
    fireEvent.click(await screen.findByRole("button", { name: "Stop recording" }));

    await waitFor(() => {
      expect(screen.getByText("Hold a little longer to record voice.")).toBeInTheDocument();
    });
    expect(onTranscribeAudio).not.toHaveBeenCalled();
  });

  it("transcribes recorded audio even when waveform samples are silent", async () => {
    mockVoiceRecorder();
    mockVoiceAudioInput();
    const onTranscribeAudio = vi.fn(async () => "quiet voice");
    render(
      <ThreadComposer
        onSend={vi.fn()}
        onTranscribeAudio={onTranscribeAudio}
        placeholder="Type your message..."
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Voice input" }));
    expect(await screen.findByLabelText("Recording 0:00")).toBeInTheDocument();
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 1_150));
    });

    expect(screen.queryByText("No microphone input detected.")).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Stop recording" }));

    await waitFor(() => expect(onTranscribeAudio).toHaveBeenCalledTimes(1));
    expect(screen.getByDisplayValue("quiet voice")).toBeInTheDocument();
  });

  it("does not treat unavailable microphone levels as silence", async () => {
    mockVoiceRecorder();
    mockVoiceAudioInput(128, "suspended");
    const onTranscribeAudio = vi.fn(async () => "voice text");
    render(
      <ThreadComposer
        onSend={vi.fn()}
        onTranscribeAudio={onTranscribeAudio}
        placeholder="Type your message..."
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Voice input" }));
    expect(await screen.findByLabelText("Recording 0:00")).toBeInTheDocument();
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 1_150));
    });

    expect(screen.queryByText("No microphone input detected.")).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Stop recording" }));

    await waitFor(() => expect(onTranscribeAudio).toHaveBeenCalledTimes(1));
    expect(screen.getByDisplayValue("voice text")).toBeInTheDocument();
  });

  it("renders and changes workspace access mode", async () => {
    const onWorkspaceScopeChange = vi.fn();
    render(
      <ThreadComposer
        onSend={vi.fn()}
        placeholder="Type your message..."
        workspaceScope={{
          project_path: "/tmp/project",
          project_name: "project",
          access_mode: "restricted",
          restrict_to_workspace: true,
        }}
        workspaceControls={{ can_change_project: true, can_use_full_access: true }}
        onWorkspaceScopeChange={onWorkspaceScopeChange}
      />,
    );

    fireEvent.pointerDown(screen.getByRole("button", { name: /Workspace access mode/ }));
    fireEvent.click(await screen.findByRole("menuitem", { name: /Full Access/ }));

    expect(onWorkspaceScopeChange).toHaveBeenCalledWith(
      expect.objectContaining({
        project_path: "/tmp/project",
        access_mode: "full",
        restrict_to_workspace: false,
      }),
    );
  });

  it("exposes full and compact workspace labels for container-driven compression", () => {
    render(
      <ThreadComposer
        onSend={vi.fn()}
        placeholder="Type your message..."
        variant="hero"
        workspaceScope={{
          project_path: "/tmp/project",
          project_name: "project",
          access_mode: "full",
          restrict_to_workspace: false,
        }}
        workspaceControls={{ can_change_project: true, can_use_full_access: true }}
        onWorkspaceScopeChange={vi.fn()}
      />,
    );

    const accessButton = screen.getByRole("button", {
      name: "Workspace access mode: Full Access",
    });
    const fullLabel = within(accessButton).getByText("Full Access");
    const shortLabel = within(accessButton).getByText("Full");
    expect(accessButton).toHaveAttribute("title", "Full Access");
    expect(fullLabel).toHaveClass("thread-composer-access-label-full");
    expect(shortLabel).toHaveClass("thread-composer-access-label-short");
    expect(shortLabel).toHaveClass("hidden");
  });

  it("keeps project selection as a compact composer dropdown", async () => {
    const user = userEvent.setup();
    const onWorkspaceScopeChange = vi.fn();
    const defaultScope = {
      project_path: "/Users/test/.nanobot/workspace",
      project_name: "workspace",
      access_mode: "restricted" as const,
      restrict_to_workspace: true,
    };
    render(
      <ThreadComposer
        onSend={vi.fn()}
        placeholder="Ask anything..."
        variant="hero"
        workspaceScope={{
          ...defaultScope,
          access_mode: "full",
          restrict_to_workspace: false,
        }}
        workspaceDefaultScope={defaultScope}
        workspaceControls={{ can_change_project: true, can_use_full_access: true }}
        onWorkspaceScopeChange={onWorkspaceScopeChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Choose project" }));

    expect(await screen.findByRole("button", { name: /Default workspace/ })).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    const input = screen.getByLabelText("Paste path");
    fireEvent.change(input, { target: { value: "relative/project" } });
    fireEvent.click(screen.getByRole("button", { name: "Use Path" }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Enter an absolute folder path on this machine.",
    );
    expect(onWorkspaceScopeChange).not.toHaveBeenCalled();

    fireEvent.change(input, { target: { value: "/Users/test/project-alpha" } });
    fireEvent.click(screen.getByRole("button", { name: "Use Path" }));

    expect(onWorkspaceScopeChange).toHaveBeenCalledWith(expect.objectContaining({
      project_path: "/Users/test/project-alpha",
      project_name: "project-alpha",
      access_mode: "full",
      restrict_to_workspace: false,
    }));

    await user.click(screen.getByRole("button", { name: "Choose project" }));
    const reopenedInput = await screen.findByLabelText("Paste path");
    fireEvent.change(reopenedInput, { target: { value: "~/Pictures/Photos" } });
    fireEvent.click(screen.getByRole("button", { name: "Use Path" }));

    expect(onWorkspaceScopeChange).toHaveBeenLastCalledWith(expect.objectContaining({
      project_path: "~/Pictures/Photos",
      project_name: "Photos",
      access_mode: "full",
      restrict_to_workspace: false,
    }));
  });

  it.each([
    ["Windows", "D:\\Users\\test\\.nanobot\\workspace", "D:\\path\\to\\project"],
    ["macOS", "/Users/test/.nanobot/workspace", "/Users/name/project"],
    ["Linux", "/home/test/.nanobot/workspace", "/home/name/project"],
  ])("uses a %s path example for the project picker", async (_, projectPath, placeholder) => {
    const user = userEvent.setup();
    const defaultScope = {
      project_path: projectPath,
      project_name: "workspace",
      access_mode: "restricted" as const,
      restrict_to_workspace: true,
    };

    render(
      <ThreadComposer
        onSend={vi.fn()}
        placeholder="Ask anything..."
        variant="hero"
        workspaceScope={defaultScope}
        workspaceDefaultScope={defaultScope}
        workspaceControls={{ can_change_project: true, can_use_full_access: true }}
        onWorkspaceScopeChange={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Choose project" }));

    expect(await screen.findByLabelText("Paste path")).toHaveAttribute("placeholder", placeholder);
  });

  it("slides project controls closed without offering a compact replacement", () => {
    const defaultScope = {
      project_path: "/Users/test/.nanobot/workspace",
      project_name: "workspace",
      access_mode: "full" as const,
      restrict_to_workspace: false,
    };
    const composer = (workspaceControlsHidden: boolean) => (
      <ThreadComposer
        onSend={vi.fn()}
        placeholder="Ask anything..."
        variant="hero"
        workspaceControlsHidden={workspaceControlsHidden}
        workspaceScope={defaultScope}
        workspaceDefaultScope={defaultScope}
        workspaceControls={{ can_change_project: true, can_use_full_access: true }}
        onWorkspaceScopeChange={vi.fn()}
      />
    );
    const { container, rerender } = render(composer(false));
    const drawer = container.querySelector("[data-composer-workspace-drawer]");

    expect(drawer).toHaveAttribute("data-state", "open");
    expect(drawer).not.toHaveAttribute("aria-hidden");
    expect(container.querySelector("[data-composer-workspace-compact]")).not.toBeInTheDocument();

    rerender(composer(true));

    expect(container.querySelector("[data-composer-workspace-drawer]")).toBe(drawer);
    expect(drawer).toHaveAttribute("data-state", "closed");
    expect(drawer).toHaveAttribute("aria-hidden", "true");
    expect(within(drawer as HTMLElement).getByRole("button", {
      hidden: true,
      name: "Choose project",
    })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Choose project" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", {
      name: "Workspace access mode: Full Access",
    })).not.toBeInTheDocument();

    rerender(composer(false));

    expect(container.querySelector("[data-composer-workspace-drawer]")).toBe(drawer);
    expect(drawer).toHaveAttribute("data-state", "open");
    expect(within(drawer as HTMLElement).getByRole("button", {
      name: "Choose project",
    })).toBeEnabled();
  });

  it("uses the native folder picker for project selection on native host", async () => {
    const onWorkspaceScopeChange = vi.fn();
    const pickFolder = vi.fn().mockResolvedValue("/Users/test/native-project");
    const defaultScope = {
      project_path: "/Users/test/.nanobot/workspace",
      project_name: "workspace",
      access_mode: "full" as const,
      restrict_to_workspace: false,
    };
    Object.defineProperty(window, "nanobotHost", {
      configurable: true,
      value: {
        getRuntimeInfo: vi.fn(),
        restartEngine: vi.fn(),
        pickFolder,
        openLogs: vi.fn(),
        exportDiagnostics: vi.fn(),
      },
    });

    render(
      <ThreadComposer
        onSend={vi.fn()}
        placeholder="Ask anything..."
        variant="hero"
        workspaceScope={defaultScope}
        workspaceDefaultScope={defaultScope}
        workspaceControls={{
          can_change_project: true,
          can_use_full_access: true,
          can_pick_folder: true,
        }}
        onWorkspaceScopeChange={onWorkspaceScopeChange}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Choose project" }));

    await waitFor(() => expect(pickFolder).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: /Default workspace/ })).not.toBeInTheDocument();
    expect(onWorkspaceScopeChange).toHaveBeenCalledWith(expect.objectContaining({
      project_path: "/Users/test/native-project",
      project_name: "native-project",
      access_mode: "full",
      restrict_to_workspace: false,
    }));
  });

  it("does not use a native host picker when the gateway disallows folder picking", async () => {
    const user = userEvent.setup();
    const onWorkspaceScopeChange = vi.fn();
    const pickFolder = vi.fn().mockResolvedValue("/Users/test/native-project");
    const onPickWorkspaceFolder = vi.fn().mockResolvedValue("/srv/nas-project");
    const defaultScope = {
      project_path: "/srv/nanobot/workspace",
      project_name: "workspace",
      access_mode: "full" as const,
      restrict_to_workspace: false,
    };
    Object.defineProperty(window, "nanobotHost", {
      configurable: true,
      value: { pickFolder },
    });

    render(
      <ThreadComposer
        onSend={vi.fn()}
        placeholder="Ask anything..."
        variant="hero"
        workspaceScope={defaultScope}
        workspaceDefaultScope={defaultScope}
        workspaceControls={{
          can_change_project: true,
          can_use_full_access: true,
          can_pick_folder: false,
        }}
        onPickWorkspaceFolder={onPickWorkspaceFolder}
        onWorkspaceScopeChange={onWorkspaceScopeChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Choose project" }));

    expect(await screen.findByLabelText("Paste path")).toBeInTheDocument();
    expect(pickFolder).not.toHaveBeenCalled();
    expect(onPickWorkspaceFolder).not.toHaveBeenCalled();
  });

  it("uses the gateway folder picker for a locally hosted WebUI", async () => {
    const onWorkspaceScopeChange = vi.fn();
    const pickFolder = vi.fn().mockResolvedValue("/Users/test/gateway-project");
    const defaultScope = {
      project_path: "/Users/test/.nanobot/workspace",
      project_name: "workspace",
      access_mode: "full" as const,
      restrict_to_workspace: false,
    };

    render(
      <ThreadComposer
        onSend={vi.fn()}
        placeholder="Ask anything..."
        variant="hero"
        workspaceScope={defaultScope}
        workspaceDefaultScope={defaultScope}
        workspaceControls={{
          can_change_project: true,
          can_use_full_access: true,
          can_pick_folder: true,
        }}
        onPickWorkspaceFolder={pickFolder}
        onWorkspaceScopeChange={onWorkspaceScopeChange}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Choose project" }));

    await waitFor(() => expect(pickFolder).toHaveBeenCalled());
    expect(screen.queryByLabelText("Paste path")).not.toBeInTheDocument();
    expect(onWorkspaceScopeChange).toHaveBeenCalledWith(expect.objectContaining({
      project_path: "/Users/test/gateway-project",
      project_name: "gateway-project",
      access_mode: "full",
      restrict_to_workspace: false,
    }));
  });

  it("uses the web path menu when no native host picker is available", async () => {
    const user = userEvent.setup();
    const defaultScope = {
      project_path: "/Users/test/.nanobot/workspace",
      project_name: "workspace",
      access_mode: "full" as const,
      restrict_to_workspace: false,
    };

    render(
      <ThreadComposer
        onSend={vi.fn()}
        placeholder="Ask anything..."
        variant="hero"
        workspaceScope={defaultScope}
        workspaceDefaultScope={defaultScope}
        workspaceControls={{ can_change_project: true, can_use_full_access: true }}
        onWorkspaceScopeChange={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Choose project" }));

    expect(await screen.findByRole("button", { name: /Default workspace/ })).toBeInTheDocument();
    expect(screen.getByLabelText("Paste path")).toBeInTheDocument();
  });

  it("closes the sustained goal through its existing drawer", () => {
    const { container, rerender } = render(
      <ThreadComposer
        onSend={vi.fn()}
        placeholder="Type your message..."
        goalState={{
          active: true,
          objective: "Ship the release",
          ui_summary: "Preparing release",
        }}
      />,
    );

    const drawer = container.querySelector("[data-composer-status-drawer]");
    expect(drawer).not.toBeNull();
    expect(drawer).toHaveAttribute("data-state", "open");
    expect(drawer).not.toHaveAttribute("aria-hidden");
    const status = screen.getByRole("status");
    expect(status).toHaveClass("composer-status-drawer-content");

    rerender(
      <ThreadComposer
        onSend={vi.fn()}
        placeholder="Type your message..."
        goalState={{ active: false }}
      />,
    );

    expect(container.querySelector("[data-composer-status-drawer]")).toBe(drawer);
    expect(drawer).toHaveAttribute("data-state", "closed");
    expect(drawer).toHaveAttribute("aria-hidden", "true");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(drawer?.querySelector('[role="status"]')).toBe(status);

    fireEvent.transitionEnd(drawer as Element, { propertyName: "grid-template-rows" });
    expect(container.querySelector("[data-composer-status-drawer]")).toBeNull();
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
    expect(screen.queryByRole("option", { name: /\/stop/i })).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: /\/history/i })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    fireEvent.keyDown(input, { key: "Enter" });

    expect(input).toHaveValue("/history ");
    expect(onSend).not.toHaveBeenCalled();
    expect(screen.queryByRole("listbox", { name: "Slash commands" })).not.toBeInTheDocument();
  });

  it("offers stop autocomplete once the user starts typing it", () => {
    const onSend = vi.fn();
    render(
      <ThreadComposer
        onSend={onSend}
        placeholder="Type your message..."
        slashCommands={COMMANDS}
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "/sto" } });

    expect(screen.getByRole("option", { name: /\/stop/i })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    fireEvent.keyDown(input, { key: "Enter" });

    expect(input).toHaveValue("/stop");
    expect(onSend).not.toHaveBeenCalled();
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
            lifecycle: "side_channel",
            acceptsArgs: true,
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
        slashCommands={COMMANDS}
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
    expect(window.localStorage.getItem("nanobot.webui.slashCommandRecents")).toBeNull();
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

  it("keeps keyboard-selected slash options visible while navigating", () => {
    const scrollIntoView = vi.fn();
    const originalScrollIntoView = HTMLElement.prototype.scrollIntoView;
    HTMLElement.prototype.scrollIntoView = scrollIntoView;

    try {
      render(
        <ThreadComposer
          onSend={vi.fn()}
          placeholder="Type your message..."
          slashCommands={Array.from({ length: 8 }, (_, index) => ({
            command: `/cmd-${index}`,
            title: `Command ${index}`,
            description: `Description ${index}`,
            icon: "activity",
            lifecycle: "side_channel",
            acceptsArgs: false,
          }))}
        />,
      );

      const input = screen.getByLabelText("Message input");
      fireEvent.change(input, { target: { value: "/" } });
      scrollIntoView.mockClear();

      fireEvent.keyDown(input, { key: "ArrowDown" });
      fireEvent.keyDown(input, { key: "ArrowDown" });

      expect(screen.getByRole("option", { name: /\/cmd-2/i })).toHaveAttribute(
        "aria-selected",
        "true",
      );
      expect(scrollIntoView).toHaveBeenLastCalledWith({ block: "nearest" });
    } finally {
      HTMLElement.prototype.scrollIntoView = originalScrollIntoView;
    }
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

    const palette = screen.getByRole("listbox", { name: "Mentions" });
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
    expect(screen.queryByRole("listbox", { name: "Mentions" })).not.toBeInTheDocument();

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

  it("keeps keyboard-selected mention options visible while navigating", () => {
    const scrollIntoView = vi.fn();
    const originalScrollIntoView = HTMLElement.prototype.scrollIntoView;
    HTMLElement.prototype.scrollIntoView = scrollIntoView;

    try {
      render(
        <ThreadComposer
          onSend={vi.fn()}
          placeholder="Type your message..."
          cliApps={Array.from({ length: 8 }, (_, index) => ({
            name: `app-${index}`,
            display_name: `App ${index}`,
            category: "test",
            description: "Test app",
            requires: "",
            source: "harness",
            entry_point: `app-${index}`,
            install_supported: true,
            installed: true,
            available: true,
            status: "installed",
            logo_url: null,
            brand_color: "#111827",
            skill_installed: true,
          }))}
        />,
      );

      const input = screen.getByLabelText("Message input");
      fireEvent.change(input, { target: { value: "@", selectionStart: 1 } });
      scrollIntoView.mockClear();

      fireEvent.keyDown(input, { key: "ArrowDown" });
      fireEvent.keyDown(input, { key: "ArrowDown" });

      expect(screen.getByRole("option", { name: /@app-2/i })).toHaveAttribute(
        "aria-selected",
        "true",
      );
      expect(scrollIntoView).toHaveBeenLastCalledWith({ block: "nearest" });
    } finally {
      HTMLElement.prototype.scrollIntoView = originalScrollIntoView;
    }
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
    const mention = screen.getByTestId("composer-mcp-mention-browserbase");
    expect(mention).toHaveTextContent("@browserbase");
    expect(mention).toHaveClass("font-normal");
    expect(mention).not.toHaveClass("font-[550]");

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

  it("attaches persisted sessions only through the shared mention palette", () => {
    const onSend = vi.fn();
    render(
      <ThreadComposer
        onSend={onSend}
        placeholder="Type your message..."
        sessions={[session("pricing", "收费设计", "讨论云存储")]}
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, {
      target: { value: "普通文字 @收费设计", selectionStart: 10 },
    });
    expect(screen.queryByTestId("composer-session-mention-收费设计")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect(onSend).toHaveBeenLastCalledWith("普通文字 @收费设计", undefined, undefined);

    fireEvent.change(input, {
      target: { value: "参考 @收费", selectionStart: 6 },
    });

    expect(screen.getByRole("group", { name: "Nanobot conversations" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /@收费设计/i })).toBeInTheDocument();
    fireEvent.keyDown(input, { key: "Tab" });

    expect(input).toHaveValue("参考 @收费设计 ");
    const mention = screen.getByTestId("composer-session-mention-收费设计");
    expect(mention).toHaveTextContent("@收费设计");
    expect(mention).toHaveClass("font-normal");
    expect(mention).not.toHaveClass("font-[550]");
    expect(mention.closest("a")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(onSend).toHaveBeenCalledWith("参考 @收费设计", undefined, {
      sessionMentions: [{
        id: session("pricing", "收费设计").handle?.id,
        name: "收费设计",
        session_key: "websocket:pricing",
        title: "收费设计",
      }],
    });
  });

  it("turns a dropped sidebar session into the shared structured mention", () => {
    const onSend = vi.fn();
    render(
      <ThreadComposer
        onSend={onSend}
        placeholder="Type your message..."
        sessions={[session("pricing", "收费设计", "讨论云存储")]}
      />,
    );

    const input = screen.getByLabelText("Message input") as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "Compare notes" } });
    input.setSelectionRange(7, 7);
    const dataTransfer = {
      types: [SESSION_DRAG_TYPE],
      effectAllowed: "copy",
      dropEffect: "none",
      files: [],
      getData: (type: string) => (
        type === SESSION_DRAG_TYPE ? "websocket:pricing" : ""
      ),
    };

    fireEvent.dragEnter(input, { dataTransfer });
    fireEvent.dragOver(input, { dataTransfer });

    expect(input).toHaveValue("Compare notes");
    expect(screen.getByTestId("composer-session-drag-preview"))
      .toHaveTextContent("@收费设计");

    fireEvent.dragEnd(document);
    expect(screen.queryByTestId("composer-session-drag-preview")).not.toBeInTheDocument();

    fireEvent.dragEnter(input, { dataTransfer });
    fireEvent.dragOver(input, { dataTransfer });

    fireEvent.drop(input, { dataTransfer });

    expect(input).toHaveValue("Compare @收费设计 notes");
    expect(screen.queryByTestId("composer-session-drag-preview")).not.toBeInTheDocument();
    expect(screen.getByTestId("composer-session-mention-收费设计"))
      .toHaveTextContent("@收费设计");

    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect(onSend).toHaveBeenCalledWith("Compare @收费设计 notes", undefined, {
      sessionMentions: [{
        id: session("pricing", "收费设计").handle?.id,
        name: "收费设计",
        session_key: "websocket:pricing",
        title: "收费设计",
      }],
    });
  });

  it("rejects self-session drops that are unavailable to the composer", () => {
    render(
      <ThreadComposer
        onSend={vi.fn()}
        placeholder="Type your message..."
        sessions={[]}
      />,
    );
    const input = screen.getByLabelText("Message input");
    const dataTransfer = {
      types: [SESSION_DRAG_TYPE],
      effectAllowed: "copyMove",
      dropEffect: "copy",
      files: [],
      getData: () => "websocket:current",
    };

    expect(fireEvent.dragEnter(input, { dataTransfer })).toBe(true);
    expect(fireEvent.dragOver(input, { dataTransfer })).toBe(true);
    expect(screen.queryByTestId("composer-session-drag-preview")).not.toBeInTheDocument();
  });

  it("releases the eight-session limit when a mention is removed", () => {
    const onSend = vi.fn();
    render(
      <ThreadComposer
        onSend={onSend}
        placeholder="Type your message..."
        sessions={Array.from(
          { length: 9 },
          (_, index) => session(`topic-${index}`, `Topic${index}`),
        )}
      />,
    );

    const input = screen.getByLabelText("Message input") as HTMLTextAreaElement;
    for (let index = 0; index < 8; index += 1) {
      const value = `${input.value}${input.value ? " " : ""}@Topic${index}`;
      fireEvent.change(input, { target: { value, selectionStart: value.length } });
      fireEvent.keyDown(input, { key: "Tab" });
    }
    const replacement = `${input.value.replace("@Topic0 ", "")} @Topic8`;
    fireEvent.change(input, {
      target: { value: replacement, selectionStart: replacement.length },
    });
    fireEvent.keyDown(input, { key: "Tab" });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    const options = onSend.mock.calls[0]?.[2];
    expect(options.sessionMentions).toHaveLength(8);
    expect(options.sessionMentions.map((mention: { session_key: string }) => (
      mention.session_key
    ))).toEqual(expect.arrayContaining(["websocket:topic-8"]));
  });

  it("keeps a selected session stable across refreshes and queued guidance", () => {
    const onSend = vi.fn();
    const target = session("z-target", "Plan", "Original plan");
    const { rerender } = render(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        isStreaming
        placeholder="Type your message..."
        sessions={[target]}
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "@", selectionStart: 1 } });
    fireEvent.keyDown(input, { key: "Tab" });

    rerender(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        isStreaming
        placeholder="Type your message..."
        sessions={[
          { ...target, title: "Renamed plan" },
          session("a-new", "Plan", target.preview),
        ]}
      />,
    );

    expect(screen.getByTestId("composer-session-mention-Plan")).toHaveTextContent("@Plan");
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Guide" }));

    expect(onSend).toHaveBeenCalledWith("@Plan", undefined, {
      sessionMentions: [{
        id: session("z-target", "Plan").handle?.id,
        name: "Plan",
        session_key: "websocket:z-target",
        title: "Plan",
      }],
      continueActiveTurn: true,
    });
  });

  it("opens skills only from a $ reference and prioritizes the skill name", () => {
    const skillName = "arxiv-intelligence-filter";
    render(
        <ThreadComposer
          onSend={vi.fn()}
          placeholder="Type your message..."
          skills={[
            {
              name: skillName,
              description: "Fetch and summarize the latest AI research papers every day",
              source: "builtin",
              enabled: true,
              available: true,
            },
            {
              name: "arxiv-disabled",
              description: "Disabled research workflow",
              source: "builtin",
              enabled: false,
              available: true,
            },
            {
              name: "arxiv-unavailable",
              description: "Unavailable research workflow",
              source: "builtin",
              enabled: true,
              available: false,
            },
          ]}
          slashCommands={COMMANDS}
        />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "/git", selectionStart: 4 } });
    expect(screen.queryByRole("listbox", { name: "Slash commands" })).not.toBeInTheDocument();

    fireEvent.change(input, { target: { value: "please use $arxiv", selectionStart: 17 } });

    const palette = screen.getByRole("listbox", { name: "Slash commands" });
    const option = within(palette).getByRole("option", { name: new RegExp(skillName, "i") });
    const name = within(option).getByText(skillName);
    expect(name).not.toHaveClass("truncate");
    expect(within(option).queryByText(`$${skillName}`)).not.toBeInTheDocument();
    expect(within(palette).queryByText("arxiv-disabled")).not.toBeInTheDocument();
    expect(within(palette).queryByText("arxiv-unavailable")).not.toBeInTheDocument();
    expect(within(palette).queryByText("/model")).not.toBeInTheDocument();

    fireEvent.keyDown(input, { key: "Tab" });

    expect(input).toHaveValue(`please use $${skillName} `);
  });

  it("ranks skill name matches ahead of earlier description matches", () => {
    render(
      <ThreadComposer
        onSend={vi.fn()}
        placeholder="Type your message..."
        skills={[
          {
            name: "skill-creator",
            description: "Create or update AgentSkills",
            source: "builtin",
            available: true,
          },
          {
            name: "setup-update",
            description: "Configure upgrades",
            source: "builtin",
            available: true,
          },
          {
            name: "update-setup",
            description: "One-time setup wizard",
            source: "builtin",
            available: true,
          },
          {
            name: "up",
            description: "Exact match",
            source: "workspace",
            available: true,
          },
        ]}
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "$up", selectionStart: 3 } });

    const options = within(screen.getByRole("listbox", { name: "Slash commands" }))
      .getAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual([
      "upExact match",
      "update-setupOne-time setup wizard",
      "setup-updateConfigure upgrades",
      "skill-creatorCreate or update AgentSkills",
    ]);
  });

  it("keeps a recently selected skill visible at the top of the blank skill menu", () => {
    const skills = Array.from({ length: 9 }, (_, index) => ({
      name: `skill-${index}`,
      description: `Skill ${index}`,
      source: "builtin",
      available: true,
    }));
    render(
      <ThreadComposer
        onSend={vi.fn()}
        placeholder="Type your message..."
        skills={skills}
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "$skill-8", selectionStart: 8 } });
    fireEvent.keyDown(input, { key: "Tab" });
    fireEvent.change(input, { target: { value: "$", selectionStart: 1 } });

    const options = within(screen.getByRole("listbox", { name: "Slash commands" }))
      .getAllByRole("option");
    expect(options).toHaveLength(8);
    expect(options[0]).toHaveTextContent("skill-8");
    expect(options[0]).toHaveTextContent("Recent");
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
    expect(token).toHaveClass("font-normal");
    expect(token).not.toHaveClass("font-[550]");
    expect(token.className).not.toContain("zoom-in");
    expect(token.className).not.toContain("px-");
    expect(token.className).not.toContain("mx-");
    expect(token.getAttribute("style")).toContain("color: #5C5543");
    expect(token.getAttribute("style")).not.toContain("text-shadow");
    expect(screen.queryByTestId("composer-cli-app-tray")).not.toBeInTheDocument();
    const logo = screen.getByTestId("composer-cli-mention-logo-gimp");
    expect(logo.className).toContain("top-1/2");
    expect(logo.className).toContain("left-1/2");
    expect(logo.className).not.toContain("-top-");
  });

  it("uses the shared accent when an installed CLI app has no brand metadata", () => {
    const mention = "@obsidian-agent-cli";
    const app: CliAppInfo = {
      name: "obsidian-agent-cli",
      display_name: "Obsidian CLI",
      category: "productivity",
      description: "Obsidian automation",
      requires: "",
      source: "local",
      entry_point: "obsidian-agent",
      install_supported: true,
      installed: true,
      available: true,
      status: "installed",
      logo_url: null,
      brand_color: null,
      skill_installed: true,
    };
    render(
      <ThreadComposer
        onSend={vi.fn()}
        placeholder="Type your message..."
        cliApps={[app]}
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, {
      target: { value: mention, selectionStart: mention.length },
    });

    const token = screen.getByTestId("composer-cli-mention-obsidian-agent-cli");
    expect(token.getAttribute("style")).toContain("var(--inline-token-highlight)");
    expect(token.getAttribute("style")).not.toContain("var(--primary)");
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

  it("keeps the slash command palette above a keyboard-constrained visual viewport", async () => {
    vi.spyOn(HTMLFormElement.prototype, "getBoundingClientRect").mockReturnValue(
      rect({ top: 120, bottom: 220, width: 390, height: 100 }),
    );
    Object.defineProperty(window, "innerHeight", {
      value: 800,
      configurable: true,
    });
    stubVisualViewport({ height: 300 });
    render(
      <ThreadComposer
        onSend={vi.fn()}
        placeholder="Ask anything..."
        slashCommands={COMMANDS}
      />,
    );
    const input = screen.getByLabelText("Message input");

    fireEvent.change(input, { target: { value: "/" } });

    await waitFor(() => {
      const palette = screen.getByRole("listbox", { name: "Slash commands" });
      expect(palette.className).toContain("bottom-full");
      expect(palette).toHaveStyle({ maxHeight: "112px" });
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

  it("keeps image generation mode out of the composer chrome", () => {
    const onSend = vi.fn();
    render(
      <ThreadComposer
        onSend={onSend}
        placeholder="Type your message..."
      />,
    );

    expect(screen.queryByRole("button", { name: "Toggle image generation mode" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Image aspect ratio" })).not.toBeInTheDocument();

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "Draw a friendly robot" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(onSend).toHaveBeenCalledWith("Draw a friendly robot", undefined, undefined);
  });

  it("marks known slash commands as side-channel sends", () => {
    const onSend = vi.fn();
    render(
      <ThreadComposer
        onSend={onSend}
        placeholder="Type your message..."
        slashCommands={COMMANDS}
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "/history" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(onSend).toHaveBeenCalledWith("/history", undefined, { sideChannel: true });
  });

  it("does not infer side-channel behavior before command metadata loads", () => {
    const onSend = vi.fn();
    render(
      <ThreadComposer
        onSend={onSend}
        placeholder="Type your message..."
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "/status" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(onSend).toHaveBeenCalledWith("/status", undefined, undefined);
  });

  it("marks new chat commands as side-channel sends that finalize the active turn", () => {
    const onSend = vi.fn();
    render(
      <ThreadComposer
        onSend={onSend}
        placeholder="Type your message..."
        slashCommands={[
          {
            command: "/new",
            title: "New chat",
            description: "Reset this chat and start a fresh conversation.",
            icon: "square-pen",
            lifecycle: "finalize_active_turn",
            acceptsArgs: false,
          },
        ]}
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "/new" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(onSend).toHaveBeenCalledWith(
      "/new",
      undefined,
      { sideChannel: true, finalizeActiveTurn: true },
    );
  });

  it("does not classify exact-only slash commands with arguments", () => {
    const onSend = vi.fn();
    render(
      <ThreadComposer
        onSend={onSend}
        placeholder="Type your message..."
        slashCommands={[
          {
            command: "/new",
            title: "New chat",
            description: "Reset this chat and start a fresh conversation.",
            icon: "square-pen",
            lifecycle: "finalize_active_turn",
            acceptsArgs: false,
          },
        ]}
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "/new with a title" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(onSend).toHaveBeenCalledWith("/new with a title", undefined, undefined);
  });

  it("routes a manually submitted stop command through the stop handler", () => {
    const onSend = vi.fn();
    const onStop = vi.fn();
    render(
      <ThreadComposer
        onSend={onSend}
        onStop={onStop}
        isStreaming
        placeholder="Type your message..."
        slashCommands={COMMANDS}
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "/stop" } });
    fireEvent.keyDown(input, { key: "Escape" });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onStop).toHaveBeenCalledTimes(1);
    expect(onSend).not.toHaveBeenCalled();
  });

  it("keeps goal task commands on the normal agent turn path", () => {
    const onSend = vi.fn();
    render(
      <ThreadComposer
        onSend={onSend}
        placeholder="Type your message..."
        slashCommands={[
          {
            command: "/goal",
            title: "Start long-running goal",
            description: "Tell the agent to treat the request as a long-running goal.",
            icon: "activity",
            argHint: "<goal>",
            lifecycle: "agent_turn_with_args",
            acceptsArgs: true,
          },
        ]}
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "/goal fix the release blocker" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(onSend).toHaveBeenCalledWith(
      "/goal fix the release blocker",
      undefined,
      undefined,
    );
  });

  it("keeps goal usage commands on the side-channel path", () => {
    const onSend = vi.fn();
    render(
      <ThreadComposer
        onSend={onSend}
        placeholder="Type your message..."
        slashCommands={[
          {
            command: "/goal",
            title: "Start long-running goal",
            description: "Tell the agent to treat the request as a long-running goal.",
            icon: "activity",
            argHint: "<goal>",
            lifecycle: "agent_turn_with_args",
            acceptsArgs: true,
          },
        ]}
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "/goal" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(onSend).toHaveBeenCalledWith("/goal", undefined, { sideChannel: true });
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

  it("queues plain guidance while a task is running", () => {
    const onSend = vi.fn();
    render(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        isStreaming
        placeholder="Type your message..."
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "keep the UI minimal" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onSend).not.toHaveBeenCalled();
    expect(input).toHaveValue("");
    expect(screen.getByText("keep the UI minimal")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Guide" }));

    expect(onSend).toHaveBeenCalledWith(
      "keep the UI minimal",
      undefined,
      { continueActiveTurn: true },
    );
    expect(screen.queryByText("keep the UI minimal")).not.toBeInTheDocument();
  });

  it("guides queued guidance when Enter is pressed again", () => {
    const onSend = vi.fn();
    render(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        isStreaming
        placeholder="Type your message..."
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "send this guidance now" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onSend).not.toHaveBeenCalled();
    expect(input).toHaveValue("");
    expect(screen.getByText("send this guidance now")).toBeInTheDocument();

    fireEvent.keyDown(input, { key: "Enter", repeat: true });

    expect(onSend).not.toHaveBeenCalled();
    expect(screen.getByText("send this guidance now")).toBeInTheDocument();

    fireEvent.keyDown(input, { key: "Enter" });

    expect(onSend).toHaveBeenCalledWith(
      "send this guidance now",
      undefined,
      { continueActiveTurn: true },
    );
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("send this guidance now")).not.toBeInTheDocument();
  });

  it("disarms the second Enter shortcut when keyboard voice recording starts", async () => {
    mockVoiceRecorder();
    const onSend = vi.fn();
    const onTranscribeAudio = vi.fn(async () => "voice guidance");
    render(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        onTranscribeAudio={onTranscribeAudio}
        isStreaming
        placeholder="Type your message..."
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "keep this queued" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.keyDown(window, { code: "KeyD", ctrlKey: true, key: "D", shiftKey: true });

    expect(await screen.findByLabelText("Recording 0:00")).toBeInTheDocument();
    expect(input).toHaveFocus();
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onSend).not.toHaveBeenCalled();
    expect(screen.getByText("keep this queued")).toBeInTheDocument();

    await waitForVoiceCapture();
    fireEvent.keyUp(window, { code: "KeyD", ctrlKey: true, key: "D", shiftKey: true });
    await waitFor(() => expect(onTranscribeAudio).toHaveBeenCalled());
  });

  it("disarms the second Enter shortcut after stopping the active response", () => {
    const onSend = vi.fn();
    const onStop = vi.fn();
    const { rerender } = render(
      <ThreadComposer
        onSend={onSend}
        onStop={onStop}
        isStreaming
        placeholder="Type your message..."
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "keep this queued" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Stop response" }));
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onStop).toHaveBeenCalledTimes(1);
    expect(onSend).not.toHaveBeenCalled();
    expect(screen.getByText("keep this queued")).toBeInTheDocument();

    rerender(
      <ThreadComposer
        onSend={onSend}
        onStop={onStop}
        isStreaming={false}
        placeholder="Type your message..."
      />,
    );
    rerender(
      <ThreadComposer
        onSend={onSend}
        onStop={onStop}
        isStreaming
        placeholder="Type your message..."
      />,
    );
    fireEvent.keyDown(screen.getByLabelText("Message input"), { key: "Enter" });

    expect(onSend).not.toHaveBeenCalled();
    expect(screen.getByText("keep this queued")).toBeInTheDocument();
  });

  it("disarms the second Enter shortcut when the composer loses focus", () => {
    const onSend = vi.fn();
    render(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        isStreaming
        placeholder="Type your message..."
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "leave this queued" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.blur(input);
    fireEvent.focus(input);
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onSend).not.toHaveBeenCalled();
    expect(screen.getByText("leave this queued")).toBeInTheDocument();
  });

  it("guides the newly queued prompt when older guidance is still waiting", () => {
    const onSend = vi.fn();
    render(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        isStreaming
        placeholder="Type your message..."
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "older guidance" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.change(input, { target: { value: "guide this one now" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onSend).toHaveBeenCalledWith(
      "guide this one now",
      undefined,
      { continueActiveTurn: true },
    );
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(screen.getByText("older guidance")).toBeInTheDocument();
    expect(screen.queryByText("guide this one now")).not.toBeInTheDocument();
  });

  it("keeps queued guidance attached to the composer and sends it one item at a time", async () => {
    const onSend = vi.fn();
    const { rerender } = render(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        isStreaming
        placeholder="Type your message..."
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "first follow-up" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.change(input, { target: { value: "second follow-up" } });
    fireEvent.keyDown(input, { key: "Enter" });

    const queue = screen.getByRole("group", { name: "Queued guidance" });
    expect(queue).toHaveClass("composer-status-strip");
    expect(queue).toHaveClass("mx-3");
    expect(queue.parentElement?.className).toContain("group/composer");
    expect(within(queue).getByText("first follow-up")).toBeInTheDocument();
    expect(within(queue).getByText("second follow-up")).toBeInTheDocument();
    expect(within(queue).getAllByRole("button", { name: "Edit guidance" })).toHaveLength(2);
    expect(within(queue).getAllByRole("button", { name: "Guide" })).toHaveLength(2);

    rerender(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        isStreaming={false}
        placeholder="Type your message..."
      />,
    );

    await waitFor(() => {
      expect(onSend).toHaveBeenCalledWith("first follow-up");
    });
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("first follow-up")).not.toBeInTheDocument();
    expect(screen.getByText("second follow-up")).toBeInTheDocument();

    rerender(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        isStreaming
        placeholder="Type your message..."
      />,
    );
    rerender(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        isStreaming={false}
        placeholder="Type your message..."
      />,
    );

    await waitFor(() => {
      expect(onSend).toHaveBeenLastCalledWith("second follow-up");
    });
    expect(onSend).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("group", { name: "Queued guidance" })).not.toBeInTheDocument();
  });

  it("lets users edit queued guidance before it is sent", async () => {
    const onSend = vi.fn();
    const { rerender } = render(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        isStreaming
        placeholder="Type your message..."
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "rough follow-up" } });
    fireEvent.keyDown(input, { key: "Enter" });

    const editButton = screen.getByRole("button", { name: "Edit guidance" });
    fireEvent.click(editButton);
    await waitFor(() => {
      expect(input).toHaveFocus();
    });
    expect(input).toHaveValue("rough follow-up");
    expect(screen.queryByRole("group", { name: "Queued guidance" })).not.toBeInTheDocument();
    fireEvent.change(input, { target: { value: "polished follow-up" } });
    fireEvent.keyDown(input, { key: "Enter" });

    rerender(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        isStreaming={false}
        placeholder="Type your message..."
      />,
    );

    await waitFor(() => {
      expect(onSend).toHaveBeenCalledWith("polished follow-up");
    });
  });

  it("requeues edited guidance at the end of the pending list", async () => {
    const onSend = vi.fn();
    const { rerender } = render(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        isStreaming
        placeholder="Type your message..."
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "first follow-up" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.change(input, { target: { value: "second follow-up" } });
    fireEvent.keyDown(input, { key: "Enter" });

    fireEvent.click(screen.getAllByRole("button", { name: "Edit guidance" })[0]);
    await waitFor(() => {
      expect(input).toHaveValue("first follow-up");
    });
    fireEvent.change(input, { target: { value: "first follow-up edited" } });
    fireEvent.keyDown(input, { key: "Enter" });

    rerender(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        isStreaming={false}
        placeholder="Type your message..."
      />,
    );

    await waitFor(() => {
      expect(onSend).toHaveBeenCalledWith("second follow-up");
    });
    expect(onSend).toHaveBeenCalledTimes(1);

    rerender(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        isStreaming
        placeholder="Type your message..."
      />,
    );
    rerender(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        isStreaming={false}
        placeholder="Type your message..."
      />,
    );

    await waitFor(() => {
      expect(onSend).toHaveBeenLastCalledWith("first follow-up edited");
    });
    expect(onSend).toHaveBeenCalledTimes(2);
  });

  it("queues image guidance while running and restores it for editing", async () => {
    mockBlobUrls();
    const onSend = vi.fn();
    const { container, rerender } = render(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        isStreaming
        placeholder="Type your message..."
      />,
    );

    const input = screen.getByLabelText("Message input");
    const fileInput = container.querySelector<HTMLInputElement>('input[type="file"]');
    expect(fileInput).toBeTruthy();
    const file = new File(["image"], "draft.png", { type: "image/png" });
    fireEvent.change(fileInput!, { target: { files: [file] } });
    await screen.findByText("draft.png");

    fireEvent.change(input, { target: { value: "look at this" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onSend).not.toHaveBeenCalled();
    expect(screen.getByRole("group", { name: "Queued guidance" })).toBeInTheDocument();
    expect(screen.getByText("look at this")).toBeInTheDocument();
    expect(screen.queryByTestId("composer-chip")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Edit guidance" }));
    expect(input).toHaveValue("look at this");
    expect(screen.getByTestId("composer-chip")).toHaveTextContent("draft.png");
    expect(screen.queryByRole("group", { name: "Queued guidance" })).not.toBeInTheDocument();

    fireEvent.keyDown(input, { key: "Enter" });
    rerender(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        isStreaming={false}
        placeholder="Type your message..."
      />,
    );

    await waitFor(() => {
      expect(onSend).toHaveBeenCalledWith(
        "look at this",
        [expect.objectContaining({
          media: expect.objectContaining({
            data_url: "data:image/png;base64,aW1hZ2U=",
            name: "draft.png",
          }),
        })],
      );
    });
  });

  it("reorders queued guidance while dragging over another row", async () => {
    const onSend = vi.fn();
    const { rerender } = render(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        isStreaming
        placeholder="Type your message..."
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "first follow-up" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.change(input, { target: { value: "second follow-up" } });
    fireEvent.keyDown(input, { key: "Enter" });

    const handles = screen.getAllByLabelText("Drag to reorder");
    const secondRow = screen
      .getByText("second follow-up")
      .closest("[data-queued-prompt-row='true']");
    expect(secondRow).toBeTruthy();

    const dataTransfer = {
      effectAllowed: "",
      dropEffect: "",
      setData: vi.fn(),
      getData: vi.fn(),
    };
    fireEvent.dragStart(handles[0], { dataTransfer });
    fireEvent.dragEnter(secondRow!, { dataTransfer });
    fireEvent.dragEnd(handles[0], { dataTransfer });

    rerender(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        isStreaming={false}
        placeholder="Type your message..."
      />,
    );

    await waitFor(() => {
      expect(onSend).toHaveBeenCalledWith("second follow-up");
    });
  });

  it("moves later queued guidance before an earlier item while dragging", async () => {
    const onSend = vi.fn();
    const { rerender } = render(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        isStreaming
        placeholder="Type your message..."
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "first follow-up" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.change(input, { target: { value: "second follow-up" } });
    fireEvent.keyDown(input, { key: "Enter" });

    const handles = screen.getAllByLabelText("Drag to reorder");
    const firstRow = screen
      .getByText("first follow-up")
      .closest("[data-queued-prompt-row='true']");
    expect(firstRow).toBeTruthy();

    const dataTransfer = {
      effectAllowed: "",
      dropEffect: "",
      setData: vi.fn(),
      getData: vi.fn(),
    };
    fireEvent.dragStart(handles[1], { dataTransfer });
    fireEvent.dragEnter(firstRow!, { dataTransfer });
    fireEvent.dragEnd(handles[1], { dataTransfer });

    rerender(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        isStreaming={false}
        placeholder="Type your message..."
      />,
    );

    await waitFor(() => {
      expect(onSend).toHaveBeenCalledWith("second follow-up");
    });
  });

  it("persists queued guidance per chat across remounts", async () => {
    const onSend = vi.fn();
    const { rerender, unmount } = render(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        isStreaming
        pendingQueueKey="chat-a"
        placeholder="Type your message..."
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "remember this follow-up" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Edit guidance" }));
    fireEvent.change(input, { target: { value: "remember this edited follow-up" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByText("remember this edited follow-up")).toBeInTheDocument();

    rerender(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        isStreaming
        pendingQueueKey="chat-b"
        placeholder="Type your message..."
      />,
    );
    await waitFor(() => {
      expect(screen.queryByText("remember this edited follow-up")).not.toBeInTheDocument();
    });

    rerender(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        isStreaming
        pendingQueueKey="chat-a"
        placeholder="Type your message..."
      />,
    );
    expect(await screen.findByText("remember this edited follow-up")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByLabelText("Message input"), { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();

    unmount();
    const remount = render(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        isStreaming
        pendingQueueKey="chat-a"
        placeholder="Type your message..."
      />,
    );

    expect(await screen.findByText("remember this edited follow-up")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByLabelText("Message input"), { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Guide" }));
    expect(onSend).toHaveBeenCalledWith(
      "remember this edited follow-up",
      undefined,
      { continueActiveTurn: true },
    );

    remount.unmount();
    render(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        isStreaming
        pendingQueueKey="chat-a"
        placeholder="Type your message..."
      />,
    );
    await waitFor(() => {
      expect(screen.queryByText("remember this edited follow-up")).not.toBeInTheDocument();
    });
  });

  it("keeps temporary chat guidance in memory only", async () => {
    const onSend = vi.fn();
    const view = render(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        isStreaming
        pendingQueueKey={null}
        placeholder="Type your message..."
      />,
    );

    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "do not persist this" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(await screen.findByText("do not persist this")).toBeInTheDocument();
    expect(
      window.localStorage.getItem(
        "nanobot.webui.composerQueuedGuidance.v1:temporary-private",
      ),
    ).toBeNull();

    view.unmount();
    render(
      <ThreadComposer
        onSend={onSend}
        onStop={vi.fn()}
        isStreaming
        pendingQueueKey={null}
        placeholder="Type your message..."
      />,
    );

    await waitFor(() => {
      expect(screen.queryByText("do not persist this")).not.toBeInTheDocument();
    });
    expect(
      window.localStorage.getItem(
        "nanobot.webui.composerQueuedGuidance.v1:temporary-private",
      ),
    ).toBeNull();
  });

});
