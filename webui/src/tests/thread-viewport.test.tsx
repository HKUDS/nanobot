import { createRef, Profiler, useRef } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PromptNavigator } from "@/components/thread/PromptNavigator";
import {
  HISTORY_WINDOW_INCREMENT,
  INITIAL_HISTORY_WINDOW,
  ThreadViewport,
  type ThreadViewportHandle,
  windowMessages,
} from "@/components/thread/ThreadViewport";
import { ThreadCameraController } from "@/components/thread/thread-camera";
import { ThreadMotionCoordinator } from "@/components/thread/thread-motion";
import type { PromptHistoryNavigation } from "@/hooks/usePromptHistory";
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

const submittedMessages: UIMessage[] = [
  { id: "u1", role: "user", content: "old question", turnId: "turn-1", createdAt: 1 },
  { id: "a1", role: "assistant", content: "old answer", turnId: "turn-1", createdAt: 2 },
  { id: "u2", role: "user", content: "new question", turnId: "turn-2", createdAt: 3 },
];
const submittedAnswer: UIMessage = {
  id: "a2", role: "assistant", content: "new answer", turnId: "turn-2", createdAt: 4,
};

afterEach(() => {
  vi.restoreAllMocks();
});

async function flushAnimationFrame(): Promise<void> {
  await act(async () => {
    await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
  });
}

function controlAnimationFrames() {
  let now = 0;
  let nextId = 1;
  const frames = new Map<number, FrameRequestCallback>();
  vi.spyOn(performance, "now").mockImplementation(() => now);
  vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
    const id = nextId++;
    frames.set(id, callback);
    return id;
  });
  vi.spyOn(window, "cancelAnimationFrame").mockImplementation((id) => {
    frames.delete(id);
  });
  return {
    frame: (elapsedMs: number) => {
      now += elapsedMs;
      act(() => {
        for (const id of [...frames.keys()]) {
          const callback = frames.get(id);
          if (!callback) continue;
          frames.delete(id);
          callback(now);
        }
      });
    },
  };
}

function mockPromptPosition(scroller: HTMLElement, prompt: HTMLElement, top: number, gap = 48) {
  scroller.getBoundingClientRect = () => DOMRect.fromRect({ width: 800, height: scroller.clientHeight });
  const content = scroller.firstElementChild as HTMLElement;
  content.getBoundingClientRect = () => DOMRect.fromRect({
    y: -scroller.scrollTop, width: 800, height: scroller.scrollHeight,
  });
  Object.defineProperty(prompt, "offsetTop", { configurable: true, value: top });
  prompt.getBoundingClientRect = () => DOMRect.fromRect({
    y: top - scroller.scrollTop, width: 800, height: 80,
  });
  const previous = prompt.previousElementSibling as HTMLElement | null;
  if (previous) {
    previous.getBoundingClientRect = () => DOMRect.fromRect({
      y: top - gap - 40 - scroller.scrollTop, width: 800, height: 40,
    });
  }
}

function dispatchUserScroll(scroller: HTMLElement): void {
  fireEvent.pointerDown(scroller, { button: 0 });
  scroller.dispatchEvent(new Event("scroll"));
}

function historyPull(scroller: HTMLElement): number {
  return Number.parseFloat(/translateY\(([-.\d]+)px\)/.exec(scroller.style.transform)?.[1] ?? "0");
}

function dispatchHistoryInput(scroller: HTMLElement, input: "wheel" | "touch" | "keyboard") {
  if (input === "wheel") fireEvent.wheel(scroller, { deltaY: -100 });
  if (input === "keyboard") fireEvent.keyDown(scroller, { key: "PageUp" });
  if (input === "touch") {
    fireEvent.touchStart(scroller, { touches: [{ clientX: 100, clientY: 200 }] });
    fireEvent.touchMove(scroller, { touches: [{ clientX: 100, clientY: 380 }] });
    fireEvent.touchEnd(scroller);
  }
}

function mockScrollGeometry(scroller: HTMLElement, height: number, viewport: number, top = 0) {
  Object.defineProperties(scroller, {
    scrollHeight: { configurable: true, value: height },
    clientHeight: { configurable: true, value: viewport },
    scrollTop: { configurable: true, writable: true, value: top },
  });
}

interface ResizeObserverInstance extends ResizeObserver {
  elements: Element[];
  callback: ResizeObserverCallback;
  disconnect: ReturnType<typeof vi.fn>;
}

function stubVisualViewport({
  height,
  innerHeight,
  offsetTop = 0,
}: {
  height: number;
  innerHeight: number;
  offsetTop?: number;
}) {
  const originalInnerHeight = window.innerHeight;
  const originalVisualViewport = window.visualViewport;
  const target = new EventTarget();
  const viewport = {
    width: 390,
    height,
    offsetTop,
    offsetLeft: 0,
    pageTop: offsetTop,
    pageLeft: 0,
    scale: 1,
    addEventListener: target.addEventListener.bind(target),
    removeEventListener: target.removeEventListener.bind(target),
    dispatchEvent: target.dispatchEvent.bind(target),
  } as unknown as VisualViewport;

  Object.defineProperty(window, "innerHeight", {
    configurable: true,
    value: innerHeight,
  });
  Object.defineProperty(window, "visualViewport", {
    configurable: true,
    value: viewport,
  });

  return {
    viewport,
    restore: () => {
      Object.defineProperty(window, "innerHeight", {
        configurable: true,
        value: originalInnerHeight,
      });
      if (originalVisualViewport) {
        Object.defineProperty(window, "visualViewport", {
          configurable: true,
          value: originalVisualViewport,
        });
      } else {
        Reflect.deleteProperty(window, "visualViewport");
      }
    },
  };
}

function stubResizeObserver() {
  const original = globalThis.ResizeObserver;
  const observers: ResizeObserverInstance[] = [];
  class MockResizeObserver implements ResizeObserverInstance {
    elements: Element[] = [];
    callback: ResizeObserverCallback;
    disconnect = vi.fn(() => { this.elements = []; });

    constructor(callback: ResizeObserverCallback) {
      this.callback = callback;
      observers.push(this);
    }

    observe(element: Element) {
      this.elements.push(element);
    }

    unobserve(element: Element) {
      this.elements = this.elements.filter((candidate) => candidate !== element);
    }
  }
  vi.stubGlobal("ResizeObserver", MockResizeObserver);
  return {
    observers,
    notify: (element: Element) => act(() => {
      for (const observer of observers) {
        if (observer.elements.includes(element)) observer.callback([], observer);
      }
    }),
    restore: () => vi.stubGlobal("ResizeObserver", original),
  };
}

function stubElementsFromPoint(resolve: () => Element[]) {
  const descriptor = Object.getOwnPropertyDescriptor(document, "elementsFromPoint");
  const mock = vi.fn(resolve);
  Object.defineProperty(document, "elementsFromPoint", {
    configurable: true,
    value: mock,
  });
  return {
    mock,
    restore: () => {
      if (descriptor) {
        Object.defineProperty(document, "elementsFromPoint", descriptor);
      } else {
        Reflect.deleteProperty(document, "elementsFromPoint");
      }
    },
  };
}

function makeLongMessages(count: number): UIMessage[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `m${index}`,
    role: "user" as const,
    content: `message ${index}`,
    createdAt: index,
  }));
}

function makePromptExchangeMessages(count: number): UIMessage[] {
  return Array.from({ length: count }, (_, index) => ([
    {
      id: `m${index}`,
      role: "user" as const,
      content: `message ${index}`,
      createdAt: index * 2,
    },
    {
      id: `a${index}`,
      role: "assistant" as const,
      content: `answer ${index}`,
      createdAt: index * 2 + 1,
    },
  ])).flat();
}

function getScroller(container: HTMLElement): HTMLElement {
  const scroller = container.querySelector<HTMLElement>(".thread-viewport-scrollbar");
  if (!scroller) throw new Error("thread scrollport not found");
  return scroller;
}

function mockMessageEnd(scroller: HTMLElement) {
  const rows = scroller.querySelectorAll<HTMLElement>(".thread-message-row");
  const row = rows[rows.length - 1];
  scroller.getBoundingClientRect = () => ({ bottom: scroller.clientHeight } as DOMRect);
  row.getBoundingClientRect = () => ({ height: 100, bottom: scroller.scrollHeight - scroller.scrollTop } as DOMRect);
  act(() => window.dispatchEvent(new Event("resize")));
}

