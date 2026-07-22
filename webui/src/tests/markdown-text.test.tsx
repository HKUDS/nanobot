import { useEffect } from "react";
import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MarkdownText } from "@/components/MarkdownText";

const rendererSpy = vi.hoisted(() => vi.fn());
const rendererMountSpy = vi.hoisted(() => vi.fn());
const rendererControl = vi.hoisted(() => ({ failStreaming: false }));

vi.mock("@/components/MarkdownTextRenderer", () => ({
  default: function MockMarkdownTextRenderer({
    children,
    highlightCode,
    streaming,
  }: {
    children: string;
    highlightCode?: boolean;
    streaming?: boolean;
  }) {
    useEffect(() => {
      rendererMountSpy();
    }, []);
    if (streaming && rendererControl.failStreaming) {
      throw new Error("incomplete streaming markdown");
    }
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
  it("recovers markdown rendering when a failed streaming response completes", async () => {
    rendererControl.failStreaming = true;
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const source = "## Final answer\n\nThis is **important**.";

    try {
      const { container, rerender } = render(
        <MarkdownText streaming>{source}</MarkdownText>,
      );

      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(container.querySelector(".streaming-text-fallback")?.textContent).toBe(source);

      rendererControl.failStreaming = false;
      rerender(<MarkdownText>{source}</MarkdownText>);

      expect(screen.getByTestId("markdown-renderer").textContent).toBe(source);
    } finally {
      rendererControl.failStreaming = false;
      consoleError.mockRestore();
    }
  });

  it("forwards every provider update without an extra UI timer", async () => {
    rendererSpy.mockClear();
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
      "false",
    );

    rerender(<MarkdownText streaming>hello world</MarkdownText>);
    expect(screen.getByTestId("markdown-renderer")).toHaveTextContent("hello world");

    rerender(<MarkdownText>hello world!!!</MarkdownText>);
    expect(screen.getByTestId("markdown-renderer")).toHaveTextContent("hello world!!!");
    expect(screen.getByTestId("markdown-renderer")).toHaveAttribute(
      "data-highlight-code",
      "true",
    );
  });

  it("keeps a healthy renderer mounted when streaming completes", async () => {
    rendererMountSpy.mockClear();
    const { rerender } = render(
      <MarkdownText streaming>hello</MarkdownText>,
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    rerender(<MarkdownText>hello world</MarkdownText>);

    expect(rendererMountSpy).toHaveBeenCalledTimes(1);
  });

  it("defers syntax highlighting until the final render", async () => {
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
