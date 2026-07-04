import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MarkdownText } from "@/components/MarkdownText";
import { LOCAL_PREFS_STORAGE_KEY } from "@/lib/localPreferences";

const rendererSpy = vi.hoisted(() => vi.fn());

vi.mock("@/components/MarkdownTextRenderer", () => ({
  default: ({
    children,
    highlightCode,
    streamRevealFrom,
    streamVisibleUntil,
    streamRevealKey,
  }: {
    children: string;
    highlightCode?: boolean;
    streamRevealFrom?: number;
    streamVisibleUntil?: number;
    streamRevealKey?: number;
  }) => {
    rendererSpy({
      children,
      highlightCode,
      streamRevealFrom,
      streamVisibleUntil,
      streamRevealKey,
    });
    const revealFrom = typeof streamRevealFrom === "number"
      ? Math.max(0, Math.min(children.length, streamRevealFrom))
      : children.length;
    const visibleUntil = typeof streamVisibleUntil === "number"
      ? Math.max(0, Math.min(children.length, streamVisibleUntil))
      : children.length;
    const stableUntil = Math.min(revealFrom, visibleUntil);
    return (
      <div
        data-testid="markdown-renderer"
        data-highlight-code={String(highlightCode)}
      >
        {children.slice(0, stableUntil)}
        {stableUntil < visibleUntil ? (
          <span data-testid="streaming-reveal-segment">
            {children.slice(stableUntil, visibleUntil)}
          </span>
        ) : null}
      </div>
    );
  },
}));

async function advanceStreamingFrames(totalMs: number): Promise<void> {
  let elapsed = 0;
  while (elapsed < totalMs) {
    const step = Math.min(32, totalMs - elapsed);
    await act(async () => {
      vi.advanceTimersByTime(step);
      await Promise.resolve();
    });
    elapsed += step;
  }
}

function lastRendererCall() {
  return rendererSpy.mock.calls.at(-1)?.[0] as
    | {
      children: string;
      highlightCode?: boolean;
      streamRevealFrom?: number;
      streamVisibleUntil?: number;
      streamRevealKey?: number;
    }
    | undefined;
}