async function renderPromptRailViewport({
  scrollTo,
  messages: promptMessages = makePromptExchangeMessages(5),
}: {
  scrollTo?: (options?: ScrollToOptions) => void;
  messages?: UIMessage[];
} = {}) {
  const { container } = render(
    <ThreadViewport
      messages={promptMessages}
      isStreaming={false}
      composer={<div />}
    />,
  );

  const scroller = getScroller(container);
  Object.defineProperties(scroller, {
    scrollHeight: { configurable: true, value: 1800 },
    clientHeight: { configurable: true, value: 600 },
    scrollTop: { configurable: true, writable: true, value: 0 },
    ...(scrollTo ? { scrollTo: { configurable: true, value: scrollTo } } : {}),
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

  await act(async () => {
    window.dispatchEvent(new Event("resize"));
    await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
  });

  return { promptEls, scroller };
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
  it("keeps reasoning disclosure anchored for pointer and keyboard toggles", () => {
    const takeUserControl = vi.spyOn(
      ThreadMotionCoordinator.prototype,
      "takeUserControl",
    );
    render(
      <ThreadViewport
        messages={[{
          id: "reasoning-1",
          role: "assistant",
          content: "",
          reasoning: "A completed thought",
          createdAt: 1,
        }]}
        isStreaming={false}
        composer={<div>composer</div>}
      />,
    );

    const disclosure = screen.getByRole("button", { name: "Worked" });
    fireEvent.pointerDown(disclosure, { button: 0 });
    expect(takeUserControl).toHaveBeenCalledTimes(1);

    takeUserControl.mockClear();
    fireEvent.keyDown(disclosure, { key: "Enter" });
    expect(takeUserControl).toHaveBeenCalledTimes(1);

    takeUserControl.mockClear();
    fireEvent.keyDown(disclosure, { key: " " });
    expect(takeUserControl).toHaveBeenCalledTimes(1);
  });

  it("yields scroll control before expanding activity from a portaled message menu", () => {
    const takeUserControl = vi.spyOn(ThreadMotionCoordinator.prototype, "takeUserControl");
    render(
      <ThreadViewport
        messages={[
          { id: "reasoning", role: "assistant", content: "", reasoning: "A completed thought", createdAt: 1 },
          { id: "answer", role: "assistant", content: "Finished answer", createdAt: 2 },
        ]}
        isStreaming={false}
        composer={<div>composer</div>}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Message actions" }));
    const disclosure = screen.getByRole("button", { name: "Worked" });
    expect(screen.getByTestId("thread-message-region")).not.toContainElement(disclosure);
    takeUserControl.mockClear();
    fireEvent.click(disclosure);
    expect(takeUserControl).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: /Collapse activity details/ })).toBeInTheDocument();
  });

  it("top-aligns short threads in the message rendering area", () => {
    render(
      <ThreadViewport
        messages={messages}
        isStreaming={false}
        composer={<div>composer</div>}
      />,
    );

    const messageRegion = screen.getByTestId("thread-message-region");
    expect(messageRegion).toHaveClass("justify-start");
    expect(messageRegion).not.toHaveClass("justify-end");
    expect(messageRegion).toHaveClass("thread-message-viewport");
    expect(messageRegion).toHaveClass("pb-0");
    expect(messageRegion.className).not.toContain("5rem");
  });

  it("allows long messages to shrink within the shared mobile grid column", () => {
    render(
      <ThreadViewport
        messages={[
          ...messages,
          {
            id: "a-long-link",
            role: "assistant",
            content:
              "https://github.com/HKUDS/nanobot/discussions/17788077"
              + "/a-very-long-unbroken-segment-that-must-not-widen-the-thread",
            createdAt: Date.now(),
          },
        ]}
        isStreaming={false}
        composer={<div>composer</div>}
      />,
    );

    expect(screen.getByTestId("thread-message-region")).toHaveClass("min-w-0");
  });

  it("keeps message hit rows full width and constrains content inside each row", () => {
    render(<ThreadViewport messages={messages} isStreaming={false} composer={<div>composer</div>} />);

    const region = screen.getByTestId("thread-message-region");
    expect(region.firstElementChild).toHaveClass("w-full");
    expect(region.firstElementChild).not.toHaveClass("max-w-[var(--content-column-width)]");
    expect(region.parentElement).not.toHaveClass("max-w-[64rem]");
    const rows = region.querySelectorAll("[data-thread-display-unit]");
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) expect(row).toHaveClass("thread-message-row");
  });

  it("top-aligns a short active turn while the agent is responding", () => {
    render(
      <ThreadViewport
        messages={messages}
        isStreaming
        composer={<div>composer</div>}
      />,
    );

    const messageRegion = screen.getByTestId("thread-message-region");
    expect(messageRegion).toHaveClass("justify-start");
    expect(messageRegion).not.toHaveClass("justify-end");
    expect(screen.getByTestId("thread-composer-dock")).not.toHaveClass("mt-auto");
  });

  it("keeps the docked composer outside the message scrollport", () => {
    const { container } = render(
      <ThreadViewport
        messages={messages}
        isStreaming={false}
        composer={<div>composer</div>}
      />,
    );

    const scroller = getScroller(container);
    const messageRegion = screen.getByTestId("thread-message-region");
    const composerDock = screen.getByTestId("thread-composer-dock");
    expect(scroller).toBe(messageRegion);
    expect(scroller).not.toContainElement(composerDock);
    expect(scroller.parentElement).toContainElement(composerDock);
    expect(composerDock).toHaveClass("relative");
    expect(composerDock).toHaveClass("thread-composer-dock");
    expect(composerDock).not.toHaveClass("sticky");
    expect(scroller.querySelector(".thread-message-end-gap")).toBeInTheDocument();
    expect(scroller.lastElementChild).toHaveClass("h-px", "shrink-0");
  });

  it.each([48, 12])("anchors within a %i px preceding gap despite an early layout scroll event", (gap) => {
    const clock = controlAnimationFrames();
    const { container, rerender } = render(<ThreadViewport messages={submittedMessages} isStreaming />);
    const scroller = getScroller(container);
    mockScrollGeometry(scroller, 1_200, 500, 700);
    const prompt = container.querySelector<HTMLElement>('[data-user-prompt-id="u2"]')!;
    mockPromptPosition(scroller, prompt, 420, gap);

    rerender(
      <ThreadViewport messages={submittedMessages} isStreaming
        activeTurnId="turn-2" submittedPromptTurnId="turn-2" />,
    );
    mockScrollGeometry(scroller, 1_280, 500, scroller.scrollTop);
    fireEvent.scroll(scroller);
    expect(screen.queryByRole("button", { name: "Scroll to bottom" })).not.toBeInTheDocument();
    clock.frame(0);
    clock.frame(300);
    expect(scroller.scrollTop).toBe(420 - gap);
    expect(prompt.getBoundingClientRect().top).toBe(gap);
  });

  it("lets the first prompt supersede a pending empty-conversation camera command", () => {
    const clock = controlAnimationFrames();
    const firstPrompt = { ...submittedMessages[2], content: "first question\n".repeat(60) };
    const viewport = (ready: boolean) => (
      <ThreadViewport messages={[firstPrompt]} isStreaming conversationKey="chat-a"
        conversationReady={ready} activeTurnId="turn-2" submittedPromptTurnId="turn-2" />
    );
    const { container, rerender } = render(
      <ThreadViewport messages={emptyMessages} isStreaming={false} conversationKey={null} />,
    );
    mockScrollGeometry(getScroller(container), 1_200, 500, 700);
    rerender(viewport(false));
    const scroller = getScroller(container);
    mockScrollGeometry(scroller, 1_200, 500);
    const prompt = container.querySelector<HTMLElement>('[data-user-prompt-id="u2"]')!;
    mockPromptPosition(scroller, prompt, 0);
    prompt.getBoundingClientRect = () => DOMRect.fromRect({ y: -scroller.scrollTop, width: 800, height: 1_200 });

    rerender(viewport(true));
    clock.frame(0);
    expect(scroller.scrollTop).toBe(0);
    clock.frame(300);
    expect(scroller.scrollTop).toBe(0);
  });

  it.each(["before measurement", "during animation"])("finishes anchoring when a quick turn completes %s", (timing) => {
    const clock = controlAnimationFrames();
    const complete = [...submittedMessages, submittedAnswer];
    const { container, rerender } = render(<ThreadViewport messages={submittedMessages} isStreaming={false} />);
    const scroller = getScroller(container);
    mockScrollGeometry(scroller, 1_200, 500, 700);
    const positionPrompt = () => mockPromptPosition(
      scroller, container.querySelector<HTMLElement>('[data-user-prompt-id="u2"]')!, 420,
    );
    rerender(
      <ThreadViewport messages={timing === "before measurement" ? complete : submittedMessages}
        isStreaming activeTurnId="turn-2" submittedPromptTurnId="turn-2" />,
    );
    positionPrompt();
    if (timing === "during animation") {
      clock.frame(0);
      clock.frame(80);
    }
    rerender(<ThreadViewport messages={complete} isStreaming={false} />);
    positionPrompt();
    clock.frame(0);
    clock.frame(300);
    expect(scroller.scrollTop).toBe(372);
  });

  it.each(["before measurement", "during animation", "after settlement"])(
    "anchors the canonical prompt when replay replaces its DOM id %s",
    (timing) => {
      const clock = controlAnimationFrames();
      const { container, rerender } = render(<ThreadViewport messages={submittedMessages} isStreaming />);
      const scroller = getScroller(container);
      mockScrollGeometry(scroller, 1_200, 500, 700);
      mockPromptPosition(scroller, container.querySelector<HTMLElement>('[data-user-prompt-id="u2"]')!, 420);
      const viewport = (prompt: UIMessage) => (
        <ThreadViewport messages={[...submittedMessages.slice(0, -1), prompt]} isStreaming
          activeTurnId="turn-2" submittedPromptTurnId="turn-2" />
      );
      rerender(viewport(submittedMessages[2]));
      if (timing !== "before measurement") {
        clock.frame(0);
        clock.frame(timing === "during animation" ? 80 : 300);
      }

      rerender(viewport({ ...submittedMessages[2], id: "canonical-user" }));
      const canonical = container.querySelector<HTMLElement>('[data-user-prompt-id="canonical-user"]')!;
      mockScrollGeometry(scroller, 1_300, 500, scroller.scrollTop);
      mockPromptPosition(scroller, canonical, 520);
      clock.frame(0);
      clock.frame(300);
      expect(scroller.scrollTop).toBe(472);
      expect(canonical.getBoundingClientRect().top).toBe(48);
    },
  );

  it("preserves the prompt through output, composer growth and reflow until the reader takes control", () => {
    const clock = controlAnimationFrames();
    const resizeObserver = stubResizeObserver();
    try {
      const composer = <textarea aria-label="Message input" />;
      const viewport = (threadMessages = submittedMessages, isStreaming = true) => (
        <ThreadViewport messages={threadMessages} isStreaming={isStreaming} composer={composer}
          activeTurnId={isStreaming ? "turn-2" : null} submittedPromptTurnId="turn-2" />
      );
      const { container, rerender } = render(
        <ThreadViewport messages={submittedMessages} isStreaming composer={composer} />,
      );
      const scroller = getScroller(container);
      mockScrollGeometry(scroller, 1_904, 500, 1_404);
      const prompt = container.querySelector<HTMLElement>('[data-user-prompt-id="u2"]')!;
      mockPromptPosition(scroller, prompt, 1_420);
      rerender(viewport());
      clock.frame(0);
      clock.frame(300);
      expect(scroller.scrollTop).toBe(1_372);

      mockScrollGeometry(scroller, 2_100, 500, scroller.scrollTop);
      rerender(viewport([...submittedMessages, { ...submittedAnswer, isStreaming: true }]));
      clock.frame(0);
      expect(scroller.scrollTop).toBe(1_372);

      const composerDock = screen.getByTestId("thread-composer-dock");
      const observer = resizeObserver.observers.find((candidate) => candidate.elements.includes(composerDock))!;
      const notifyResize = () => act(() => observer.callback([], observer));
      fireEvent.input(screen.getByLabelText("Message input"), { target: { value: "next question" } });
      composerDock.getBoundingClientRect = () => DOMRect.fromRect({ y: 400, width: 800, height: 240 });
      mockScrollGeometry(scroller, 2_300, 400, scroller.scrollTop);
      notifyResize();
      expect(scroller.scrollTop).toBe(1_372);

      mockScrollGeometry(scroller, 2_548, 400, scroller.scrollTop);
      rerender(viewport([...submittedMessages, { ...submittedAnswer, content: "final answer" }], false));
      clock.frame(0);
      expect(scroller.scrollTop).toBe(1_372);

      // Reflow above the prompt changes its document position, not its reading position.
      mockScrollGeometry(scroller, 3_220, 400, scroller.scrollTop);
      mockPromptPosition(scroller, prompt, 2_092);
      notifyResize();
      expect(scroller.scrollTop).toBe(2_044);
      expect(prompt.getBoundingClientRect().top).toBe(48);

      fireEvent.wheel(scroller, { deltaY: -100 });
      scroller.scrollTop = 1_000;
      fireEvent.scroll(scroller);
      mockScrollGeometry(scroller, 3_320, 400, scroller.scrollTop);
      mockPromptPosition(scroller, prompt, 2_192);
      notifyResize();
      clock.frame(300);
      expect(scroller.scrollTop).toBe(1_000);
    } finally {
      resizeObserver.restore();
    }
  });

  it.each(["wheel", "touch"])("lets %s interrupt anchoring without resuming output follow at the tail", (input) => {
    const clock = controlAnimationFrames();
    const threaded = [...submittedMessages, submittedAnswer];
    const { container, rerender } = render(<ThreadViewport messages={threaded} isStreaming />);
    const scroller = getScroller(container);
    mockScrollGeometry(scroller, 1_904, 500, 1_404);
    rerender(
      <ThreadViewport messages={threaded} isStreaming activeTurnId="turn-2" submittedPromptTurnId="turn-2" />,
    );
    mockPromptPosition(scroller, container.querySelector<HTMLElement>('[data-user-prompt-id="u2"]')!, 1_420);
    const rows = scroller.querySelectorAll<HTMLElement>(".thread-message-row");
    rows[rows.length - 1].getBoundingClientRect = () => DOMRect.fromRect({
      y: scroller.scrollHeight - scroller.scrollTop - 100, width: 800, height: 100,
    });
    act(() => window.dispatchEvent(new Event("resize")));
    clock.frame(0);
    clock.frame(80);

    const scroll = (top: number) => {
      const delta = top - scroller.scrollTop;
      if (input === "wheel") fireEvent.wheel(scroller, { deltaY: delta });
      else {
        fireEvent.touchStart(scroller, { touches: [{ clientX: 100, clientY: 300 }] });
        fireEvent.touchMove(scroller, { touches: [{ clientX: 100, clientY: 300 - delta }] });
      }
      scroller.scrollTop = top;
      fireEvent.scroll(scroller);
      if (input === "touch") fireEvent.touchEnd(scroller);
    };
    scroll(1_300);
    clock.frame(300);
    expect(scroller.scrollTop).toBe(1_300);
    expect(screen.getByRole("button", { name: "Scroll to bottom" })).toBeInTheDocument();

    scroll(1_404);
    expect(screen.queryByRole("button", { name: "Scroll to bottom" })).not.toBeInTheDocument();
    mockScrollGeometry(scroller, 2_100, 500, scroller.scrollTop);
    act(() => window.dispatchEvent(new Event("resize")));
    clock.frame(0);
    expect(scroller.scrollTop).toBe(1_404);
  });

  it("keeps uncommanded scrolling user-owned through layout changes and a tail reversal", async () => {
    const { scroller } = await renderPromptRailViewport();
    expect(scroller.scrollTop).toBe(1_200);

    act(() => {
      scroller.scrollTop = 1_180;
      fireEvent.scroll(scroller);
      window.dispatchEvent(new Event("resize"));
    });
    await flushAnimationFrame();
    expect(scroller.scrollTop).toBe(1_180);

    act(() => {
      scroller.scrollTop = 1_000;
      fireEvent.scroll(scroller);
      scroller.scrollTop = 1_100;
      fireEvent.scroll(scroller);
    });
    // A partial return must not let later layout clamping resume follow.
    act(() => {
      Object.defineProperty(scroller, "scrollHeight", { configurable: true, value: 1_500 });
      scroller.scrollTop = 900;
      fireEvent.scroll(scroller);
      window.dispatchEvent(new Event("resize"));
    });
    await flushAnimationFrame();
    act(() => {
      Object.defineProperty(scroller, "scrollHeight", { configurable: true, value: 1_800 });
      window.dispatchEvent(new Event("resize"));
    });
    await flushAnimationFrame();
    expect(scroller.scrollTop).toBe(900);

    act(() => {
      scroller.scrollTop = 1_200;
      fireEvent.scroll(scroller);
    });
    await flushAnimationFrame();
    expect(scroller.scrollTop).toBe(1_200);

    act(() => {
      scroller.scrollTop = 1_000;
      fireEvent.scroll(scroller);
      window.dispatchEvent(new Event("resize"));
    });
    await flushAnimationFrame();
    expect(scroller.scrollTop).toBe(1_000);
  });

  it.each(["scroll-first", "layout-first"])("keeps the reading position through output and completion with %s delivery", async (ordering) => {
    const threaded: UIMessage[] = [
      { id: "u1", role: "user", content: "question", turnId: "turn-1", createdAt: 1 },
      { id: "a1", role: "assistant", content: "answer", turnId: "turn-1", isStreaming: true, createdAt: 2 },
    ];
    const { container, rerender } = render(
      <ThreadViewport messages={threaded} isStreaming activeTurnId="turn-1" composer={<div />} />,
    );
    const scroller = getScroller(container);
    mockScrollGeometry(scroller, 1_900, 500, 1_400);
    act(() => window.dispatchEvent(new Event("resize")));
    await flushAnimationFrame();

    act(() => {
      scroller.scrollTop = 1_000;
      if (ordering === "scroll-first") fireEvent.scroll(scroller);
      Object.defineProperty(scroller, "scrollHeight", { configurable: true, value: 2_100 });
      rerender(
        <ThreadViewport messages={[threaded[0], { ...threaded[1], content: "answer with more output" }]} isStreaming activeTurnId="turn-1" composer={<div />} />,
      );
    });
    await flushAnimationFrame();
    expect(scroller.scrollTop).toBe(1_000);

    act(() => {
      Object.defineProperty(scroller, "scrollHeight", { configurable: true, value: 2_300 });
      rerender(
        <ThreadViewport messages={[threaded[0], { ...threaded[1], content: "final answer", isStreaming: false }]} isStreaming={false} composer={<div />} />,
      );
    });
    await flushAnimationFrame();
    expect(scroller.scrollTop).toBe(1_000);
  });

  it("tracks the message content edge independently of trailing space and motion ownership", () => {
    const resizeObserver = stubResizeObserver();
    try {
      const { container } = render(<ThreadViewport messages={messages} isStreaming={false} composer={<div>composer</div>} />);
      const scroller = getScroller(container);
      const content = scroller.firstElementChild as HTMLElement;
      const row = scroller.querySelector<HTMLElement>(".thread-message-row:last-child")!;
      const gap = scroller.querySelector<HTMLElement>(".thread-message-end-gap")!;
      let contentBottom = 565;
      scroller.getBoundingClientRect = () => ({ bottom: 600 } as DOMRect);
      gap.getBoundingClientRect = () => ({ height: 36 } as DOMRect);
      row.getBoundingClientRect = () => ({ bottom: contentBottom, height: 100 } as DOMRect);
      act(() => window.dispatchEvent(new Event("resize")));
      Object.defineProperties(scroller, {
        scrollHeight: { configurable: true, value: 1000 },
        clientHeight: { configurable: true, value: 600 },
        scrollTop: { configurable: true, writable: true, value: 300 },
      });
      act(() => { scroller.dispatchEvent(new Event("scroll")); });
      expect(screen.getByRole("button", { name: "Scroll to bottom" })).toBeInTheDocument();
      contentBottom = 564;
      act(() => { scroller.dispatchEvent(new Event("scroll")); });
      expect(screen.queryByRole("button", { name: "Scroll to bottom" })).not.toBeInTheDocument();
      contentBottom = 570;
      const observer = resizeObserver.observers.find((item) => item.elements.includes(content))!;
      act(() => { observer.callback([], observer); });
      expect(screen.getByRole("button", { name: "Scroll to bottom" })).toBeInTheDocument();
      vi.spyOn(ThreadMotionCoordinator.prototype, "navigateLatestTo").mockReturnValue("started");
      fireEvent.click(screen.getByRole("button", { name: "Scroll to bottom" }));
      expect(screen.queryByRole("button", { name: "Scroll to bottom" })).not.toBeInTheDocument();
      fireEvent.wheel(scroller, { deltaY: -20 });
      expect(screen.getByRole("button", { name: "Scroll to bottom" })).toBeInTheDocument();
    } finally {
      resizeObserver.restore();
    }
  });

  it("keeps the scroll-to-bottom button above a growing composer", async () => {
    const resizeObserver = stubResizeObserver();

    try {
      const { container } = render(
        <ThreadViewport
          messages={messages}
          isStreaming={false}
          composer={<div>composer</div>}
        />,
      );
      const scroller = getScroller(container);
      Object.defineProperties(scroller, {
        scrollHeight: { configurable: true, value: 2400 },
        clientHeight: { configurable: true, value: 600 },
        scrollTop: { configurable: true, value: 0 },
      });

      mockMessageEnd(scroller);
      act(() => {
        dispatchUserScroll(scroller);
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

      const composerObserver = resizeObserver.observers.find(
        (observer) => observer.elements.includes(composerDock),
      );
      expect(composerObserver).toBeDefined();

      act(() => {
        composerObserver!.callback([], composerObserver!);
      });
      await flushAnimationFrame();

      expect(buttonPositioner).toHaveStyle({ bottom: "256px" });
    } finally {
      resizeObserver.restore();
    }
  });

  it("gives smooth scroll-to-bottom navigation ownership of the latest target", () => {
    const navigateLatestTo = vi.spyOn(
      ThreadMotionCoordinator.prototype,
      "navigateLatestTo",
    ).mockReturnValue("started");
    const { container } = render(
      <ThreadViewport
        messages={messages}
        isStreaming
        composer={<div>composer</div>}
      />,
    );
    const scroller = getScroller(container);
    Object.defineProperties(scroller, {
      scrollHeight: { configurable: true, value: 2_400 },
      clientHeight: { configurable: true, value: 600 },
      scrollTop: { configurable: true, writable: true, value: 0 },
    });

    mockMessageEnd(scroller);
    act(() => {
      dispatchUserScroll(scroller);
    });
    fireEvent.click(screen.getByRole("button", { name: "Scroll to bottom" }));

    expect(navigateLatestTo).toHaveBeenCalledWith(1_800);
  });

  it("keeps the thread scrollport above a mobile soft keyboard", async () => {
    const visualViewport = stubVisualViewport({ innerHeight: 800, height: 480 });
    try {
      const { container } = render(
        <ThreadViewport
          messages={messages}
          isStreaming={false}
          composer={<textarea aria-label="Message input" />}
        />,
      );
      const scroller = getScroller(container);
      const viewportFrame = container.querySelector(".thread-viewport-frame");
      expect(viewportFrame).not.toBeNull();
      Object.defineProperties(scroller, {
        scrollHeight: { configurable: true, value: 2400 },
        clientHeight: { configurable: true, value: 600 },
        scrollTop: { configurable: true, value: 0 },
      });

      act(() => {
        dispatchUserScroll(scroller);
      });

      const input = screen.getByLabelText("Message input");
      act(() => {
        input.focus();
        fireEvent.focusIn(input);
      });

      await waitFor(() => expect(viewportFrame).toHaveStyle({ bottom: "320px" }));
      expect(screen.queryByRole("button", { name: "Scroll to bottom" })).not.toBeInTheDocument();

      act(() => {
        visualViewport.viewport.dispatchEvent(new Event("resize"));
      });
      expect(viewportFrame).toHaveStyle({ bottom: "320px" });
    } finally {
      visualViewport.restore();
    }
  });

  it("does not apply the keyboard inset twice when the App shell owns the viewport", () => {
    const visualViewport = stubVisualViewport({ innerHeight: 800, height: 480 });
    try {
      const { container } = render(
        <div id="root" className="visual-viewport">
          <ThreadViewport messages={messages} isStreaming={false}
            composer={<textarea aria-label="Message input" />} />
        </div>,
      );
      act(() => { screen.getByLabelText("Message input").focus(); });
      expect(container.querySelector(".thread-viewport-frame")).not.toHaveStyle({ bottom: "320px" });
    } finally {
      visualViewport.restore();
    }
  });

  it("keeps the welcome composer above a mobile soft keyboard", async () => {
    const visualViewport = stubVisualViewport({ innerHeight: 800, height: 480 });
    try {
      const { container } = render(
        <ThreadViewport
          messages={emptyMessages}
          isStreaming={false}
          composer={<textarea aria-label="Message input" />}
          emptyState={<div>welcome</div>}
          showScrollToBottomButton={false}
        />,
      );
      const scroller = container.querySelector(".thread-viewport-scrollbar") as HTMLElement;
      const input = screen.getByLabelText("Message input");

      act(() => {
        input.focus();
        fireEvent.focusIn(input);
      });

      await waitFor(() => expect(scroller).toHaveStyle({ bottom: "320px" }));
    } finally {
      visualViewport.restore();
    }
  });

  it("keeps one composer instance while the landing layout docks into a thread", () => {
    const { rerender } = render(
      <ThreadViewport
        messages={emptyMessages}
        isStreaming={false}
        composer={(
          <input
            data-testid="persistent-composer"
            defaultValue="draft"
          />
        )}
        emptyState={<div>welcome</div>}
      />,
    );

    const initialComposer = screen.getByTestId("persistent-composer");
    fireEvent.change(initialComposer, { target: { value: "kept draft" } });

    rerender(
      <ThreadViewport
        messages={messages}
        isStreaming
        composer={(
          <input
            data-testid="persistent-composer"
            defaultValue="draft"
          />
        )}
        emptyState={<div>welcome</div>}
      />,
    );

    const dockedComposer = screen.getByTestId("persistent-composer");
    expect(dockedComposer).toBe(initialComposer);
    expect(dockedComposer).toHaveValue("kept draft");
    expect(dockedComposer.closest(".thread-layout")).toHaveAttribute(
      "data-layout",
      "thread",
    );
  });

  it("separates the mobile welcome copy and composer into responsive rows", () => {
    render(
      <ThreadViewport
        messages={emptyMessages}
        isStreaming={false}
        composer={<div>composer</div>}
        emptyState={<div>welcome</div>}
      />,
    );

    const layout = screen.getByTestId("thread-welcome-layout");
    expect(layout).toHaveClass("thread-layout", "grid");
    expect(layout).toHaveAttribute("data-layout", "hero");
    expect(screen.getByText("welcome").parentElement).toHaveClass(
      "min-h-0",
      "items-center",
      "sm:items-end",
      "sm:pb-8",
    );
    expect(screen.getByTestId("thread-composer-motion")).toContainElement(
      screen.getByText("composer"),
    );
  });

  it("allows the welcome view to scroll when a short viewport overflows", async () => {
    const { container } = render(
      <ThreadViewport
        messages={emptyMessages}
        isStreaming={false}
        composer={<div>composer</div>}
        emptyState={<div>welcome</div>}
        showScrollToBottomButton={false}
      />,
    );
    const scroller = container.querySelector(".thread-viewport-scrollbar") as HTMLElement;
    Object.defineProperties(scroller, {
      scrollHeight: { configurable: true, value: 620 },
      clientHeight: { configurable: true, value: 320 },
    });

    act(() => {
      window.dispatchEvent(new Event("resize"));
    });

    await waitFor(() => expect(scroller).toHaveClass("overflow-y-auto"));
    expect(scroller).toHaveClass(
      "[scrollbar-width:none]",
      "[&::-webkit-scrollbar]:hidden",
    );
  });

  it("scrolls recent messages into view when the composer receives focus", async () => {
    const scrollTo = vi.fn();
    const { container } = render(
      <ThreadViewport
        messages={messages}
        isStreaming={false}
        composer={<textarea aria-label="Message input" />}
      />,
    );
    const scroller = getScroller(container);
    Object.defineProperties(scroller, {
      scrollHeight: { configurable: true, value: 2400 },
      clientHeight: { configurable: true, value: 600 },
      scrollTop: { configurable: true, writable: true, value: 0 },
      scrollTo: { configurable: true, value: scrollTo },
    });

    act(() => {
      dispatchUserScroll(scroller);
    });
    scrollTo.mockClear();

    const input = screen.getByLabelText("Message input");
    act(() => {
      input.focus();
      fireEvent.focusIn(input);
    });

    await waitFor(() => expect(scroller.scrollTop).toBe(1800));
  });

  it("scrolls recent messages into view when the focused composer resizes the visual viewport without an inset", async () => {
    const visualViewport = stubVisualViewport({ innerHeight: 500, height: 500 });
    const scrollTo = vi.fn();

    try {
      const { container } = render(
        <ThreadViewport
          messages={messages}
          isStreaming={false}
          composer={<textarea aria-label="Message input" />}
        />,
      );
      const scroller = getScroller(container);
      Object.defineProperties(scroller, {
        scrollHeight: { configurable: true, value: 2400 },
        clientHeight: { configurable: true, value: 600 },
        scrollTop: { configurable: true, writable: true, value: 0 },
        scrollTo: { configurable: true, value: scrollTo },
      });

      const input = screen.getByLabelText("Message input");
      Object.defineProperty(document, "activeElement", {
        configurable: true,
        get: () => input,
      });

      act(() => {
        visualViewport.viewport.dispatchEvent(new Event("resize"));
      });

      await waitFor(() => expect(scroller.scrollTop).toBe(1800));
      expect(scroller).not.toHaveStyle({ bottom: "320px" });
    } finally {
      Reflect.deleteProperty(document, "activeElement");
      visualViewport.restore();
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
    const scroller = getScroller(container);
    Object.defineProperties(scroller, {
      scrollHeight: { configurable: true, value: 2400 },
      clientHeight: { configurable: true, value: 600 },
      scrollTop: { configurable: true, writable: true, value: 0 },
    });

    act(() => {
      dispatchUserScroll(scroller);
    });

    expect(screen.queryByRole("button", { name: "Scroll to bottom" })).not.toBeInTheDocument();
  });

  it("renders only the tail window for long history by default", () => {
    const longMessages = makeLongMessages(300);
    const firstVisible = longMessages.length - INITIAL_HISTORY_WINDOW;

    render(
      <ThreadViewport
        messages={longMessages}
        isStreaming={false}
        composer={<div />}
      />,
    );

    expect(screen.queryByText(`message ${firstVisible - 1}`)).not.toBeInTheDocument();
    expect(screen.getByText(`message ${firstVisible}`)).toBeInTheDocument();
    expect(screen.getByText("message 299")).toBeInTheDocument();
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

    const scroller = getScroller(container);
    Object.defineProperties(scroller, {
      scrollHeight: { configurable: true, value: 2400 },
      clientHeight: { configurable: true, value: 600 },
      scrollTop: { configurable: true, writable: true, value: 0 },
    });

    act(() => {
      dispatchUserScroll(scroller);
    });

    const firstVisible =
      300 - INITIAL_HISTORY_WINDOW - HISTORY_WINDOW_INCREMENT;

    expect(
      screen.queryByText(`message ${firstVisible - 1}`),
    ).not.toBeInTheDocument();
    expect(screen.getByText(`message ${firstVisible}`)).toBeInTheDocument();
    expect(screen.getAllByText("message 299").length).toBeGreaterThan(0);
  });

  it("prefetches earlier history within half a viewport of the top", () => {
    const expandedFirstVisible = 300 - INITIAL_HISTORY_WINDOW - HISTORY_WINDOW_INCREMENT;
    const { container } = render(
      <ThreadViewport
        messages={makeLongMessages(300)}
        isStreaming={false}
        composer={<div />}
      />,
    );

    const scroller = getScroller(container);
    Object.defineProperties(scroller, {
      scrollHeight: { configurable: true, value: 2400 },
      clientHeight: { configurable: true, value: 600 },
      scrollTop: { configurable: true, writable: true, value: 301 },
    });

    act(() => {
      dispatchUserScroll(scroller);
    });
    expect(
      screen.queryByText(`message ${300 - INITIAL_HISTORY_WINDOW - 1}`),
    ).not.toBeInTheDocument();

    scroller.scrollTop = 250;
    act(() => {
      dispatchUserScroll(scroller);
    });
    expect(screen.getByText(`message ${expandedFirstVisible}`)).toBeInTheDocument();
    expect(screen.queryByText(`message ${expandedFirstVisible - 1}`)).not.toBeInTheDocument();
  });

  it("keeps the first visible history item fixed while deferred rows materialize", () => {
    const resizeObserver = stubResizeObserver();
    let hitTarget: Element | null = null;
    const hitTest = stubElementsFromPoint(() => hitTarget ? [hitTarget] : []);
    try {
      const { container } = render(
        <ThreadViewport
          messages={makeLongMessages(300)}
          isStreaming={false}
          composer={<div />}
        />,
      );

      const scroller = getScroller(container);
      let scrollHeight = 2_400;
      Object.defineProperties(scroller, {
        scrollHeight: { configurable: true, get: () => scrollHeight },
        clientHeight: { configurable: true, value: 600 },
        scrollTop: { configurable: true, writable: true, value: 80 },
        getBoundingClientRect: {
          configurable: true,
          value: () => DOMRect.fromRect({ y: 0, width: 800, height: 600 }),
        },
      });

      const firstVisible = 300 - INITIAL_HISTORY_WINDOW;
      const anchor = screen.getByText(`message ${firstVisible}`)
        .closest<HTMLElement>("[data-thread-display-unit]")!;
      expect(anchor).not.toBeNull();
      hitTarget = anchor;
      let anchorDocumentTop = 200;
      Object.defineProperty(anchor, "getBoundingClientRect", {
        configurable: true,
        value: () => DOMRect.fromRect({
          y: anchorDocumentTop - scroller.scrollTop,
          width: 800,
          height: 40,
        }),
      });

      act(() => {
        dispatchUserScroll(scroller);
      });
      expect(hitTest.mock).toHaveBeenCalled();

      // Deferred content grows above the existing row wrapper.
      anchorDocumentTop += 180;
      scrollHeight += 180;
      const content = screen.getByTestId("thread-message-region").firstElementChild;
      const observer = resizeObserver.observers.find((candidate) =>
        content ? candidate.elements.includes(content) : false,
      );
      expect(observer).toBeDefined();
      act(() => {
        observer?.callback([], observer);
      });

      expect(scroller.scrollTop).toBe(260);
      expect(anchor.getBoundingClientRect().top).toBe(120);

      // ResizeObserver may arrive before the next native scroll event.
      scroller.scrollTop = 240;
      anchorDocumentTop += 60;
      scrollHeight += 60;
      act(() => { observer?.callback([], observer); });
      expect(scroller.scrollTop).toBe(240);
      act(() => { fireEvent.scroll(scroller); });
      anchorDocumentTop += 40;
      scrollHeight += 40;
      act(() => { observer?.callback([], observer); });
      expect(scroller.scrollTop).toBe(280);
    } finally {
      hitTest.restore();
      resizeObserver.restore();
    }
  });

  it.each(["sequence", "stream", "shared-stream", "missing"] as const)(
    "handles a fragment prepend with %s identity without selecting the wrong answer",
    (identity) => {
      const turnId = "partial-turn";
      const answer = (id: string, content: string, turnSeq: number): UIMessage => ({
        id, role: "assistant", content, createdAt: turnSeq, turnId, turnPhase: "answer", turnSeq,
        ...(identity === "stream" ? { streamId: `stream-${content}` } : {}),
        ...(identity === "shared-stream" ? { streamId: "shared-stream" } : {}),
      });
      const activity = (id: string, turnSeq: number): UIMessage => ({
        id, role: "tool", kind: "trace", content: "tool", traces: ["tool"],
        createdAt: turnSeq, turnId, turnPhase: "activity", turnSeq,
      });
      const tail = [answer("history-1", "tail one", 3), activity("history-2", 4), answer("history-3", "tail two", 5)];
      const { container, rerender } = render(<ThreadViewport messages={tail} isStreaming={false} />);
      const scroller = getScroller(container);
      let prepended = false;
      Object.defineProperties(scroller, {
        scrollHeight: { configurable: true, get: () => prepended ? 2_580 : 2_400 },
        clientHeight: { configurable: true, value: 600 },
        scrollTop: { configurable: true, writable: true, value: 80 },
      });
      const originalRect = HTMLElement.prototype.getBoundingClientRect;
      vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
        if (this === scroller) return DOMRect.fromRect({ width: 800, height: 600 });
        if (this.hasAttribute("data-thread-display-unit")) {
          const top = this.textContent?.includes("tail one") ? (prepended ? 380 : 200) : 150;
          return DOMRect.fromRect({ y: top - scroller.scrollTop, width: 800, height: 40 });
        }
        return originalRect.call(this);
      });
      const hitTest = stubElementsFromPoint(() => [
        screen.getByText("tail one").closest<HTMLElement>("[data-thread-display-unit]")!,
      ]);
      try {
        act(() => dispatchUserScroll(scroller));
        prepended = true;
        const replayedSequence = identity === "stream" || identity === "missing";
        rerender(<ThreadViewport isStreaming={false} messages={[
          { id: "history-0", role: "user", content: "earlier prompt", createdAt: 0, turnId, turnPhase: "user" },
          answer("history-1", "earlier answer", 1), activity("history-2", 2),
          answer("history-3", "tail one", replayedSequence ? 13 : 3),
          activity("history-4", replayedSequence ? 14 : 4),
          answer("history-5", "tail two", replayedSequence ? 15 : 5),
        ]} />);
        // Without a matching source, do not jump to the earlier answer which reused its old id.
        expect(scroller.scrollTop).toBe(identity === "missing" ? 80 : 260);
        expect(screen.getByText("tail one").closest<HTMLElement>("[data-thread-display-unit]")!
          .getBoundingClientRect().top).toBe(identity === "missing" ? 300 : 120);
      } finally {
        hitTest.restore();
      }
    },
  );

  it("keeps a unique answer anchored when live identity changes on replay", () => {
    const live: UIMessage = {
      id: "live-answer", role: "assistant", content: "same answer", createdAt: 1,
      turnId: "live-turn", turnPhase: "answer", turnSeq: 2,
    };
    const { container, rerender } = render(<ThreadViewport messages={[live]} isStreaming={false} />);
    const scroller = getScroller(container);
    let replayed = false;
    Object.defineProperties(scroller, {
      scrollHeight: { configurable: true, get: () => replayed ? 2_480 : 2_400 },
      clientHeight: { configurable: true, value: 600 },
      scrollTop: { configurable: true, writable: true, value: 80 },
    });
    const originalRect = HTMLElement.prototype.getBoundingClientRect;
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      if (this === scroller) return DOMRect.fromRect({ width: 800, height: 600 });
      if (this.hasAttribute("data-thread-display-unit")) {
        return DOMRect.fromRect({ y: (replayed ? 280 : 200) - scroller.scrollTop, width: 800, height: 40 });
      }
      return originalRect.call(this);
    });
    const hitTest = stubElementsFromPoint(() => [
      screen.getByText("same answer").closest<HTMLElement>("[data-thread-display-unit]")!,
    ]);
    try {
      act(() => dispatchUserScroll(scroller));
      const answerNode = screen.getByText("same answer");
      replayed = true;
      rerender(<ThreadViewport messages={[{ ...live, id: "replayed-answer", turnSeq: 11 }]} isStreaming={false} />);
      expect(screen.getByText("same answer")).toBe(answerNode);
      expect(scroller.scrollTop).toBe(160);
      expect(answerNode.closest<HTMLElement>("[data-thread-display-unit]")!.getBoundingClientRect().top).toBe(120);
    } finally {
      hitTest.restore();
    }
  });

  it.each(["wheel", "touch", "keyboard"] as const)(
    "requests older history on %s intent when the initial page does not overflow",
    (input) => {
      const onLoadOlder = vi.fn();
      const { container } = render(
        <ThreadViewport messages={messages} isStreaming={false}
          hasMoreBefore onLoadOlder={onLoadOlder} />,
      );
      const scroller = getScroller(container);
      mockScrollGeometry(scroller, 746, 746);
      expect(onLoadOlder).not.toHaveBeenCalled();
      dispatchHistoryInput(scroller, input);
      expect(onLoadOlder).toHaveBeenCalledTimes(1);
    },
  );

  describe.each(["wheel", "touch"] as const)("%s history boundary", (input) => {
    it.each([
      { loadingOlder: true },
      { conversationReady: false },
      { hasMoreBefore: false },
    ])("keeps history blocked: %o", (blocked) => {
      const onLoadOlder = vi.fn();
      const { container } = render(<ThreadViewport messages={messages} isStreaming={false}
        hasMoreBefore onLoadOlder={onLoadOlder} {...blocked} />);
      const scroller = getScroller(container);
      dispatchHistoryInput(scroller, input);
      expect(onLoadOlder).not.toHaveBeenCalled();
      if ("conversationReady" in blocked && blocked.conversationReady === false) expect(historyPull(scroller)).toBe(0);
    });
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

    const scroller = getScroller(container);
    mockScrollGeometry(scroller, 1800, 600);

    act(() => {
      dispatchUserScroll(scroller);
    });

    expect(onLoadOlder).toHaveBeenCalledTimes(1);
  });

  it.each(["wheel", "touch", "keyboard"] as const)("pauses automatic requests after failure but accepts another %s boundary gesture", (input) => {
    const onLoadOlder = vi.fn();

    const { container } = render(
      <ThreadViewport
        messages={makeLongMessages(20)}
        isStreaming={false}
        composer={<div />}
        hasMoreBefore
        olderError="offline"
        onLoadOlder={onLoadOlder}
      />,
    );

    const scroller = getScroller(container);
    mockScrollGeometry(scroller, 1800, 600);

    act(() => {
      dispatchUserScroll(scroller);
      scroller.dispatchEvent(new Event("scroll"));
    });

    expect(onLoadOlder).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Loading failed. Retry" }).querySelectorAll(".thread-history-blocks > span")).toHaveLength(9);
    dispatchHistoryInput(scroller, input);
    expect(onLoadOlder).toHaveBeenCalledTimes(1);
  });

  it("keeps real loading visible after leaving the top without fetching again", async () => {
    const onLoadOlder = vi.fn();
    const { container, rerender } = render(
      <ThreadViewport messages={messages} isStreaming={false}
        hasMoreBefore loadingOlder onLoadOlder={onLoadOlder} />,
    );
    const scroller = getScroller(container);
    mockScrollGeometry(scroller, 1800, 600, 200);
    act(() => dispatchUserScroll(scroller));
    expect(await screen.findByText("Loading earlier messages…")).toBeVisible();
    expect(scroller.scrollTop).toBe(200);
    expect(onLoadOlder).not.toHaveBeenCalled();

    act(() => {
      scroller.scrollTop = 800;
      dispatchUserScroll(scroller);
    });
    expect(screen.getByText("Loading earlier messages…")).toBeInTheDocument();
    rerender(<ThreadViewport messages={messages} isStreaming={false}
      conversationKey="another" hasMoreBefore onLoadOlder={onLoadOlder} />);
    expect(screen.queryByText("Loading earlier messages…")).not.toBeInTheDocument();
  });

  it("reveals touch feedback, springs back on cancellation, and requests only on an armed release", async () => {
    const onLoadOlder = vi.fn();
    const props = { messages, isStreaming: false, hasMoreBefore: true, onLoadOlder };
    const { container, rerender } = render(<ThreadViewport {...props} />);
    const scroller = getScroller(container);
    const touch = (y: number) => ({ touches: [{ clientX: 100, clientY: y }] });
    fireEvent.touchStart(scroller, touch(200));
    fireEvent.touchMove(scroller, touch(240));
    expect(historyPull(scroller)).toBeGreaterThan(0);
    expect(screen.getByRole("status").querySelectorAll(".thread-history-blocks > span")).toHaveLength(9);
    expect(container.querySelector(".thread-history-status")).not.toHaveClass("invisible");
    expect(onLoadOlder).not.toHaveBeenCalled();
    fireEvent.touchEnd(scroller);
    expect(historyPull(scroller)).toBeGreaterThan(0);
    await waitFor(() => expect(historyPull(scroller)).toBe(0));

    fireEvent.touchStart(scroller, touch(200));
    fireEvent.touchMove(scroller, touch(380));
    expect(onLoadOlder).not.toHaveBeenCalled();
    expect(screen.getByRole("status").querySelectorAll(".thread-history-blocks > span")).toHaveLength(9);
    fireEvent.touchEnd(scroller);
    expect(onLoadOlder).toHaveBeenCalledTimes(1);
    rerender(<ThreadViewport {...props} loadingOlder />);
    fireEvent.scroll(scroller);
    expect(onLoadOlder).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Loading earlier messages…")).toBeInTheDocument();
    rerender(<ThreadViewport {...props} loadingOlder />);
    expect(container.querySelector(".thread-history-slot")).toBeInTheDocument();
    const prepended = [
      { ...messages[0], id: "older-u0", content: "Earlier message" },
      ...messages,
    ];
    rerender(<ThreadViewport {...props} messages={prepended} />);
    await waitFor(() => expect(historyPull(scroller)).toBe(0));
    expect(container.querySelector(".thread-history-slot")).not.toBeInTheDocument();
    expect(container.querySelector(".thread-history-status")).toHaveAttribute("data-state", "ready");
    expect(container.querySelector(".thread-history-status")).toHaveClass("invisible");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByText("Loading earlier messages…")).not.toBeInTheDocument();
  });

  it("does not fetch on touch scroll alone or horizontal gestures and clears pull on session change", () => {
    const onLoadOlder = vi.fn();
    const props = { messages, isStreaming: false, hasMoreBefore: true, onLoadOlder };
    const { container, rerender } = render(<ThreadViewport {...props} conversationKey="a" />);
    const scroller = getScroller(container);
    fireEvent.touchStart(scroller, { touches: [{ clientX: 100, clientY: 200 }] });
    fireEvent.touchMove(scroller, { touches: [{ clientX: 300, clientY: 220 }] });
    fireEvent.scroll(scroller);
    expect(historyPull(scroller)).toBe(0);
    expect(onLoadOlder).not.toHaveBeenCalled();
    fireEvent.touchEnd(scroller);
    fireEvent.touchStart(scroller, { touches: [{ clientX: 100, clientY: 200 }] });
    fireEvent.touchMove(scroller, { touches: [{ clientX: 100, clientY: 240 }] });
    rerender(<ThreadViewport {...props} conversationKey="b" />);
    expect(historyPull(scroller)).toBe(0);
    expect(onLoadOlder).not.toHaveBeenCalled();
  });

  it("animates boundary frames without rerendering the message tree", async () => {
    const onRender = vi.fn();
    const { container } = render(<Profiler id="history" onRender={onRender}>
      <ThreadViewport messages={messages} isStreaming={false} />
    </Profiler>);
    await flushAnimationFrame();
    await flushAnimationFrame();
    fireEvent.wheel(getScroller(container), { deltaY: -100 });
    await flushAnimationFrame();
    onRender.mockClear();
    await flushAnimationFrame();
    await flushAnimationFrame();
    expect(historyPull(getScroller(container))).toBeGreaterThan(0);
    expect(onRender).not.toHaveBeenCalled();
  });

  it("shows the confirmed start only during boundary feedback and clears it on conversation changes", async () => {
    const onLoadOlder = vi.fn();
    const props = { messages, isStreaming: false, onLoadOlder };
    const { container, rerender } = render(<ThreadViewport {...props} conversationKey="a" />);
    const scroller = getScroller(container);
    expect(screen.queryByText("No earlier messages")).not.toBeInTheDocument();
    fireEvent.wheel(scroller, { deltaY: -100 });
    expect(screen.getByText("hello")).toBeVisible();
    expect(screen.getByText("No earlier messages")).toBeVisible();
    await waitFor(() => expect(historyPull(scroller)).toBeGreaterThan(0));
    await waitFor(() => expect(screen.queryByText("No earlier messages")).not.toBeInTheDocument());
    expect(historyPull(scroller)).toBe(0);
    expect(scroller.scrollTop).toBe(0);
    fireEvent.wheel(scroller, { deltaY: -100 });
    expect(screen.getByText("No earlier messages")).toBeVisible();
    rerender(<ThreadViewport {...props} conversationKey="b" />);
    expect(screen.queryByText("No earlier messages")).not.toBeInTheDocument();
    expect(historyPull(scroller)).toBe(0);
    expect(onLoadOlder).not.toHaveBeenCalled();
  });

  it("renders a prompt rail that jumps to user messages", async () => {
    const navigateTo = vi.spyOn(ThreadCameraController.prototype, "navigateTo")
      .mockReturnValue("started");
    const scrollTo = vi.fn();
    const { promptEls } = await renderPromptRailViewport({ scrollTo });

    expect(promptEls).toHaveLength(5);

    expect(screen.getByLabelText("My message navigation")).toBeInTheDocument();
    const promptMarkers = screen.getAllByRole("button", { name: /Jump to message:/ });
    const markerTops = promptMarkers.map((marker) => Number.parseFloat(marker.style.top));
    expect(markerTops[2]).toBeCloseTo(150);
    expect(markerTops[1] - markerTops[0]).toBeCloseTo(16);
    expect(markerTops[4] - markerTops[0]).toBeCloseTo(64);

    const railMarkers = screen.getAllByTestId("prompt-rail-marker");
    expect(railMarkers).toHaveLength(promptMarkers.length);
    expect(railMarkers.every((marker) => marker.style.width === "9px")).toBe(true);

    fireEvent.pointerEnter(promptMarkers[2]);
    expect(railMarkers.map((marker) => marker.style.width)).toEqual([
      "16px",
      "22px",
      "28px",
      "22px",
      "16px",
    ]);

    fireEvent.pointerLeave(promptMarkers[2]);
    expect(railMarkers.every((marker) => marker.style.width === "9px")).toBe(true);

    const targetPrompt = screen.getByRole("button", { name: "Jump to message: message 3" });
    fireEvent.pointerEnter(targetPrompt);
    const preview = screen.getByTestId("prompt-rail-preview");
    expect(within(preview).getByText("message 3")).toBeInTheDocument();
    expect(within(preview).getByText("answer 3")).toBeInTheDocument();

    fireEvent.click(targetPrompt);

    expect(navigateTo).toHaveBeenCalledWith(1032);
  });

  it("renders markdown in prompt rail previews", async () => {
    const promptMessages = makePromptExchangeMessages(5);
    const answer = promptMessages.find((message) => message.id === "a3");
    if (!answer) throw new TypeError("prompt answer fixture missing");
    answer.content = "### Confirmed limit\n\nUse the **policy cap**.";

    await renderPromptRailViewport({ messages: promptMessages });

    const targetPrompt = screen.getByRole("button", { name: "Jump to message: message 3" });
    fireEvent.pointerEnter(targetPrompt);
    const preview = screen.getByTestId("prompt-rail-preview");

    await waitFor(() => {
      expect(preview.querySelector("h3")).toHaveTextContent("Confirmed limit");
    });
    expect(preview.querySelector("strong")).toHaveTextContent("policy cap");
    expect(preview).not.toHaveTextContent("###");
    expect(preview).not.toHaveTextContent("**");
  });

  it("lets direct paging input interrupt prompt rail navigation", async () => {
    vi.spyOn(ThreadCameraController.prototype, "navigateTo")
      .mockReturnValue("started");
    const cancel = vi.spyOn(ThreadCameraController.prototype, "cancel");
    const { scroller } = await renderPromptRailViewport();
    const targetPrompt = screen.getByRole("button", { name: "Jump to message: message 3" });
    const restartNavigation = () => {
      fireEvent.click(targetPrompt);
      cancel.mockClear();
    };

    scroller.scrollTop = 500;
    restartNavigation();
    fireEvent.wheel(scroller, { deltaY: 120 });
    expect(cancel).toHaveBeenCalledTimes(1);

    restartNavigation();
    fireEvent.wheel(scroller, { deltaY: -120 });
    expect(cancel).toHaveBeenCalledTimes(1);

    restartNavigation();
    fireEvent.keyDown(scroller, { key: "PageDown" });
    expect(cancel).toHaveBeenCalledTimes(1);

    restartNavigation();
    fireEvent.touchStart(scroller, { touches: [{ clientX: 100, clientY: 300 }] });
    fireEvent.touchMove(scroller, { touches: [{ clientX: 100, clientY: 200 }] });
    expect(cancel).toHaveBeenCalledTimes(1);

    restartNavigation();
    scroller.scrollTop = 1200;
    fireEvent.wheel(scroller, { deltaY: 120 });
    expect(cancel).toHaveBeenCalledTimes(1);

    cancel.mockClear();
    fireEvent.wheel(scroller, { deltaY: 120 });
    expect(cancel).not.toHaveBeenCalled();
  });

  it("opens a prompt navigator list and jumps to a selected prompt", async () => {
    const navigateTo = vi.spyOn(ThreadCameraController.prototype, "navigateTo")
      .mockReturnValue("started");
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

    fireEvent.click(screen.getByRole("button", { name: "Message navigation" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("My messages")).toBeInTheDocument();
    expect(within(dialog).getByText("message 4")).toBeInTheDocument();

    fireEvent.change(within(dialog).getByRole("textbox", { name: "Search messages" }), {
      target: { value: "message 4" },
    });
    expect(within(dialog).queryByText("message 1")).not.toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Jump to message: message 4" }));

    expect(navigateTo).toHaveBeenCalledWith(1200);
  });

  it("expands the history window before jumping to an older prompt from the navigator", async () => {
    const longMessages = makeLongMessages(300);
    render(<ViewportWithPromptNavigator messages={longMessages} />);

    expect(screen.queryByText("message 20")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Message navigation" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Search messages" }), { target: { value: "message 20" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Jump to message: message 20" }));

    await waitFor(() => expect(screen.getByText("message 20")).toBeInTheDocument());
  });

  it("returns from a history window to a live prompt that has no saved cursor yet", async () => {
    const viewportRef = createRef<ThreadViewportHandle>();
    const latest = vi.fn();
    const navigation = { prompts: [{ id: "u1", label: "hello", preview: "hello", answerPreview: "", createdAt: 1, index: 0 }],
      window: { messages: [{ id: "old", role: "user" as const, content: "old question", createdAt: 0 }],
        userMessageOffset: 0, hasMoreBefore: false, hasMoreAfter: true, forkBoundaryMessageCount: null },
      target: null, operation: null, loading: false, error: null, jump: vi.fn(), older: vi.fn(), newer: vi.fn(), cancel: vi.fn(), latest, retry: vi.fn(), expandTraceDetail: vi.fn() };
    const view = render(<ThreadViewport ref={viewportRef} messages={messages} isStreaming={false} composer={<div />} navigation={navigation} />);
    act(() => viewportRef.current?.jumpToUserPrompt("u1"));
    expect(latest).toHaveBeenCalledOnce();
    view.rerender(<ThreadViewport ref={viewportRef} messages={messages} isStreaming={false} composer={<div />} navigation={{ ...navigation, window: null }} />);
    await waitFor(() => expect(screen.getByText("hello")).toBeInTheDocument());
  });

  it.each(["wheel", "touch", "keyboard"] as const)("loads newer history after one %s input reaches the page bottom", async (input) => {
    const history = makePromptExchangeMessages(5);
    const newer = vi.fn();
    const navigation: PromptHistoryNavigation = {
      prompts: [], window: { messages: history, userMessageOffset: 0,
        hasMoreBefore: false, hasMoreAfter: true, forkBoundaryMessageCount: null },
      target: null, operation: null, loading: false, error: null,
      jump: vi.fn(), older: vi.fn(), newer, cancel: vi.fn(), latest: vi.fn(), retry: vi.fn(), expandTraceDetail: vi.fn(),
    };
    const view = render(<ThreadViewport messages={messages} isStreaming={false} composer={<div />} navigation={navigation} />);
    await flushAnimationFrame();
    const scroller = view.getByTestId("thread-message-region");
    mockScrollGeometry(scroller, 2000, 500, 100);

    const forward = () => {
      if (input === "wheel") fireEvent.wheel(scroller, { deltaY: 10000 });
      if (input === "keyboard") fireEvent.keyDown(scroller, { key: "End" });
      if (input === "touch") {
        fireEvent.touchStart(scroller, { touches: [{ clientX: 100, clientY: 400 }] });
        fireEvent.touchMove(scroller, { touches: [{ clientX: 100, clientY: 200 }] });
        fireEvent.touchEnd(scroller);
      }
    };
    // A large input can cross the entire prefetch range in one native scroll.
    forward();
    expect(newer).not.toHaveBeenCalled();
    act(() => {
      scroller.scrollTop = 1500;
      fireEvent.scroll(scroller);
    });
    expect(newer).toHaveBeenCalledOnce();

    // Appending a page must preserve the reader's position, not follow its tail.
    mockScrollGeometry(scroller, 2800, 500, 1500);
    view.rerender(<ThreadViewport messages={messages} isStreaming={false} composer={<div />}
      navigation={{ ...navigation, window: { ...navigation.window!, messages: makePromptExchangeMessages(10) } }} />);
    await flushAnimationFrame();
    expect(scroller.scrollTop).toBe(1500);

    // At the existing page boundary, forward input cannot produce a scroll event.
    mockScrollGeometry(scroller, 2800, 500, 2300);
    forward();
    expect(newer).toHaveBeenCalledTimes(2);
    mockScrollGeometry(scroller, 3600, 500, 2300);
    view.rerender(<ThreadViewport messages={messages} isStreaming={false} composer={<div />}
      navigation={{ ...navigation, window: { ...navigation.window!, messages: makePromptExchangeMessages(15) } }} />);
    await flushAnimationFrame();
    expect(scroller.scrollTop).toBe(2300);
  });

  it("includes the selected prompt when one server turn exceeds the local render window", async () => {
    const history: UIMessage[] = [{ id: "old-user", role: "user", content: "Large old turn", createdAt: 1 },
      ...Array.from({ length: INITIAL_HISTORY_WINDOW + 10 }, (_, index): UIMessage => ({
        id: `old-answer-${index}`, role: "assistant", content: `Answer part ${index}`, createdAt: index + 2,
      }))];
    render(<ThreadViewport messages={messages} isStreaming={false} composer={<div />}
      navigation={{ prompts: [], window: { messages: history, userMessageOffset: 0,
        hasMoreBefore: false, hasMoreAfter: true, forkBoundaryMessageCount: null },
      target: { id: "old-user", sequence: 1 }, operation: null, loading: false, error: null,
      jump: vi.fn(), older: vi.fn(), newer: vi.fn(), cancel: vi.fn(), latest: vi.fn(), retry: vi.fn(), expandTraceDetail: vi.fn() }} />);
    await waitFor(() => expect(screen.getByText("Large old turn")).toBeInTheDocument());
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

    const scroller = getScroller(container);
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

    expect(screen.getByLabelText("My message navigation")).toBeInTheDocument();
  });

  it.each([2, 3, 100])("keeps %i prompts navigable before a very long answer", async (count) => {
    const navigateTo = vi.spyOn(ThreadCameraController.prototype, "navigateTo")
      .mockReturnValue("started");
    const { promptEls, scroller } = await renderPromptRailViewport({
      messages: makeLongMessages(count),
    });
    Object.defineProperty(scroller, "scrollHeight", {
      configurable: true,
      value: 1_000_000,
    });
    promptEls.forEach((el, index) => {
      Object.defineProperty(el, "offsetTop", { configurable: true, value: index * 40 });
    });
    await act(async () => {
      window.dispatchEvent(new Event("resize"));
      await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
    });

    const markers = screen.getAllByRole("button", { name: /Jump to message:/ });
    if (count < 30) {
      expect(markers).toHaveLength(count);
      markers.forEach((marker, index) => {
        fireEvent.click(marker);
        expect(navigateTo).toHaveBeenLastCalledWith(Math.max(0, index * 40 - 48));
      });
    } else {
      expect(markers.length).toBeGreaterThan(1);
      expect(markers.length).toBeLessThan(count);
    }
    fireEvent.click(markers[markers.length - 1]);
    expect(navigateTo).toHaveBeenLastCalledWith(Math.max(0, (count - 1) * 40 - 48));
  });

  it("aligns prompt jumps with the scroll inset independently of message layout", async () => {
    const navigateTo = vi.spyOn(ThreadCameraController.prototype, "navigateTo")
      .mockReturnValue("started");
    const { scroller } = await renderPromptRailViewport();
    const marker = screen.getByRole("button", { name: "Jump to message: message 1" });

    scroller.style.scrollPaddingTop = "16px";
    fireEvent.click(marker);
    expect(navigateTo).toHaveBeenLastCalledWith(344);

    scroller.style.scrollPaddingTop = "48px";
    fireEvent.click(marker);
    expect(navigateTo).toHaveBeenLastCalledWith(312);
  });

  it("windows dense prompt rails while keeping each individual prompt reachable", async () => {
    const navigateTo = vi.spyOn(ThreadCameraController.prototype, "navigateTo")
      .mockReturnValue("started");
    const promptMessages = makeLongMessages(100);
    const { container } = render(
      <ThreadViewport
        messages={promptMessages}
        isStreaming={false}
        composer={<div />}
      />,
    );

    const scroller = getScroller(container);
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

    const promptMarkers = screen.getAllByRole("button", { name: /Jump to message:/ });
    expect(promptMarkers.length).toBeGreaterThan(3);
    expect(promptMarkers.length).toBeLessThan(100);
    fireEvent.scroll(screen.getByTestId("prompt-rail-scroll"), { target: { scrollTop: 1500 } });
    fireEvent.click(screen.getByRole("button", { name: "Jump to message: message 99" }));

    expect(navigateTo).toHaveBeenCalledWith(8862);
  });

  it("expands the window start to avoid cutting an agent activity cluster", () => {
    const clustered = makeLongMessages(200);
    const boundary = clustered.length - INITIAL_HISTORY_WINDOW;
    clustered.splice(
      boundary - 2,
      3,
      {
        id: "r0",
        role: "assistant",
        content: "",
        reasoning: "first reasoning",
        createdAt: boundary - 2,
      },
      {
        id: "t0",
        role: "tool",
        kind: "trace",
        content: "tool()",
        traces: ["tool()"],
        createdAt: boundary - 1,
      },
      {
        id: "r1",
        role: "assistant",
        content: "",
        reasoning: "second reasoning",
        createdAt: boundary,
      },
    );

    const visible = windowMessages(clustered, INITIAL_HISTORY_WINDOW);

    expect(visible[0].id).toBe("r0");
    expect(visible).toHaveLength(INITIAL_HISTORY_WINDOW + 2);
  });

  it.each([false, true])("keeps an activity cluster together across an empty answer frame (streaming=%s)", (isStreaming) => {
    const activity: UIMessage[] = [
      { id: "prompt", role: "user", content: "question", createdAt: 1 },
      { id: "first", role: "tool", kind: "trace", content: "first()", createdAt: 2 },
      { id: "empty", role: "assistant", content: "", turnPhase: "answer", isStreaming, createdAt: 3 },
      { id: "second", role: "tool", kind: "trace", content: "second()", createdAt: 4 },
    ];
    expect(windowMessages(activity, 1).map((message) => message.id)).toEqual(["first", "empty", "second"]);
  });

  it("keeps compaction notices as activity window boundaries", () => {
    const activity: UIMessage[] = [
      { id: "first", role: "tool", kind: "trace", content: "first()", createdAt: 1 },
      { id: "compact", role: "assistant", kind: "compaction", content: "", compaction: { id: "compact", phase: "started" }, createdAt: 2 },
      { id: "second", role: "tool", kind: "trace", content: "second()", createdAt: 3 },
    ];
    expect(windowMessages(activity, 1).map((message) => message.id)).toEqual(["second"]);
  });

  it("resets to the bottom when opening a different conversation", async () => {
    const scrollTo = vi.fn();
    const { container, rerender } = render(
      <ThreadViewport
        messages={messages}
        isStreaming={false}
        composer={<div />}
        conversationKey="chat-a"
      />,
    );
    const scroller = getScroller(container);
    Object.defineProperties(scroller, {
      scrollHeight: { configurable: true, value: 2400 },
      clientHeight: { configurable: true, value: 600 },
      scrollTop: { configurable: true, writable: true, value: 0 },
      scrollTo: { configurable: true, value: scrollTo },
    });
    act(() => {
      dispatchUserScroll(scroller);
    });
    scrollTo.mockClear();

    rerender(
      <ThreadViewport
        messages={messages}
        isStreaming={false}
        composer={<div />}
        conversationKey="chat-b"
      />,
    );

    await waitFor(() => expect(scroller.scrollTop).toBe(1800));
  });

  it.each(["during animation", "after settlement"])("resets a submitted anchor when switching temporary conversations %s", (timing) => {
    const clock = controlAnimationFrames();
    const { container, rerender } = render(
      <ThreadViewport messages={submittedMessages} isStreaming temporary messagesKey="temporary-a" />,
    );
    const scroller = getScroller(container);
    mockScrollGeometry(scroller, 2_400, 600, 700);
    mockPromptPosition(scroller, container.querySelector<HTMLElement>('[data-user-prompt-id="u2"]')!, 420);
    rerender(
      <ThreadViewport messages={submittedMessages} isStreaming temporary messagesKey="temporary-a"
        activeTurnId="turn-2" submittedPromptTurnId="turn-2" />,
    );
    clock.frame(0);
    clock.frame(timing === "during animation" ? 80 : 300);

    rerender(<ThreadViewport messages={messages} isStreaming={false} temporary messagesKey="temporary-b" />);
    clock.frame(0);
    expect(scroller.scrollTop).toBe(1_800);
    clock.frame(300);
    expect(scroller.scrollTop).toBe(1_800);
  });

  it("pins an opened conversation to late layout growth without animating", async () => {
    const resizeObserver = stubResizeObserver();
    const jumpTo = vi.spyOn(ThreadCameraController.prototype, "jumpTo");

    try {
      const { container, rerender } = render(
        <ThreadViewport
          messages={messages}
          isStreaming={false}
          composer={<div />}
          conversationKey="chat-a"
        />,
      );
      const scroller = getScroller(container);
      Object.defineProperties(scroller, {
        scrollHeight: { configurable: true, value: 2400 },
        clientHeight: { configurable: true, value: 600 },
        scrollTop: { configurable: true, writable: true, value: 300 },
      });
      act(() => {
        dispatchUserScroll(scroller);
      });

      rerender(
        <ThreadViewport
          messages={messages}
          isStreaming={false}
          composer={<div />}
          conversationKey="chat-b"
        />,
      );
      await waitFor(() => expect(scroller.scrollTop).toBe(1800));
      jumpTo.mockClear();

      Object.defineProperty(scroller, "scrollHeight", {
        configurable: true,
        value: 3000,
      });
      resizeObserver.notify(scroller.firstElementChild!);
      await flushAnimationFrame();

      expect(jumpTo).toHaveBeenCalledWith(2400);
      expect(scroller.scrollTop).toBe(2400);
    } finally {
      jumpTo.mockRestore();
      resizeObserver.restore();
    }
  });

  it.each(["opening follow", "user takeover"] as const)(
    "settles a running conversation after the scrollport outgrows its frame with %s",
    (ownership) => {
      const clock = controlAnimationFrames();
      const resizeObserver = stubResizeObserver();
      try {
        const answer = { ...submittedAnswer, id: "running-answer", createdAt: 102, isStreaming: true };
        const running = [
          ...makePromptExchangeMessages(25),
          { ...submittedMessages[2], createdAt: 101 },
          answer,
        ];
        const viewport = (threadMessages: UIMessage[], key: string, ready = true) => (
          <ThreadViewport messages={threadMessages} conversationKey={key} conversationReady={ready}
            isStreaming={key === "running"} activeTurnId={key === "running" ? "turn-2" : null}
            composer={<div>composer</div>} />
        );
        const { container, rerender } = render(viewport(messages, "previous"));
        const scroller = getScroller(container);
        const frame = scroller.closest<HTMLElement>(".thread-viewport-frame")!;
        Object.defineProperty(frame, "clientHeight", { configurable: true, value: 600 });
        frame.getBoundingClientRect = () => DOMRect.fromRect({ width: 800, height: frame.clientHeight });
        scroller.getBoundingClientRect = () => DOMRect.fromRect({ width: 800, height: scroller.clientHeight });
        mockScrollGeometry(scroller, 2_400, 900, 300);
        rerender(viewport(messages, "running", false));
        rerender(viewport(running, "running"));
        expect(scroller.scrollTop).toBe(1_500);

        const notifyResize = () => resizeObserver.notify(scroller);
        // Output arrives before the grid has a usable scrollport height.
        mockScrollGeometry(scroller, 2_600, 900, scroller.scrollTop);
        rerender(viewport([...running.slice(0, -1), { ...answer, content: "more output" }], "running"));
        notifyResize();
        clock.frame(0);

        if (ownership === "user takeover") {
          fireEvent.wheel(scroller, { deltaY: -100 });
          scroller.scrollTop = 1_000;
          fireEvent.scroll(scroller);
        }
        mockScrollGeometry(scroller, 2_600, 600, scroller.scrollTop);
        notifyResize();
        clock.frame(0);
        const settledTop = ownership === "opening follow" ? 2_000 : 1_000;
        expect(scroller.scrollTop).toBe(settledTop);

        mockScrollGeometry(scroller, 3_000, 600, scroller.scrollTop);
        rerender(viewport([...running.slice(0, -1), { ...answer, content: "even more output" }], "running"));
        notifyResize();
        clock.frame(0);
        expect(scroller.scrollTop).toBe(settledTop);
      } finally {
        resizeObserver.restore();
      }
    },
  );

  it("animates the bottom button target and pins later layout growth", async () => {
    const resizeObserver = stubResizeObserver();
    const navigateLatestTo = vi.spyOn(
      ThreadMotionCoordinator.prototype,
      "navigateLatestTo",
    );
    const jumpTo = vi.spyOn(ThreadCameraController.prototype, "jumpTo");

    try {
      const { container } = render(
        <ThreadViewport
          messages={messages}
          isStreaming={false}
          composer={<div />}
          conversationKey="chat-a"
        />,
      );
      const scroller = getScroller(container);
      Object.defineProperties(scroller, {
        scrollHeight: { configurable: true, value: 2400 },
        clientHeight: { configurable: true, value: 600 },
        scrollTop: { configurable: true, writable: true, value: 300 },
      });
      mockMessageEnd(scroller);
      act(() => {
        dispatchUserScroll(scroller);
      });

      navigateLatestTo.mockClear();
      jumpTo.mockClear();
      fireEvent.click(screen.getByRole("button", { name: "Scroll to bottom" }));
      expect(navigateLatestTo).toHaveBeenCalledWith(1800);
      expect(scroller.scrollTop).toBe(300);

      const messageRegion = screen.getByTestId("thread-message-region");
      const messageContent = messageRegion.firstElementChild;
      expect(messageContent).not.toBeNull();
      const contentObserver = resizeObserver.observers.find(
        (observer) => observer.elements.includes(messageContent!),
      );
      expect(contentObserver).toBeDefined();

      Object.defineProperty(scroller, "scrollHeight", {
        configurable: true,
        value: 3000,
      });
      act(() => {
        contentObserver!.callback([], contentObserver!);
      });
      await waitFor(() => expect(scroller.scrollTop).toBe(2400));

      expect(jumpTo).not.toHaveBeenCalled();

      act(() => {
        scroller.dispatchEvent(new Event("scroll"));
      });
      await flushAnimationFrame();
      jumpTo.mockClear();

      Object.defineProperty(scroller, "scrollHeight", {
        configurable: true,
        value: 3400,
      });
      act(() => {
        contentObserver!.callback([], contentObserver!);
      });
      await flushAnimationFrame();

      expect(jumpTo).toHaveBeenCalledWith(2800);
      expect(scroller.scrollTop).toBe(2800);
    } finally {
      navigateLatestTo.mockRestore();
      jumpTo.mockRestore();
      resizeObserver.restore();
    }
  });

  it("waits for the next conversation's transcript before restoring its bottom", async () => {
    const jumpTo = vi.spyOn(ThreadCameraController.prototype, "jumpTo");
    const handoffAnimation = {
      cancel: vi.fn(),
      oncancel: null,
      onfinish: null,
    } as unknown as Animation;
    const animate = vi.fn(() => handoffAnimation);
    const oldMessages: UIMessage[] = [
      {
        id: "old-user",
        role: "user",
        content: "old question",
        turnId: "old-turn",
        createdAt: 1,
      },
    ];
    const nextMessages: UIMessage[] = [
      {
        id: "next-user",
        role: "user",
        content: "next question",
        turnId: "next-turn",
        createdAt: 2,
      },
      {
        id: "next-answer",
        role: "assistant",
        content: "next answer",
        turnId: "next-turn",
        createdAt: 3,
      },
    ];
    const { container, rerender } = render(
      <ThreadViewport
        messages={oldMessages}
        isStreaming
        composer={<div />}
        conversationKey="chat-a"
        activeTurnId="old-turn"
      />,
    );
    const scroller = getScroller(container);
    Object.defineProperties(scroller, {
      scrollHeight: { configurable: true, value: 2400 },
      clientHeight: { configurable: true, value: 600 },
      scrollTop: { configurable: true, writable: true, value: 300 },
      animate: { configurable: true, value: animate },
    });
    jumpTo.mockClear();

    rerender(
      <ThreadViewport
        messages={oldMessages}
        isStreaming
        composer={<div />}
        conversationKey="chat-b"
        activeTurnId="old-turn"
        conversationReady={false}
      />,
    );
    expect(scroller.scrollTop).toBe(300);
    expect(jumpTo).not.toHaveBeenCalled();
    expect(animate).toHaveBeenCalledWith(
      [{ opacity: 1 }, { opacity: 0.82 }],
      {
        duration: 80,
        easing: "cubic-bezier(0.2, 0, 0, 1)",
        fill: "forwards",
      },
    );

    Object.defineProperty(scroller, "scrollHeight", {
      configurable: true,
      value: 3000,
    });
    rerender(
      <ThreadViewport
        messages={nextMessages}
        isStreaming
        composer={<div />}
        conversationKey="chat-b"
        activeTurnId="next-turn"
        conversationReady
      />,
    );

    await waitFor(() => expect(scroller.scrollTop).toBe(2400));
    await flushAnimationFrame();
    expect(jumpTo.mock.calls).toEqual([[2400]]);
    expect(scroller.scrollTop).toBe(2400);
    expect(handoffAnimation.cancel).toHaveBeenCalled();
    expect(animate).toHaveBeenCalledWith(
      [{ opacity: 0.82 }, { opacity: 1 }],
      {
        duration: 140,
        easing: "cubic-bezier(0.2, 0, 0, 1)",
      },
    );
    expect(jumpTo.mock.invocationCallOrder[0]).toBeLessThan(
      animate.mock.invocationCallOrder[1],
    );
  });

  it("waits for hydrated messages before fulfilling open-chat bottom scroll", async () => {
    const jumpTo = vi.spyOn(ThreadCameraController.prototype, "jumpTo");
    const scrollTo = vi.fn();
    const { container, rerender } = render(
      <ThreadViewport
        messages={emptyMessages}
        isStreaming={false}
        composer={<div />}
        conversationKey={null}
      />,
    );
    const scroller = getScroller(container);
    Object.defineProperties(scroller, {
      scrollHeight: { configurable: true, value: 0 },
      clientHeight: { configurable: true, value: 600 },
      scrollTop: { configurable: true, writable: true, value: 0 },
      scrollTo: { configurable: true, value: scrollTo },
    });
    scrollTo.mockClear();
    jumpTo.mockClear();

    rerender(
      <ThreadViewport
        messages={emptyMessages}
        isStreaming={false}
        composer={<div />}
        conversationKey="chat-a"
      />,
    );
    expect(jumpTo).toHaveBeenCalledWith(0);

    rerender(
      <ThreadViewport
        messages={messages}
        isStreaming={false}
        composer={<div />}
        conversationKey="chat-a"
        conversationReady={false}
      />,
    );
    const hydratedScroller = getScroller(container);
    Object.defineProperties(hydratedScroller, {
      scrollHeight: { configurable: true, value: 2400 },
      clientHeight: { configurable: true, value: 600 },
      scrollTop: { configurable: true, writable: true, value: 0 },
      scrollTo: { configurable: true, value: scrollTo },
    });
    scrollTo.mockClear();
    jumpTo.mockClear();

    rerender(
      <ThreadViewport
        messages={messages}
        isStreaming={false}
        composer={<div />}
        conversationKey="chat-a"
        conversationReady
      />,
    );

    await waitFor(() => expect(hydratedScroller.scrollTop).toBe(1800));
    expect(jumpTo).toHaveBeenCalledWith(1800);
  });

  it("scrolls to the bottom when explicitly signalled after send", async () => {
    const scrollTo = vi.fn();
    const { container, rerender } = render(
      <ThreadViewport
        messages={messages}
        isStreaming={false}
        composer={<div />}
        scrollToBottomSignal={0}
      />,
    );
    const scroller = getScroller(container);
    Object.defineProperties(scroller, {
      scrollHeight: { configurable: true, value: 2400 },
      clientHeight: { configurable: true, value: 600 },
      scrollTop: { configurable: true, writable: true, value: 0 },
      scrollTo: { configurable: true, value: scrollTo },
    });
    scrollTo.mockClear();

    rerender(
      <ThreadViewport
        messages={messages}
        isStreaming={false}
        composer={<div />}
        scrollToBottomSignal={1}
      />,
    );

    await waitFor(() => expect(scroller.scrollTop).toBe(1800));
  });
});
