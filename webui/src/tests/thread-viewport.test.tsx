import { act, render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ThreadViewport } from "@/components/thread/ThreadViewport";
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

describe("ThreadViewport", () => {
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
          behavior: "smooth",
        }),
      );
    } finally {
      HTMLElement.prototype.scrollIntoView = originalScrollIntoView;
    }
  });
});
