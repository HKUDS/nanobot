import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

describe("MarkdownText lazy renderer failure", () => {
  it("keeps rendering plain text if the markdown renderer chunk fails to load", async () => {
    vi.resetModules();
    vi.doMock("@/components/MarkdownTextRenderer", () => {
      throw new Error("markdown renderer failed to load");
    });
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

    try {
      const { MarkdownText } = await import("@/components/MarkdownText");

      render(<MarkdownText>hello **markdown**</MarkdownText>);

      await waitFor(() => {
        expect(screen.getByText("hello **markdown**")).toBeInTheDocument();
      });
    } finally {
      consoleError.mockRestore();
      vi.doUnmock("@/components/MarkdownTextRenderer");
    }
  });
});
