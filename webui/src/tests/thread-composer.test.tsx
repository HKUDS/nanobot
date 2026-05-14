import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ThreadComposer } from "@/components/thread/ThreadComposer";
import type { SlashCommand } from "@/lib/types";

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
const ORIGINAL_INNER_HEIGHT = window.innerHeight;

afterEach(() => {
  vi.restoreAllMocks();
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
    expect(input.parentElement?.className).toContain("max-w-[58rem]");
  });

  it("keeps the thread composer compact while matching the hero style", () => {
    render(
      <ThreadComposer
        onSend={vi.fn()}
        modelLabel="gpt-4o"
        placeholder="Type your message..."
      />,
    );

    expect(screen.getByText("gpt-4o")).toBeInTheDocument();
    const input = screen.getByPlaceholderText("Type your message...");
    expect(input.className).toContain("min-h-[50px]");
    expect(input.parentElement?.className).toContain("max-w-[49.5rem]");
    expect(input.parentElement?.className).toContain("rounded-[22px]");
    expect(input.parentElement?.className).toContain("shadow-[0_12px_30px_rgba(15,23,42,0.07)]");
    expect(screen.getByRole("button", { name: "Attach image" }).className).toContain("bg-card");
    expect(screen.getByRole("button", { name: "Send message" }).className).toContain("bg-foreground");
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
