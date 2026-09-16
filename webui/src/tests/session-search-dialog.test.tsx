import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SessionSearchDialog } from "@/components/SessionSearchDialog";
import type { ChatSummary } from "@/lib/types";

function session(index: number): ChatSummary {
  return {
    key: `websocket:chat-${index}`,
    channel: "websocket",
    chatId: `chat-${index}`,
    createdAt: null,
    updatedAt: null,
    title: `Chat ${index}`,
    preview: `Preview ${index}`,
  };
}

describe("SessionSearchDialog", () => {
  it("windows large result sets and selects an item reached beyond the first window", () => {
    const onSelect = vi.fn();
    render(<SessionSearchDialog open sessions={Array.from({ length: 1000 }, (_, i) => session(i))}
      activeKey={null} loading={false} onOpenChange={() => {}} onSelect={onSelect} />);
    expect(screen.getAllByRole("button").length).toBeLessThanOrEqual(24);
    const input = screen.getByRole("textbox", { name: "Search" });
    for (let i = 0; i < 40; i++) fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith("websocket:chat-40");
    expect(screen.getAllByRole("button").length).toBeLessThanOrEqual(24);
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("uses a solid compact command palette surface", () => {
    render(
      <SessionSearchDialog
        open
        sessions={[{ ...session(1), title: "Model chat", preview: "/model fast" }]}
        activeKey={null}
        loading={false}
        onOpenChange={() => {}}
        onSelect={() => {}}
      />,
    );

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveClass("bg-background");
    expect(dialog.className).not.toContain("bg-popover/");
    expect(dialog.className).not.toContain("backdrop-blur");
    expect(screen.getByTestId("session-search-scroll")).toHaveClass("overflow-y-auto");
    expect(screen.queryByText("/model fast")).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Search" }), {
      target: { value: "model fast" },
    });
    expect(screen.queryByText("Model chat")).not.toBeInTheDocument();
  });

  it("keeps keyboard navigation scrollable through long result lists", () => {
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });

    render(
      <SessionSearchDialog
        open
        sessions={Array.from({ length: 24 }, (_, index) => session(index + 1))}
        activeKey={null}
        loading={false}
        onOpenChange={() => {}}
        onSelect={() => {}}
      />,
    );

    const input = screen.getByRole("textbox", { name: "Search" });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowDown" });

    expect(scrollIntoView).toHaveBeenCalledWith({
      block: "nearest",
      inline: "nearest",
    });
  });
});
