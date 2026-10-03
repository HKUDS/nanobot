import { act, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { DiffSyntaxHighlight } from "@/components/thread/activity/DiffSyntaxHighlight";
import { ThemeProvider } from "@/hooks/useTheme";

vi.mock("react-syntax-highlighter/dist/esm/prism-async-light", () => {
  const MockSyntaxHighlighter = ({
    children,
    language,
    renderer,
    ...props
  }: {
    children: string;
    language: string;
    renderer: (args: {
      rows: Array<{
        type: "element";
        tagName: "span";
        properties: { className: string[] };
        children: Array<{ type: "text"; value: string }>;
      }>;
      stylesheet: Record<string, React.CSSProperties>;
      useInlineStyles: boolean;
    }) => ReactNode;
    [key: string]: unknown;
  }) => (
    <div data-testid={String(props["data-testid"])} data-language={language}>
      {renderer({
        rows: children.split("\n").map((line) => ({
          type: "element" as const,
          tagName: "span" as const,
          properties: { className: ["token", "keyword"] },
          children: [{ type: "text" as const, value: `${line}\n` }],
        })),
        stylesheet: {},
        useInlineStyles: true,
      })}
    </div>
  );
  return { default: MockSyntaxHighlighter };
});

vi.mock("react-syntax-highlighter/dist/esm/create-element", () => ({
  default: ({ node }: { node: { children?: Array<{ value?: string }> } }) => (
    <span data-testid="syntax-token">{node.children?.[0]?.value}</span>
  ),
}));

vi.mock("react-syntax-highlighter/dist/esm/styles/prism/one-dark", () => ({
  default: { dark: { color: "#fff" } },
}));

vi.mock("react-syntax-highlighter/dist/esm/styles/prism/one-light", () => ({
  default: { light: { color: "#111" } },
}));

describe("DiffSyntaxHighlight", () => {
  it("highlights a complete hunk while preserving diff rows and line numbers", async () => {
    render(
      <ThemeProvider theme="light">
        <DiffSyntaxHighlight
          language="typescript"
          lines={[
            { kind: "context", old_lineno: 4, new_lineno: 4, content: "export function run() {" },
            { kind: "delete", old_lineno: 5, new_lineno: null, content: "  return oldValue;" },
            { kind: "add", old_lineno: null, new_lineno: 5, content: "  return newValue;" },
          ]}
        />
      </ThemeProvider>,
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    const highlighted = await screen.findByTestId("syntax-highlighted-diff-hunk");
    expect(highlighted).toHaveAttribute("data-language", "typescript");
    expect(screen.getAllByTestId("syntax-token")).toHaveLength(3);
    expect(screen.getByText("return oldValue;", { exact: false }).closest("tr")).toHaveClass(
      "bg-rose-500/[0.09]",
    );
    expect(screen.getByText("return newValue;", { exact: false }).closest("tr")).toHaveClass(
      "bg-emerald-500/[0.09]",
    );
    expect(screen.getAllByText("5")).toHaveLength(2);
    expect(screen.getAllByTestId("syntax-token").some((node) => node.textContent?.endsWith("\n"))).toBe(false);
  });
});
