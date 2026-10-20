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

  it("keeps the ready control distinct from real loading and preserves keyboard activation", () => {
    const onRetry = vi.fn();
    const { container, rerender } = render(<ThreadHistoryStatus loading={false} error={null} onRetry={onRetry} />);
    expect(container.firstElementChild).toHaveAttribute("data-state", "ready");
    expect(screen.queryByText("Loading earlier messages…")).not.toBeInTheDocument();
    const load = screen.getByRole("button", { name: "Load earlier messages" });
    expect(load.querySelectorAll(".thread-history-blocks > span")).toHaveLength(9);
    fireEvent.click(load);
    expect(onRetry).toHaveBeenCalledTimes(1);
    rerender(<ThreadHistoryStatus loading={false} error={null} requiresBoundary onRetry={onRetry} />);
    const instruction = screen.getByText("Scroll up to continue loading earlier messages");
    expect(instruction).toHaveClass("text-xs");
    expect(instruction).toBeVisible();
    fireEvent.click(instruction);
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    rerender(<ThreadHistoryStatus loading error={null} requiresBoundary onRetry={onRetry} />);
    expect(container.firstElementChild).toHaveAttribute("data-state", "loading");
    expect(screen.getByRole("status").querySelectorAll(".thread-history-blocks > span")).toHaveLength(9);
  });

  it("offers error Blocks with the actual failure on keyboard focus and resumes loading on retry", () => {
    const onRetry = vi.fn();
    const { container, rerender } = render(<ThreadHistoryStatus loading={false} error="offline" requiresBoundary onRetry={onRetry} />);
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