describe("MarkdownText", () => {
  afterEach(() => {
    window.localStorage.removeItem(LOCAL_PREFS_STORAGE_KEY);
  });

  it("keeps markdown rendering during streaming and reveals appended text", async () => {
    rendererSpy.mockClear();
    vi.useFakeTimers();
    try {
      const { rerender } = render(
        <MarkdownText streaming>hello</MarkdownText>,
      );

      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(screen.getByTestId("markdown-renderer")).toHaveTextContent("hello");
      expect(screen.getByTestId("markdown-renderer")).toHaveAttribute(
        "data-highlight-code",
        "true",
      );
      expect(rendererSpy).toHaveBeenLastCalledWith(
        expect.objectContaining({
          children: "hello",
          streamRevealFrom: 5,
          streamVisibleUntil: 5,
        }),
      );

      const full = "hello world, this sentence keeps streaming long enough for smooth reveal";
      rerender(
        <MarkdownText streaming>{full}</MarkdownText>,
      );
      expect(screen.getByTestId("markdown-renderer")).toHaveTextContent("hello");
      expect(rendererSpy).toHaveBeenLastCalledWith(
        expect.objectContaining({
          children: full,
          streamRevealFrom: 5,
          streamVisibleUntil: 5,
        }),
      );

      await advanceStreamingFrames(20);
      expect(rendererSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          children: full,
          streamVisibleUntil: expect.any(Number),
        }),
      );

      await advanceStreamingFrames(1_000);
      expect((screen.getByTestId("markdown-renderer").textContent ?? "").length).toBeGreaterThan(
        "hello".length,
      );
      expect(rendererSpy).toHaveBeenLastCalledWith(
        expect.objectContaining({
          children: full,
        }),
      );

      rerender(
        <MarkdownText streaming>{full}</MarkdownText>,
      );
      expect((screen.getByTestId("markdown-renderer").textContent ?? "").length).toBeGreaterThan(
        "hello".length,
      );

      rerender(
        <MarkdownText>{full}</MarkdownText>,
      );
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(screen.getByTestId("markdown-renderer")).toHaveTextContent(full);
      expect(screen.getByTestId("markdown-renderer")).toHaveAttribute(
        "data-highlight-code",
        "true",
      );
      expect(rendererSpy).toHaveBeenLastCalledWith(
        expect.objectContaining({ streamRevealFrom: undefined }),
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps very large streaming snippets rendered as markdown without live highlighting", async () => {
    rendererSpy.mockClear();
    const largeCode = `\`\`\`ts\n${"const value = 1;\n".repeat(1_100)}\`\`\``;

    const { rerender } = render(
      <MarkdownText streaming>{largeCode}</MarkdownText>,
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByTestId("markdown-renderer")).toHaveTextContent("const value = 1;");
    expect(screen.getByTestId("markdown-renderer")).toHaveAttribute(
      "data-highlight-code",
      "false",
    );

    rerender(<MarkdownText>{largeCode}</MarkdownText>);

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByTestId("markdown-renderer")).toHaveAttribute(
      "data-highlight-code",
      "true",
    );
  });

  it("starts revealing short unpunctuated streaming tails over animation frames", async () => {
    rendererSpy.mockClear();
    vi.useFakeTimers();
    try {
      const { rerender } = render(<MarkdownText streaming>hello</MarkdownText>);
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });

      rerender(<MarkdownText streaming>{"hello tiny"}</MarkdownText>);
      expect(screen.getByTestId("markdown-renderer")).toHaveTextContent("hello");
      expect(rendererSpy).toHaveBeenLastCalledWith(
        expect.objectContaining({
          children: "hello tiny",
          streamVisibleUntil: 5,
        }),
      );

      await advanceStreamingFrames(1_000);

      const visibleText = screen.getByTestId("markdown-renderer").textContent ?? "";
      expect(visibleText.length).toBeGreaterThan("hello".length);
      expect(rendererSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          children: "hello tiny",
          streamVisibleUntil: expect.any(Number),
        }),
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it("paces fast deltas without jumping over the unread backlog", async () => {
    rendererSpy.mockClear();
    vi.useFakeTimers();
    try {
      const { rerender } = render(<MarkdownText streaming>hello</MarkdownText>);
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });

      const full = `hello ${"fast delta ".repeat(80)}`;
      rerender(<MarkdownText streaming>{full}</MarkdownText>);
      expect(lastRendererCall()).toEqual(
        expect.objectContaining({
          children: full,
          streamVisibleUntil: 5,
        }),
      );

      await advanceStreamingFrames(96);

      const call = lastRendererCall();
      expect(call?.children).toBe(full);
      expect(call?.streamRevealFrom).toBeLessThan(50);
      expect(call?.streamVisibleUntil).toBeGreaterThan(call?.streamRevealFrom ?? 0);
      expect((call?.streamVisibleUntil ?? 0) - (call?.streamRevealFrom ?? 0)).toBeLessThanOrEqual(
        24,
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it("briefly pauses after punctuation before revealing the next phrase", async () => {
    rendererSpy.mockClear();
    vi.useFakeTimers();
    try {
      const { rerender } = render(<MarkdownText streaming>hello</MarkdownText>);
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });

      rerender(<MarkdownText streaming>{"hello, world"}</MarkdownText>);

      await advanceStreamingFrames(70);
      expect(screen.getByTestId("markdown-renderer")).toHaveTextContent("hello,");
      const pausedText = screen.getByTestId("markdown-renderer").textContent;

      await advanceStreamingFrames(32);
      expect(screen.getByTestId("markdown-renderer").textContent).toBe(pausedText);
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows streamed deltas immediately when natural pacing is disabled", async () => {
    rendererSpy.mockClear();
    window.localStorage.setItem(
      LOCAL_PREFS_STORAGE_KEY,
      JSON.stringify({ streamingNaturalPacing: false }),
    );
    const { rerender } = render(<MarkdownText streaming>hello</MarkdownText>);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    const full = `hello ${"fast delta ".repeat(40)}`.trimEnd();
    rerender(<MarkdownText streaming>{full}</MarkdownText>);
    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByTestId("markdown-renderer")).toHaveTextContent(full);
    expect(lastRendererCall()).toEqual(
      expect.objectContaining({
        children: full,
        streamRevealFrom: 5,
        streamVisibleUntil: full.length,
      }),
    );
  });
});
