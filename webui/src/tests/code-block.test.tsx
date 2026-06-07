import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

  it("can render without chat-style chrome for file previews", () => {
    render(
      <ThemeProvider theme="light">
        <CodeBlock
          language="html"
          code="<main />"
          chrome="none"
          highlight={false}
          showLineNumbers
        />
      </ThemeProvider>,
    );

    expect(screen.queryByText("html")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /copy/i })).not.toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByTestId("plain-code-fallback")).toHaveClass("bg-transparent");
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

  it("renders ANSI output without mounting the syntax highlighter", () => {
    render(
      <ThemeProvider theme="dark">
        <CodeBlock
          language="ansi"
          code={"\x1b[32mPASS\x1b[0m <script>alert(1)</script>"}
        />
      </ThemeProvider>,
    );

    expect(screen.queryByTestId("highlighted-code")).not.toBeInTheDocument();
    expect(screen.getByTestId("ansi-code")).toBeInTheDocument();
    expect(screen.getByTestId("ansi-code").closest(".not-prose")).toBeTruthy();
    expect(screen.getByText("ansi")).toBeInTheDocument();
    expect(screen.getByText("PASS")).toHaveStyle({ color: "#0dbc79" });
    expect(screen.getByText("<script>alert(1)</script>")).toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
  });

  it("detects ANSI sequences in regular code blocks", () => {
    render(
      <ThemeProvider theme="light">
        <CodeBlock
          language="text"
          code={"\x1b[38;2;35;209;139mtruecolor\x1b[0m"}
        />
      </ThemeProvider>,
    );

    expect(screen.queryByTestId("highlighted-code")).not.toBeInTheDocument();
    expect(screen.getByText("truecolor")).toHaveStyle({
      color: "rgb(35, 209, 139)",
    });
  });

  it("copies ANSI output as clean text", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    try {
      render(
        <ThemeProvider theme="dark">
          <CodeBlock language="ansi" code={"\x1b[32mPASS\x1b[0m"} />
        </ThemeProvider>,
      );

      await user.click(screen.getByRole("button", { name: /copy/i }));

      expect(writeText).toHaveBeenCalledWith("PASS");
    } finally {
      Reflect.deleteProperty(navigator, "clipboard");
    }
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
