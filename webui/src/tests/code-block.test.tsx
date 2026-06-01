import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CodeBlock } from "@/components/CodeBlock";
import { ThemeProvider } from "@/hooks/useTheme";

const mockedStyles = vi.hoisted(() => ({
  dark: { pre: { background: "#111" } },
  light: { pre: { background: "#fff" } },
}));

vi.mock("react-syntax-highlighter/dist/esm/prism-async-light", () => ({
  default: ({
    children,
    language,
    style,
  }: {
    children: string;
    language?: string;
    style: Record<string, unknown>;
  }) => (
    <pre
      data-testid="highlighted-code"
      data-language={language}
      data-theme={style === mockedStyles.dark ? "dark" : "light"}
    >
      <code>{children}</code>
    </pre>
  ),
}));

vi.mock("react-syntax-highlighter/dist/esm/styles/prism/one-dark", () => ({
  default: mockedStyles.dark,
}));

vi.mock("react-syntax-highlighter/dist/esm/styles/prism/one-light", () => ({
  default: mockedStyles.light,
}));

describe("CodeBlock", () => {
  it("renders plain code without mounting the highlighter when highlighting is disabled", () => {
    render(
      <ThemeProvider theme="dark">
        <CodeBlock language="ts" code="const value = 1;" highlight={false} />
      </ThemeProvider>,
    );

    expect(screen.queryByTestId("highlighted-code")).not.toBeInTheDocument();
    expect(screen.getByText("const value = 1;")).toBeInTheDocument();
    expect(screen.getByText("ts")).toBeInTheDocument();
    expect(screen.getByTestId("plain-code-fallback")).toHaveClass("text-foreground/90");
  });

  it("falls back to 'text' language when language is undefined", async () => {
    render(
      <ThemeProvider theme="dark">
        <CodeBlock language={undefined} code="const value = 1;" />
      </ThemeProvider>,
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByTestId("highlighted-code")).toBeInTheDocument();
    expect(screen.getByTestId("highlighted-code")).toHaveAttribute("data-language", "text");
    expect(screen.getByText("const value = 1;")).toBeInTheDocument();
  });

  it("reads theme from context without creating per-block observers", async () => {
    const originalMutationObserver = globalThis.MutationObserver;
    const observer = vi.fn();
    class MockMutationObserver {
      constructor(callback: MutationCallback) {
        observer(callback);
      }

      observe = vi.fn();

      disconnect = vi.fn();

      takeRecords() {
        return [];
      }
    }
    vi.stubGlobal("MutationObserver", MockMutationObserver);

    try {
      const { rerender } = render(
        <ThemeProvider theme="dark">
          <CodeBlock language="ts" code="const value = 1;" />
        </ThemeProvider>,
      );

      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(screen.getByTestId("highlighted-code")).toHaveAttribute(
        "data-theme",
        "dark",
      );

      rerender(
        <ThemeProvider theme="light">
          <CodeBlock language="ts" code="const value = 1;" />
        </ThemeProvider>,
      );

      await act(async () => {
        await Promise.resolve();
      });

      expect(screen.getByTestId("highlighted-code")).toHaveAttribute(
        "data-theme",
        "light",
      );
      expect(observer).not.toHaveBeenCalled();
    } finally {
      vi.stubGlobal("MutationObserver", originalMutationObserver);
    }
  });
});
