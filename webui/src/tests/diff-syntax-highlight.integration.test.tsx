import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DiffSyntaxHighlight } from "@/components/thread/activity/DiffSyntaxHighlight";
import { ThemeProvider } from "@/hooks/useTheme";

describe("DiffSyntaxHighlight with Prism", () => {
  it("loads the TSX grammar and renders styled syntax tokens", async () => {
    render(
      <ThemeProvider theme="light">
        <DiffSyntaxHighlight
          language="tsx"
          lines={[
            {
              kind: "context",
              old_lineno: 1,
              new_lineno: 1,
              content: 'import { useMemo } from "react";',
            },
            {
              kind: "delete",
              old_lineno: 2,
              new_lineno: null,
              content: "export function StatusBadge() {",
            },
            {
              kind: "add",
              old_lineno: null,
              new_lineno: 2,
              content: "export function StatusBadge(): JSX.Element {",
            },
            {
              kind: "context",
              old_lineno: 3,
              new_lineno: 3,
              content: '  return <span className="badge">ready</span>;',
            },
          ]}
        />
      </ThemeProvider>,
    );

    // Full-suite workers can keep the first Prism grammar import busy for more
    // than Testing Library's one-second default, especially on Windows.
    const highlighted = await screen.findByTestId(
      "syntax-highlighted-diff-hunk",
      {},
      { timeout: 10_000 },
    );
    await waitFor(
      () => {
        const tokens = highlighted.querySelectorAll<HTMLElement>(
          'td:last-child span[style*="color"]',
        );
        expect(tokens).not.toHaveLength(0);
        expect(new Set([...tokens].map((token) => token.style.color)).size).toBeGreaterThan(1);
      },
      { timeout: 10_000 },
    );

    expect(highlighted).toHaveAttribute("data-language", "tsx");
    expect(highlighted.querySelectorAll("tbody tr")).toHaveLength(4);
  });

  it("preserves markdown table line boundaries", async () => {
    const lines = [
      "## 发布安排",
      "",
      "| 日期 | 角色 | 方向 | 是否进实验 |",
      "| --- | --- | --- | --- |",
      "| 7/22 | trust / core | data-driven | yes |",
    ];

    render(
      <ThemeProvider theme="light">
        <DiffSyntaxHighlight
          language="markdown"
          lines={lines.map((content, index) => ({
            kind: "add" as const,
            old_lineno: null,
            new_lineno: 20 + index,
            content,
          }))}
        />
      </ThemeProvider>,
    );

    const highlighted = await screen.findByTestId(
      "syntax-highlighted-diff-hunk",
      {},
      { timeout: 10_000 },
    );
    const rows = [...highlighted.querySelectorAll("tbody tr")];

    expect(rows).toHaveLength(lines.length);
    expect(rows.map((row) => row.querySelector("td:last-child")?.textContent)).toEqual(
      lines.map((line) => line || " "),
    );
    expect(highlighted.querySelector(".token.table")).toBeNull();
  });
});
