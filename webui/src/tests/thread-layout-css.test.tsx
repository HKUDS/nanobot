import { render, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import MarkdownTextRenderer from "@/components/MarkdownTextRenderer";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const css = readFileSync(resolve(process.cwd(), "src/globals.css"), "utf8");

// Structural guards complement the real-browser bounds/scroll regressions in
// assistant-rollout/visual/mobile-check.cjs; happy-dom does not perform layout.
function rulesFor(selector: string): string {
  return Array.from(css.replace(/\/\*[\s\S]*?\*\//g, "").matchAll(/([^{}]+)\{([^{}]*)\}/g))
    .filter((match) => match[1].trim().split(/,\s*/).includes(selector))
    .map((match) => match[2])
    .join("\n");
}

describe("thread layout containment", () => {
  it("does not undo intrinsic word wrapping through the word-wrap alias", () => {
    for (const selector of [".markdown-content", ".markdown-content a", ".markdown-content code"]) {
      const rules = rulesFor(selector);
      expect(rules).toContain("overflow-wrap: anywhere;");
      expect(rules).not.toContain("word-wrap: break-word;");
    }
  });

  it("keeps wide display math locally scrollable with its left edge reachable", async () => {
    const source = `$$\n${Array.from({ length: 25 }, () => "x^{2}").join(" + ")}\n$$`;
    const { container } = render(<MarkdownTextRenderer>{source}</MarkdownTextRenderer>);
    await waitFor(() => expect(container.querySelector(".markdown-content .katex-display > .katex")).not.toBeNull());
    const scrollport = rulesFor(".markdown-content .katex-display");
    expect(scrollport).toContain("max-width: 100%;");
    expect(scrollport).toContain("overflow-x: auto;");
    expect(scrollport).toContain("overscroll-behavior-x: contain;");
    const math = rulesFor(".markdown-content .katex-display > .katex");
    expect(math).toContain("width: max-content;");
    expect(math).toContain("min-width: 100%;");
  });
});
