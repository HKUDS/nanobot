import { useRef } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PromptNavigator } from "@/components/thread/PromptNavigator";
import {
  HISTORY_WINDOW_INCREMENT,
  INITIAL_HISTORY_WINDOW,
  ThreadViewport,
  type ThreadViewportHandle,
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

function ViewportWithPromptNavigator({ messages }: { messages: UIMessage[] }) {
  const viewportRef = useRef<ThreadViewportHandle | null>(null);
  return (
    <div>
      <PromptNavigator
        messages={messages}
        onJumpToPrompt={(promptId) => viewportRef.current?.jumpToUserPrompt(promptId)}
      />
      <ThreadViewport
        ref={viewportRef}
        messages={messages}
        isStreaming={false}
        composer={<div />}
      />
    </div>
  );
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
      const buttonPositioner = button.parentElement as HTMLElement;
      expect(button).not.toHaveClass("-translate-x-1/2");
      expect(buttonPositioner).toHaveStyle({ bottom: "192px" });

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

      expect(buttonPositioner).toHaveStyle({ bottom: "256px" });
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
      scrollTop: { configurable: true, writable: true, value: 0 },
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
    expect(screen.queryByRole("button", { name: "Load earlier messages" })).not.toBeInTheDocument();
  });

  it("automatically expands earlier local history near the top", () => {
    const longMessages = makeLongMessages(300);

    const { container } = render(
      <ThreadViewport
        messages={longMessages}
        isStreaming={false}
        composer={<div />}
      />,
    );

    const scroller = container.firstElementChild?.firstElementChild as HTMLElement;
    Object.defineProperties(scroller, {
      scrollHeight: { configurable: true, value: 2400 },
      clientHeight: { configurable: true, value: 600 },
      scrollTop: { configurable: true, writable: true, value: 0 },
    });

    act(() => {
      scroller.dispatchEvent(new Event("scroll"));
    });

    const firstVisible =
      300 - INITIAL_HISTORY_WINDOW - HISTORY_WINDOW_INCREMENT;

    expect(
      screen.queryByText(`message ${firstVisible - 1}`),
    ).not.toBeInTheDocument();
    expect(screen.getByText(`message ${firstVisible}`)).toBeInTheDocument();
    expect(screen.getByText("message 299")).toBeInTheDocument();
  });

  it("automatically requests older transcript pages near the top", () => {
    const onLoadOlder = vi.fn();

    const { container } = render(
      <ThreadViewport
        messages={makeLongMessages(20)}
        isStreaming={false}
        composer={<div />}
        hasMoreBefore
        onLoadOlder={onLoadOlder}
      />,
    );

    const scroller = container.firstElementChild?.firstElementChild as HTMLElement;
    Object.defineProperties(scroller, {
      scrollHeight: { configurable: true, value: 1800 },
      clientHeight: { configurable: true, value: 600 },
      scrollTop: { configurable: true, writable: true, value: 0 },
    });

    act(() => {
      scroller.dispatchEvent(new Event("scroll"));
    });

    expect(onLoadOlder).toHaveBeenCalledTimes(1);
  });

  it("renders a prompt rail that jumps to user messages", async () => {
    const promptMessages = makeLongMessages(5);
    const { container } = render(
      <ThreadViewport
        messages={promptMessages}
        isStreaming={false}
        composer={<div />}
      />,
    );

    const scroller = container.firstElementChild?.firstElementChild as HTMLElement;
    const scrollTo = vi.fn();
    Object.defineProperties(scroller, {
      scrollHeight: { configurable: true, value: 1800 },
      clientHeight: { configurable: true, value: 600 },
      scrollTop: { configurable: true, value: 0 },
      scrollTo: { configurable: true, value: scrollTo },
    });

    const promptEls = Array.from(
      container.querySelectorAll<HTMLElement>("[data-user-prompt-id]"),
    );
    expect(promptEls).toHaveLength(5);
    promptEls.forEach((el, index) => {
      Object.defineProperty(el, "offsetTop", {
        configurable: true,
        value: index * 360,
      });
    });

    await act(async () => {
      window.dispatchEvent(new Event("resize"));
      await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
    });

    expect(screen.getByLabelText("User prompt navigation")).toBeInTheDocument();

    const targetPrompt = screen.getByRole("button", { name: "Jump to prompt: message 3" });
    expect(within(targetPrompt).getByText("message 3")).toBeInTheDocument();

    fireEvent.click(targetPrompt);

    expect(scrollTo).toHaveBeenCalledWith({
      top: 1064,
      behavior: "smooth",
    });
  });

  it("opens a prompt navigator list and jumps to a selected prompt", async () => {
    const promptMessages = makeLongMessages(5);
    const { container } = render(<ViewportWithPromptNavigator messages={promptMessages} />);

    const scroller = container.querySelector(".thread-viewport-scrollbar") as HTMLElement;
    const scrollTo = vi.fn();
    Object.defineProperties(scroller, {
      scrollHeight: { configurable: true, value: 1800 },
      clientHeight: { configurable: true, value: 600 },
      scrollTop: { configurable: true, value: 0 },
      scrollTo: { configurable: true, value: scrollTo },
    });

    const promptEls = Array.from(
      container.querySelectorAll<HTMLElement>("[data-user-prompt-id]"),
    );
    promptEls.forEach((el, index) => {
      Object.defineProperty(el, "offsetTop", {
        configurable: true,
        value: index * 360,
      });
    });

    fireEvent.click(screen.getByRole("button", { name: "Open prompt navigator" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("Prompts")).toBeInTheDocument();
    expect(within(dialog).getByText("message 4")).toBeInTheDocument();

    fireEvent.change(within(dialog).getByRole("textbox", { name: "Search prompts" }), {
      target: { value: "message 4" },
    });
    expect(within(dialog).queryByText("message 1")).not.toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Jump to prompt: message 4" }));

    expect(scrollTo).toHaveBeenCalledWith({
      top: 1424,
      behavior: "smooth",
    });
  });

  it("expands the history window before jumping to an older prompt from the navigator", async () => {
    const longMessages = makeLongMessages(300);
    render(<ViewportWithPromptNavigator messages={longMessages} />);

    expect(screen.queryByText("message 20")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open prompt navigator" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Jump to prompt: message 20" }));

    await waitFor(() => expect(screen.getByText("message 20")).toBeInTheDocument());
  });

  it("renders the prompt rail for compact scroll ranges", async () => {
    const promptMessages = makeLongMessages(3);
    const { container } = render(
      <ThreadViewport
        messages={promptMessages}
        isStreaming={false}
        composer={<div />}
      />,
    );

    const scroller = container.firstElementChild?.firstElementChild as HTMLElement;
    Object.defineProperties(scroller, {
      scrollHeight: { configurable: true, value: 700 },
      clientHeight: { configurable: true, value: 600 },
      scrollTop: { configurable: true, value: 0 },
    });

    const promptEls = Array.from(
      container.querySelectorAll<HTMLElement>("[data-user-prompt-id]"),
    );
    expect(promptEls).toHaveLength(3);
    promptEls.forEach((el, index) => {
      Object.defineProperty(el, "offsetTop", {
        configurable: true,
        value: index * 50,
      });
    });

    await act(async () => {
      window.dispatchEvent(new Event("resize"));
      await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
    });

    expect(screen.getByLabelText("User prompt navigation")).toBeInTheDocument();
  });

  it("buckets dense prompt rails without rendering every prompt as a marker", async () => {
    const promptMessages = makeLongMessages(100);
    const { container } = render(
      <ThreadViewport
        messages={promptMessages}
        isStreaming={false}
        composer={<div />}
      />,
    );

    const scroller = container.firstElementChild?.firstElementChild as HTMLElement;
    const scrollTo = vi.fn();
    Object.defineProperties(scroller, {
      scrollHeight: { configurable: true, value: 10000 },
      clientHeight: { configurable: true, value: 600 },
      scrollTop: { configurable: true, value: 0 },
      scrollTo: { configurable: true, value: scrollTo },
    });

    const promptEls = Array.from(
      container.querySelectorAll<HTMLElement>("[data-user-prompt-id]"),
    );
    expect(promptEls).toHaveLength(100);
    promptEls.forEach((el, index) => {
      Object.defineProperty(el, "offsetTop", {
        configurable: true,
        value: index * 90,
      });
    });

    await act(async () => {
      window.dispatchEvent(new Event("resize"));
      await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
    });

    const promptMarkers = screen.getAllByRole("button", { name: /Jump to prompt:/ });
    expect(promptMarkers.length).toBeGreaterThan(3);
    expect(promptMarkers.length).toBeLessThan(100);
    expect(
      promptMarkers.some((marker) =>
        marker.getAttribute("aria-label")?.includes("prompts, latest"),
      ),
    ).toBe(true);

    fireEvent.click(promptMarkers[promptMarkers.length - 1]);

    expect(scrollTo).toHaveBeenCalledWith({
      top: 8894,
      behavior: "smooth",
    });
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