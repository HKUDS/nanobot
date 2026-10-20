import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ThreadHistoryStatus } from "@/components/thread/ThreadHistoryStatus";

describe("ThreadHistoryStatus", () => {
  it("exposes real loading immediately and switches to a distinct exhausted state on completion", () => {
    const props = { error: null, onRetry: vi.fn() };
    const { container, rerender } = render(<ThreadHistoryStatus {...props} loading />);
    expect(screen.getByText("Loading earlier messages…")).toHaveClass("sr-only");
    expect(container.firstElementChild).toHaveAttribute("data-state", "loading");
    expect(screen.getByRole("status").querySelectorAll(".thread-history-blocks > span")).toHaveLength(9);

    rerender(<ThreadHistoryStatus {...props} loading={false} exhausted />);
    expect(screen.getByText("Start of conversation")).toHaveClass("sr-only");
    expect(container.firstElementChild).toHaveAttribute("data-state", "exhausted");
    expect(screen.getByRole("status").querySelectorAll("path")).toHaveLength(1);
  });

  it("offers keyboard-accessible loading and explains an armed touch pull", () => {
    const onRetry = vi.fn();
    const { rerender } = render(<ThreadHistoryStatus loading={false} error={null} onRetry={onRetry} />);
    fireEvent.click(screen.getByRole("button", { name: "Load earlier messages" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
    rerender(<ThreadHistoryStatus loading={false} error={null} armed onRetry={onRetry} />);
    expect(screen.getByText("Release to load earlier messages")).toHaveClass("sr-only");
  });

  it("offers an explicit retry after loading earlier history fails", () => {
    const onRetry = vi.fn();
    render(<ThreadHistoryStatus loading={false} error="offline" onRetry={onRetry} />);
    expect(screen.getByText("Loading failed.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
