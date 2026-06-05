import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MarkdownText } from "@/components/MarkdownText";

const rendererSpy = vi.hoisted(() => vi.fn());

vi.mock("@/components/MarkdownTextRenderer", () => ({
  default: ({
    children,
    highlightCode,
  }: {
    children: string;
    highlightCode?: boolean;
  }) => {
    rendererSpy({ children, highlightCode });
    return (
      <div
        data-testid="markdown-renderer"
        data-highlight-code={String(highlightCode)}
      >
        {children}
      </div>
    );
  },
}));

describe("MarkdownText", () => {
  it("throttles streaming markdown commits and flushes before final highlighting", async () => {
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
      expect(rendererSpy).toHaveBeenCalledTimes(1);

      rerender(<MarkdownText streaming>hello world</MarkdownText>);
      expect(screen.getByTestId("markdown-renderer")).toHaveTextContent("hello");
      expect(rendererSpy).toHaveBeenCalledTimes(1);

      act(() => {
        vi.advanceTimersByTime(79);
      });
      expect(screen.getByTestId("markdown-renderer")).toHaveTextContent("hello");
      expect(rendererSpy).toHaveBeenCalledTimes(1);

      act(() => {
        vi.advanceTimersByTime(1);
      });
      await act(async () => {
        await Promise.resolve();
      });

      expect(screen.getByTestId("markdown-renderer")).toHaveTextContent("hello world");
      expect(rendererSpy).toHaveBeenCalledTimes(2);

      rerender(<MarkdownText streaming>hello world!!!</MarkdownText>);
      expect(screen.getByTestId("markdown-renderer")).toHaveTextContent("hello world");

      rerender(<MarkdownText>hello world!!!</MarkdownText>);
      expect(screen.getByTestId("markdown-renderer")).toHaveTextContent("hello world!!!");
      expect(screen.getByTestId("markdown-renderer")).toHaveAttribute(
        "data-highlight-code",
        "true",
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps very large streaming snippets plain until the final render", async () => {
    rendererSpy.mockClear();
    const largeCode = `\`\`\`ts\n${"const value = 1;\n".repeat(1_100)}\`\`\``;

    const { rerender } = render(
      <MarkdownText streaming>{largeCode}</MarkdownText>,
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByTestId("markdown-renderer")).toHaveAttribute(
      "data-highlight-code",
      "false",
    );

    rerender(<MarkdownText>{largeCode}</MarkdownText>);

    expect(screen.getByTestId("markdown-renderer")).toHaveAttribute(
      "data-highlight-code",
      "true",
    );
  });
});
