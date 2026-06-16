import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ThreadComposer } from "@/components/thread/ThreadComposer";
import type { CliAppInfo, McpPresetInfo, SlashCommand } from "@/lib/types";

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

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  Reflect.deleteProperty(window, "blackcatHost");
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

function mockVoiceAudioInput(sample = 128, state: AudioContextState = "running") {
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
    resume = vi.fn(async () => undefined);
  }

  vi.stubGlobal("AudioContext", FakeAudioContext);
  vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) =>
    window.setTimeout(() => callback(performance.now()), 16) as unknown as number
  );
  vi.spyOn(window, "cancelAnimationFrame").mockImplementation((id) =>
    window.clearTimeout(id as unknown as number)
  );
}

async function waitForVoiceCapture(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 700));
  });
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
    expect(input.className).toContain("pt-[27px]");
    fireEvent.change(input, { target: { value: "1" } });
    expect(input.className).toContain("pt-[27px]");
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
    expect(input.parentElement?.parentElement?.className).toContain("shadow-[0_12px_30px_hsl(var(--brand)/0.03)]"); // HACK: specific to blackcat
    expect(screen.getByRole("button", { name: "Attach image" }).className).toContain("bg-card");
    expect(screen.getByRole("button", { name: "Send message" }).className).toContain("bg-foreground");
    expect(screen.queryByText(/Enter to send/)).not.toBeInTheDocument();
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

  it("warns during recording when microphone input is silent", async () => {
    mockVoiceRecorder();
    mockVoiceAudioInput();
    const onTranscribeAudio = vi.fn(async () => "should not appear");
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

    expect(screen.getByText("No microphone input detected.")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Stop recording" }));
    expect(onTranscribeAudio).not.toHaveBeenCalled();
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

    fireEvent.pointerDown(screen.getByRole("button", { name: "Workspace access mode" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: /Full Access/ }));

    expect(onWorkspaceScopeChange).toHaveBeenCalledWith(
      expect.objectContaining({
        project_path: "/tmp/project",
        access_mode: "full",
        restrict_to_workspace: false,
      }),
    );
  });

  it("keeps project selection as a compact composer dropdown", async () => {
    const onWorkspaceScopeChange = vi.fn();
    const defaultScope = {
      project_path: "/Users/test/.blackcat/workspace",
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

    fireEvent.pointerDown(screen.getByRole("button", { name: "Choose project" }));

    expect(await screen.findByRole("menuitem", { name: /Default workspace/ })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

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

    fireEvent.pointerDown(screen.getByRole("button", { name: "Choose project" }));
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

  it("uses the native folder picker for project selection on native host", async () => {
    const onWorkspaceScopeChange = vi.fn();
    const pickFolder = vi.fn().mockResolvedValue("/Users/test/native-project");
    const defaultScope = {
      project_path: "/Users/test/.blackcat/workspace",
      project_name: "workspace",
      access_mode: "full" as const,
      restrict_to_workspace: false,
    };
    Object.defineProperty(window, "blackcatHost", {
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
        workspaceControls={{ can_change_project: true, can_use_full_access: true }}
        onWorkspaceScopeChange={onWorkspaceScopeChange}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Choose project" }));

    await waitFor(() => expect(pickFolder).toHaveBeenCalled());
    expect(screen.queryByRole("menuitem", { name: /Default workspace/ })).not.toBeInTheDocument();
    expect(onWorkspaceScopeChange).toHaveBeenCalledWith(expect.objectContaining({
      project_path: "/Users/test/native-project",
      project_name: "native-project",
      access_mode: "full",
      restrict_to_workspace: false,
    }));
  });

  it("uses the web path menu when no native host picker is available", async () => {
    const defaultScope = {
      project_path: "/Users/test/.blackcat/workspace",
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

    fireEvent.pointerDown(screen.getByRole("button", { name: "Choose project" }));

    expect(await screen.findByRole("menuitem", { name: /Default workspace/ })).toBeInTheDocument();
    expect(screen.getByLabelText("Paste path")).toBeInTheDocument();
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
    expect(status.parentElement).toHaveClass("composer-status-strip");
    expect(status.parentElement).toHaveAttribute("data-state", "enter");
    expect(status.querySelector(".run-pulse-icon")).not.toBeNull();

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
    expect(window.localStorage.getItem("blackcat.webui.slashCommandRecents")).toBeNull();
  });

  it("orders recent slash commands first for the blank slash menu", () => {
    window.localStorage.setItem("blackcat.webui.slashCommandRecents", JSON.stringify(["/history"]));
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

    const palette = screen.getByRole("listbox", { name: "Apps" });
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
    expect(screen.queryByRole("listbox", { name: "Apps" })).not.toBeInTheDocument();

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

    expect(onSend).toHaveBeenCalledWith("keep the UI minimal");
    expect(screen.queryByText("keep the UI minimal")).not.toBeInTheDocument();
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
    fireEvent.click(screen.getByRole("button", { name: "Guide" }));
    expect(onSend).toHaveBeenCalledWith("remember this edited follow-up");

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

});
