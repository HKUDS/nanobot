import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen, waitFor } from "@testing-library/react";
import { parse } from "postcss";
import { describe, expect, it } from "vitest";

import { DiffSyntaxHighlight } from "@/components/thread/activity/DiffSyntaxHighlight";
import { ThemeProvider } from "@/hooks/useTheme";

const globalStyles = parse(readFileSync(resolve(process.cwd(), "src/globals.css"), "utf8"));
// happy-dom does not apply cascade layers; retain the real rules and their order.
globalStyles.walkAtRules("layer", (layer) => {
  layer.replaceWith(...(layer.nodes ?? []));
});

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
          "td:last-child .token",
        );
        expect(tokens).not.toHaveLength(0);
        expect(highlighted.querySelector(".token.keyword")).not.toBeNull();
        expect(highlighted.querySelector(".token.string")).not.toBeNull();
      },
      { timeout: 10_000 },
    );

    expect(highlighted).toHaveAttribute("data-language", "tsx");
    expect(highlighted.querySelectorAll("tbody tr")).toHaveLength(4);
  });

  it.each(["light", "dark"] as const)(
    "preserves nested JSX token colors in the %s appearance",
    async (appearance) => {
      const { container } = render(
        <div className={appearance === "dark" ? "dark" : ""}>
          <style>{globalStyles.toString()}</style>
          <DiffSyntaxHighlight
            language="tsx"
            lines={[{
              kind: "add",
              old_lineno: null,
              new_lineno: 1,
              content: '<span className={enabled ? "yes" : "no"} onClick={() => save(new Event("ok"))}>ready</span>',
            }]}
          />
        </div>,
      );

      const highlighted = await screen.findByTestId(
        "syntax-highlighted-diff-hunk",
        {},
        { timeout: 10_000 },
      );
      await waitFor(() => {
        expect(highlighted.querySelector(".token.function")).not.toBeNull();
      }, { timeout: 10_000 });

      const colors = getComputedStyle(
        appearance === "dark" ? container.firstElementChild! : document.documentElement,
      );
      const tokens = [...highlighted.querySelectorAll<HTMLElement>(".token")];
      for (const [text, category, variable] of [
        ['"yes"', "string", "--code-string"],
        ["new", "keyword", "--code-keyword"],
        ["save", "function", "--code-function"],
        ["=>", "operator", "--code-function"],
        ["className", "attr-name", "--code-property"],
        ["span", "tag", "--code-property"],
      ]) {
        const token = tokens.find(
          (node) => node.textContent === text && node.classList.contains(category),
        );
        const expectedColor = colors.getPropertyValue(variable).trim();
        expect(token, `${category}: ${text}`).toBeDefined();
        expect(expectedColor).not.toBe("");
        expect.soft(getComputedStyle(token!).color, `${category}: ${text}`).toBe(expectedColor);
      }
    },
  );

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
