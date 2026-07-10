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

    const highlighted = await screen.findByTestId("syntax-highlighted-diff-hunk");
    await waitFor(
      () => {
        expect(highlighted.querySelectorAll('td:last-child span[style*="color"]')).not.toHaveLength(
          0,
        );
      },
      { timeout: 10_000 },
    );

    expect(highlighted).toHaveAttribute("data-language", "tsx");
    expect(highlighted.querySelectorAll("tbody tr")).toHaveLength(4);
  });
});
