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
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("uses a solid compact command palette surface", () => {
    render(
      <SessionSearchDialog
        open
        sessions={[session(1)]}
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
