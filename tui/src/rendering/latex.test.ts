import { describe, expect, test } from "bun:test"

import { renderLatexAsUnicode } from "./latex"

describe("terminal LaTeX rendering", () => {
  test("renders the cache-rate example as readable Unicode text", () => {
    expect(renderLatexAsUnicode([
      "实际公式是：",
      "",
      "\\[",
      "\\text{缓存率}=\\frac{\\text{cached input tokens}}{\\text{total input tokens}}",
      "\\]",
      "",
      "缓存命中：\\(66{,}000 \\times 94\\% \\approx 62{,}040\\) tokens",
    ].join("\n"))).toBe([
      "实际公式是：",
      "",
      "缓存率 = cached input tokens / total input tokens",
      "",
      "缓存命中：66,000 × 94% ≈ 62,040 tokens",
    ].join("\n"))
  })

  test("converts common symbols, scripts, roots, fractions, and accents", () => {
    const source = "$\\hat{f}(\\xi)=\\sum_{n=0}^{\\infty} \\frac{x^n}{n!}$ and \\(x_1=\\sqrt[3]{\\alpha+\\beta}\\)"

    expect(renderLatexAsUnicode(source)).toBe(
      "f̂(ξ) = ∑ₙ₌₀^(∞) xⁿ / n! and x₁ = ³√(α+β)",
    )
  })

  test("preserves precedence for compound fraction sides", () => {
    expect(renderLatexAsUnicode("\\(\\frac{a-b}{c} + \\frac{a}{b \\times c}\\)"))
      .toBe("(a-b) / c + a / (b × c)")
  })

  test("keeps currency and price ranges literal while converting guarded dollar math", () => {
    const source = [
      "Costs are $24 today or $10-20 later; variables $x$ and $2^n$ are math.",
      "Shipping costs $5+$10 and paths use $HOME/$USER.",
      "Mixed currency and variables like $5+$x$ remain literal.",
      "Commands and groups stay literal: $5+$\\alpha$, $5+${x}$, and $5+$(x)$.",
      "Matrix $A$ maps $V$ to $W$.",
    ].join("\n")

    expect(renderLatexAsUnicode(source)).toBe([
      "Costs are $24 today or $10-20 later; variables x and 2ⁿ are math.",
      "Shipping costs $5+$10 and paths use $HOME/$USER.",
      "Mixed currency and variables like $5+$x$ remain literal.",
      "Commands and groups stay literal: $5+$\\alpha$, $5+${x}$, and $5+$(x)$.",
      "Matrix A maps V to W.",
    ].join("\n"))
  })

  test("supports display dollars and aligned line breaks", () => {
    const source = "$$\\begin{aligned}a&=b+c\\\\d&\\le e\\end{aligned}$$"

    expect(renderLatexAsUnicode(source)).toBe("a = b+c\nd ≤ e")
  })

  test("leaves inline and fenced code unchanged", () => {
    const source = [
      "Inline `\\(x^2\\)` stays literal, but \\(y^2\\) renders.",
      "",
      "```tex",
      "\\[\\frac{a}{b}\\]",
      "```",
    ].join("\n")

    expect(renderLatexAsUnicode(source)).toBe([
      "Inline `\\(x^2\\)` stays literal, but y² renders.",
      "",
      "```tex",
      "\\[\\frac{a}{b}\\]",
      "```",
    ].join("\n"))
    expect(renderLatexAsUnicode("`$x$``")).toBe("`x``")
  })

  test("leaves fenced code inside block quotes and lists unchanged", () => {
    const source = [
      "> ~~~tex",
      "> $x^2$",
      "> ~~~",
      "",
      "- ```tex",
      "  \\(y_1\\)",
      "  ```",
      "",
      "1. item",
      "",
      "    ~~~tex",
      "    $z^2$",
      "    ~~~",
    ].join("\n")

    expect(renderLatexAsUnicode(source)).toBe(source)
  })

  test("leaves unmatched delimiters available during streaming", () => {
    expect(renderLatexAsUnicode("Working on \\(x^2")).toBe("Working on \\(x^2")
    expect(renderLatexAsUnicode("Working $$x$")).toBe("Working $$x$")
    expect(renderLatexAsUnicode("An escaped \\$5 stays literal.")).toBe("An escaped \\$5 stays literal.")
  })

  test("handles many unmatched openers without changing them", () => {
    const openers = "\\(".repeat(20_000)
    const backslashes = "\\".repeat(20_000)
    const backticks = `text ${"`".repeat(20_000)} then $x$`
    const descendingBackticks = "text " + Array.from(
      { length: 500 },
      (_, index) => "`".repeat(500 - index),
    ).join("x") + " $x$"
    const linkDestinations = `${"](".repeat(20_000)} then $x$`

    expect(renderLatexAsUnicode(openers)).toBe(openers)
    expect(renderLatexAsUnicode(backslashes)).toBe(backslashes)
    expect(renderLatexAsUnicode(backticks)).toBe(backticks.replace("$x$", "x"))
    expect(renderLatexAsUnicode(descendingBackticks))
      .toBe(descendingBackticks.replace("$x$", "x"))
    expect(renderLatexAsUnicode(linkDestinations)).toBe(linkDestinations.replace("$x$", "x"))
  })

  test("leaves unsupported, malformed, and deeply nested math unchanged", () => {
    const deep = `{`.repeat(100) + "x" + `}`.repeat(100)
    const source = [
      "$\\color{red}{x}$",
      "$\\frac{a}$",
      `\\(${deep}\\)`,
      "\\(\\displaystyle x^2\\)",
    ].join(" ")

    expect(renderLatexAsUnicode(source)).toBe([
      "$\\color{red}{x}$",
      "$\\frac{a}$",
      `\\(${deep}\\)`,
      "x²",
    ].join(" "))
  })

  test("does not rewrite Markdown link destinations or autolinks", () => {
    const source = [
      "[formula $x$](https://example.test/$x$/\\(raw\\))",
      "<https://example.test/$y$>",
      "bare https://example.test/$z$ remains intact",
      "<span title=\"$raw$\">HTML</span>",
      "if a < $x$ > b",
    ].join("\n")

    expect(renderLatexAsUnicode(source)).toBe([
      "[formula x](https://example.test/$x$/\\(raw\\))",
      "<https://example.test/$y$>",
      "bare https://example.test/$z$ remains intact",
      "<span title=\"$raw$\">HTML</span>",
      "if a < x > b",
    ].join("\n"))
  })
})
