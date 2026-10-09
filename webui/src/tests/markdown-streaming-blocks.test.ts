import remarkMath from "remark-math";
import remarkParse from "remark-parse";
import remend from "remend";
import { parseMarkdownIntoBlocks } from "streamdown";
import { unified } from "unified";
import { describe, expect, it } from "vitest";

import { parseMathAwareMarkdownBlocks } from "@/lib/markdown-streaming-blocks";
import { remarkTexMath } from "@/lib/remark-tex-math";
import mixedMathFixture from "@/tests/fixtures/markdown-math-mixed.md?raw";

const mixedMath = mixedMathFixture.replaceAll("\r\n", "\n");

const formula = String.raw`\[
\tan\left(\frac{\mathrm{HFOV}}{2}\right)
=
\frac{X}{Z}

\]`;

function expectIntact(source: string, protectedSource: string) {
  const blocks = parseMathAwareMarkdownBlocks(source);
  expect(blocks.join("")).toBe(source);
  expect(blocks.some((block) => block.includes(protectedSource))).toBe(true);
  return blocks;
}

describe("math-aware streaming blocks", () => {
  it.each([
    [String.raw`\(\alpha+\beta=\gamma\)`, String.raw`\alpha+\beta=\gamma`],
    [String.raw`\(\nabla\cdot\vec{E}=\frac{\rho}{\varepsilon_0}\)`, String.raw`\nabla\cdot\vec{E}=\frac{\rho}{\varepsilon_0}`],
    [String.raw`\(a\\b\)`, String.raw`a\\b`],
    ["\\(a\n\\alpha\\)", "a\n\\alpha"],
  ])("retains inline TeX data beginning with commands: %s", (source, value) => {
    const parser = unified().use(remarkParse).use(remarkMath).use(remarkTexMath);
    const paragraph = parser.parse(source).children[0];
    expect(paragraph.type).toBe("paragraph");
    if (paragraph.type !== "paragraph") throw new Error("Expected a paragraph");
    expect(paragraph.children).toMatchObject([{ type: "inlineMath", value }]);
  });

  it("parses mixed math containers without creating empty inline-data tokens", () => {
    expect(parseMathAwareMarkdownBlocks(mixedMath).join("")).toBe(mixedMath);
  });

  it("accepts every repaired prefix of a mixed math response", () => {
    for (let end = 1; end <= mixedMath.length; end++) {
      const source = remend(mixedMath.slice(0, end), { htmlTags: false });
      expect(parseMathAwareMarkdownBlocks(source).join("")).toBe(source);
    }
  });

  it("merges a TeX formula split at a Setext equals line and blank lines", () => {
    const source = "Before\n\n" + formula + "\n\nAfter";
    expect(parseMarkdownIntoBlocks(source).some((block) => block.includes(formula))).toBe(false);
    const blocks = expectIntact(source, formula);
    expect(blocks[0]).toBe("Before");
    expect(blocks.at(-1)).toBe("After");
  });

  it("keeps every unfinished display-math prefix together without carrying state", () => {
    for (let end = 2; end <= formula.length; end++) {
      const partial = formula.slice(0, end);
      expectIntact("Before\n\n" + partial, partial);
    }
    expect(parseMathAwareMarkdownBlocks("Replacement\n\nPlain text")).toEqual(
      parseMarkdownIntoBlocks("Replacement\n\nPlain text"),
    );
  });

  it.each([
    String.raw`\[a
=
b\]`,
    "Before\n" + formula,
    String.raw`\(a + b\)`,
    "$$a\n=\nb\n\n$$",
    "$$$\na\n=\nb\n\n$$$",
  ])("keeps math intact with surrounding text and supported fences: %s", (math) => {
    expectIntact(math + "\n\nAfter", math);
  });

  it.each([
    formula.split("\n").map((line) => "> " + line).join("\n"),
    "- Item\n\n" + formula.split("\n").map((line) => "  " + line).join("\n"),
  ])("protects the enclosing container: %s", (container) => {
    expectIntact(container + "\n\nAfter", container);
  });

  it("does not consume text outside an unfinished blockquote formula", () => {
    const quoted = "> \\[\n> a\n> =\n> b";
    const blocks = expectIntact(quoted + "\n\nOutside\n\nNext", quoted);
    expect(blocks.at(-1)).toBe("Next");
    expect(blocks.some((block) => block.includes(quoted) && block.includes("Outside"))).toBe(false);
  });

  it.each([
    "", "First\n\n## Heading\n\nLast", "Prices: $20 and $30.\n\nNext",
    "```latex\n" + formula + "\n```\n\nAfter",
    formula.split("\n").map((line) => "    " + line).join("\n") + "\n\nAfter",
    "`" + formula + "`\n\nAfter",
    String.raw`\\[a
=
b\\]

After`,
    "$$a$$ trailing prose\n\nAfter",
    "[link][target]\n\nNext\n\n[target]: https://example.com",
    "<div>\n\nOrdinary HTML\n\n</div>\n\nAfter",
  ])("preserves default grouping when no math boundary needs repair: %s", (source) => {
    expect(parseMathAwareMarkdownBlocks(source)).toEqual(parseMarkdownIntoBlocks(source));
  });

  it("preserves CRLF source bytes rather than comparing normalized offsets", () => {
    const source = "Before\r\n\r\n" + formula.replaceAll("\n", "\r\n") + "\r\n\r\nAfter";
    expect(parseMathAwareMarkdownBlocks(source)).toEqual([source]);
  });

  it("does not enable unfinished formulas in the rendering grammar", () => {
    const source = String.raw`\[
a
=
b`;
    const strict = unified().use(remarkParse).use(remarkMath).use(remarkTexMath);
    const boundaries = unified().use(remarkParse).use(remarkMath)
      .use(remarkTexMath, { allowUnclosedFlow: true });
    expect(strict.parse(source).children.some((node) => node.type === "math")).toBe(false);
    expect(boundaries.parse(source).children.map((node) => node.type)).toEqual(["math"]);
  });
});
