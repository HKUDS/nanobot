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
    expect(screen.getByText("No earlier messages")).toHaveClass("text-xs");
    expect(container.firstElementChild).toHaveAttribute("data-state", "exhausted");
  });

  it("hides completed feedback without offering another loading action", () => {
    const onRetry = vi.fn();
    const { container, rerender } = render(<ThreadHistoryStatus loading error={null} onRetry={onRetry} />);
    expect(container.firstElementChild).toHaveAttribute("data-state", "loading");
    rerender(<ThreadHistoryStatus loading={false} error={null} onRetry={onRetry} />);
    expect(container.firstElementChild).toHaveAttribute("data-state", "ready");
    expect(container.firstElementChild).toHaveAttribute("aria-hidden", "true");
    expect(container.firstElementChild).toHaveClass("invisible");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(onRetry).not.toHaveBeenCalled();
    rerender(<ThreadHistoryStatus loading error={null} onRetry={onRetry} />);
    expect(container.firstElementChild).not.toHaveClass("invisible");
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows decorative Blocks while previewing a pull without offering a loading action", () => {
    const onRetry = vi.fn();
    const { container } = render(<ThreadHistoryStatus loading={false} error={null} preview onRetry={onRetry} />);
    expect(container.firstElementChild).toHaveAttribute("data-state", "ready");
    expect(container.firstElementChild).not.toHaveClass("invisible");
    const blocks = screen.getByRole("status").querySelector(".thread-history-blocks")!;
    expect(blocks.children).toHaveLength(9);
    expect(blocks).toHaveAttribute("aria-hidden", "true");
    fireEvent.click(blocks);
    expect(onRetry).not.toHaveBeenCalled();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByRole("status").textContent).toBe("");
  });

  it("offers error Blocks with the actual failure on keyboard focus and resumes loading on retry", () => {
    const onRetry = vi.fn();
    const { container, rerender } = render(<ThreadHistoryStatus loading={false} error="offline" onRetry={onRetry} />);
    const retry = screen.getByRole("button", { name: "Loading failed. Retry" });
    expect(retry.querySelectorAll(".thread-history-blocks > span")).toHaveLength(9);
    expect(screen.getByText("Loading failed. Retry")).toHaveClass("sr-only");
    fireEvent.focus(retry);
    expect(screen.getByRole("tooltip")).toHaveTextContent("offline");
    fireEvent.click(retry);
    expect(onRetry).toHaveBeenCalledTimes(1);
    rerender(<ThreadHistoryStatus loading error={null} onRetry={onRetry} />);
    expect(container.firstElementChild).toHaveAttribute("data-state", "loading");
    expect(screen.getByRole("status").querySelectorAll(".thread-history-blocks > span")).toHaveLength(9);
  });
});
