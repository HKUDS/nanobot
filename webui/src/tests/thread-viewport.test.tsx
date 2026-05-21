import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  HISTORY_WINDOW_INCREMENT,
  INITIAL_HISTORY_WINDOW,
  ThreadViewport,
  windowMessages,
} from "@/components/thread/ThreadViewport";
import type { UIMessage } from "@/lib/types";

const messages: UIMessage[] = [
  {
    id: "u1",
    role: "user",
    content: "hello",
    createdAt: Date.now(),
  },
];

const emptyMessages: UIMessage[] = [];

interface ResizeObserverInstance {
  element?: Element;
  callback: ResizeObserverCallback;
  disconnect: ReturnType<typeof vi.fn>;
}

function makeLongMessages(count: number): UIMessage[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `m${index}`,
    role: "user" as const,
    content: `message ${index}`,
    createdAt: index,
  }));
}

describe("ThreadViewport", () => {
  it("keeps the scroll-to-bottom button above a growing composer", () => {
    const originalResizeObserver = globalThis.ResizeObserver;
    const resizeObservers: ResizeObserverInstance[] = [];
    class MockResizeObserver {
      element?: Element;
      callback: ResizeObserverCallback;
      disconnect = vi.fn();

      constructor(callback: ResizeObserverCallback) {
        this.callback = callback;
        resizeObservers.push(this);
      }

      observe(element: Element) {
        this.element = element;
      }
    }
    vi.stubGlobal("ResizeObserver", MockResizeObserver);

    try {
      const { container } = render(
        <ThreadViewport
          messages={messages}
          isStreaming={false}
          composer={<div>composer</div>}
        />,
      );
      const scroller = container.firstElementChild?.firstElementChild as HTMLElement;
      Object.defineProperties(scroller, {
        scrollHeight: { configurable: true, value: 2400 },
        clientHeight: { configurable: true, value: 600 },
        scrollTop: { configurable: true, value: 0 },
      });

      act(() => {
        scroller.dispatchEvent(new Event("scroll"));
      });

      const button = screen.getByRole("button", { name: "Scroll to bottom" });
      expect(button).toHaveStyle({ bottom: "192px" });

      const composerDock = screen.getByTestId("thread-composer-dock");
      composerDock.getBoundingClientRect = () =>
        ({
          height: 240,
          width: 800,
          top: 0,
          right: 800,
          bottom: 240,
          left: 0,
          x: 0,
          y: 0,
          toJSON: () => ({}),
        }) as DOMRect;

      const composerObserver = resizeObservers.find(
        (observer) => observer.element === composerDock,
      );
      expect(composerObserver).toBeDefined();

      act(() => {
        composerObserver!.callback([], composerObserver as unknown as ResizeObserver);
      });

      expect(button).toHaveStyle({ bottom: "256px" });
    } finally {
      vi.stubGlobal("ResizeObserver", originalResizeObserver);
    }
  });

  it("hides the scroll-to-bottom button when disabled for the welcome view", () => {
    const { container } = render(
      <ThreadViewport
        messages={emptyMessages}
        isStreaming={false}
        composer={<div>composer</div>}
        emptyState={<div>welcome</div>}
        showScrollToBottomButton={false}
      />,
    );
    const scroller = container.firstElementChild?.firstElementChild as HTMLElement;
    Object.defineProperties(scroller, {
      scrollHeight: { configurable: true, value: 2400 },
      clientHeight: { configurable: true, value: 600 },
      scrollTop: { configurable: true, value: 0 },
    });

    act(() => {
      scroller.dispatchEvent(new Event("scroll"));
    });

    expect(screen.queryByRole("button", { name: "Scroll to bottom" })).not.toBeInTheDocument();
  });

  it("renders only the tail window for long history by default", () => {
    const longMessages = makeLongMessages(300);

    render(
      <ThreadViewport
        messages={longMessages}
        isStreaming={false}
        composer={<div />}
      />,
    );

    expect(screen.queryByText("message 139")).not.toBeInTheDocument();
    expect(screen.getByText("message 140")).toBeInTheDocument();
    expect(screen.getByText("message 299")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Load earlier messages" })).toBeInTheDocument();
  });

  it("loads earlier history in fixed increments without rendering the whole transcript", () => {
    const longMessages = makeLongMessages(300);

    render(
      <ThreadViewport
        messages={longMessages}
        isStreaming={false}
        composer={<div />}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Load earlier messages" }));

    const firstVisible =
      300 - INITIAL_HISTORY_WINDOW - HISTORY_WINDOW_INCREMENT;

    expect(
      screen.queryByText(`message ${firstVisible - 1}`),
    ).not.toBeInTheDocument();
    expect(screen.getByText(`message ${firstVisible}`)).toBeInTheDocument();
    expect(screen.getByText("message 299")).toBeInTheDocument();
  });

  it("expands the window start to avoid cutting an agent activity cluster", () => {
    const clustered = makeLongMessages(200);
    clustered.splice(
      38,
      3,
      {
        id: "r0",
        role: "assistant",
        content: "",
        reasoning: "first reasoning",
        createdAt: 38,
      },
      {
        id: "t0",
        role: "tool",
        kind: "trace",
        content: "tool()",
        traces: ["tool()"],
        createdAt: 39,
      },
      {
        id: "r1",
        role: "assistant",
        content: "",
        reasoning: "second reasoning",
        createdAt: 40,
      },
    );

    const visible = windowMessages(clustered, INITIAL_HISTORY_WINDOW);

    expect(visible[0].id).toBe("r0");
    expect(visible).toHaveLength(INITIAL_HISTORY_WINDOW + 2);
  });

  it("resets to the bottom when opening a different conversation", async () => {
    const scrollIntoView = vi.fn();
    const originalScrollIntoView = HTMLElement.prototype.scrollIntoView;
    HTMLElement.prototype.scrollIntoView = scrollIntoView;

    try {
      const { container, rerender } = render(
        <ThreadViewport
          messages={messages}
          isStreaming={false}
          composer={<div />}
          conversationKey="chat-a"
        />,
      );
      const scroller = container.firstElementChild?.firstElementChild as HTMLElement;
      Object.defineProperties(scroller, {
        scrollHeight: { configurable: true, value: 2400 },
        clientHeight: { configurable: true, value: 600 },
        scrollTop: { configurable: true, value: 0 },
      });
      act(() => {
        scroller.dispatchEvent(new Event("scroll"));
      });
      scrollIntoView.mockClear();

      rerender(
        <ThreadViewport
          messages={messages}
          isStreaming={false}
          composer={<div />}
          conversationKey="chat-b"
        />,
      );

      await waitFor(() =>
        expect(scrollIntoView).toHaveBeenCalledWith({
          block: "end",
          behavior: "auto",
        }),
      );
    } finally {
      HTMLElement.prototype.scrollIntoView = originalScrollIntoView;
    }
  });

  it("waits for hydrated messages before fulfilling open-chat bottom scroll", async () => {
    const scrollIntoView = vi.fn();
    const originalScrollIntoView = HTMLElement.prototype.scrollIntoView;
    HTMLElement.prototype.scrollIntoView = scrollIntoView;

    try {
      const { container, rerender } = render(
        <ThreadViewport
          messages={emptyMessages}
          isStreaming={false}
          composer={<div />}
          conversationKey={null}
        />,
      );
      const scroller = container.firstElementChild?.firstElementChild as HTMLElement;
      Object.defineProperty(scroller, "scrollHeight", {
        configurable: true,
        value: 0,
      });
      scrollIntoView.mockClear();

      rerender(
        <ThreadViewport
          messages={emptyMessages}
          isStreaming={false}
          composer={<div />}
          conversationKey="chat-a"
        />,
      );
      expect(scrollIntoView).toHaveBeenCalledWith({
        block: "end",
        behavior: "auto",
      });

      Object.defineProperty(scroller, "scrollHeight", {
        configurable: true,
        value: 2400,
      });
      scrollIntoView.mockClear();

      rerender(
        <ThreadViewport
          messages={messages}
          isStreaming={false}
          composer={<div />}
          conversationKey="chat-a"
        />,
      );

      await waitFor(() =>
        expect(scrollIntoView).toHaveBeenCalledWith({
          block: "end",
          behavior: "auto",
        }),
      );
    } finally {
      HTMLElement.prototype.scrollIntoView = originalScrollIntoView;
    }
  });

  it("scrolls to the bottom when explicitly signalled after send", async () => {
    const scrollIntoView = vi.fn();
    const originalScrollIntoView = HTMLElement.prototype.scrollIntoView;
    HTMLElement.prototype.scrollIntoView = scrollIntoView;

    try {
      const { container, rerender } = render(
        <ThreadViewport
          messages={messages}
          isStreaming={false}
          composer={<div />}
          scrollToBottomSignal={0}
        />,
      );
      const scroller = container.firstElementChild?.firstElementChild as HTMLElement;
      Object.defineProperty(scroller, "scrollHeight", {
        configurable: true,
        value: 2400,
      });
      scrollIntoView.mockClear();

      rerender(
        <ThreadViewport
          messages={messages}
          isStreaming={false}
          composer={<div />}
          scrollToBottomSignal={1}
        />,
      );

      await waitFor(() =>
        expect(scrollIntoView).toHaveBeenCalledWith({
          block: "end",
          behavior: "auto",
        }),
      );
    } finally {
      HTMLElement.prototype.scrollIntoView = originalScrollIntoView;
    }
  });
});
