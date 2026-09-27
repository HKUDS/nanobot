import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ThreadHistoryStatus } from "@/components/thread/ThreadHistoryStatus";

afterEach(() => {
  vi.useRealTimers();
});

describe("ThreadHistoryStatus", () => {
  it("delays the loading indicator so fast history requests do not flash", () => {
    vi.useFakeTimers();
    render(<ThreadHistoryStatus loading error={null} onRetry={vi.fn()} />);

    expect(screen.queryByText("Loading earlier messages…")).not.toBeInTheDocument();
    act(() => vi.advanceTimersByTime(179));
    expect(screen.queryByText("Loading earlier messages…")).not.toBeInTheDocument();
    act(() => vi.advanceTimersByTime(1));
    expect(screen.getByText("Loading earlier messages…")).toBeVisible();
  });

  it("cancels the delay on completion and starts a fresh delay for the next request", () => {
    vi.useFakeTimers();
    const props = { error: null, onRetry: vi.fn() };
    const { rerender } = render(<ThreadHistoryStatus {...props} loading />);
    act(() => vi.advanceTimersByTime(100));
    rerender(<ThreadHistoryStatus {...props} loading={false} />);
    act(() => vi.advanceTimersByTime(500));
    expect(screen.getByRole("status")).toBeEmptyDOMElement();

    rerender(<ThreadHistoryStatus {...props} loading />);
    act(() => vi.advanceTimersByTime(180));
    expect(screen.getByText("Loading earlier messages…")).toBeVisible();
    rerender(<ThreadHistoryStatus {...props} loading={false} />);
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    rerender(<ThreadHistoryStatus {...props} loading />);
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("offers an explicit retry after loading earlier history fails", () => {
    const onRetry = vi.fn();
    render(<ThreadHistoryStatus loading={false} error="offline" onRetry={onRetry} />);

    expect(screen.getByText("Couldn’t load earlier messages.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
