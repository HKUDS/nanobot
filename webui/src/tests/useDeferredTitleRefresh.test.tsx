import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useDeferredTitleRefresh } from "@/hooks/useDeferredTitleRefresh";
import type { ChatSummary } from "@/lib/types";

function session(overrides: Partial<ChatSummary> = {}): ChatSummary {
  return {
    key: "websocket:chat-a",
    channel: "websocket",
    chatId: "chat-a",
    createdAt: null,
    updatedAt: null,
    title: "",
    preview: "First user message",
    ...overrides,
  };
}

describe("useDeferredTitleRefresh", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("retries refreshing untitled sessions after turn_end", () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() =>
      useDeferredTitleRefresh(session(), refresh, [100, 300]),
    );

    act(() => {
      result.current();
    });

    expect(refresh).toHaveBeenCalledTimes(1);

    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(refresh).toHaveBeenCalledTimes(2);

    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(refresh).toHaveBeenCalledTimes(3);
  });

  it("stops pending retries once a generated title arrives", () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    const { result, rerender } = renderHook(
      ({ activeSession }) =>
        useDeferredTitleRefresh(activeSession, refresh, [100, 300]),
      { initialProps: { activeSession: session() } },
    );

    act(() => {
      result.current();
    });
    rerender({ activeSession: session({ title: "Generated title" }) });

    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("does not retry when the active session already has a title", () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() =>
      useDeferredTitleRefresh(session({ title: "Existing title" }), refresh, [100]),
    );

    act(() => {
      result.current();
      vi.advanceTimersByTime(100);
    });

    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("clears pending retries when the active chat changes", () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    const { result, rerender } = renderHook(
      ({ activeSession }) =>
        useDeferredTitleRefresh(activeSession, refresh, [100]),
      { initialProps: { activeSession: session() } },
    );

    act(() => {
      result.current();
    });
    rerender({
      activeSession: session({
        key: "websocket:chat-b",
        chatId: "chat-b",
      }),
    });

    act(() => {
      vi.advanceTimersByTime(100);
    });

    expect(refresh).toHaveBeenCalledTimes(1);
  });
});
