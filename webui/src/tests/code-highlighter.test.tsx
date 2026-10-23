import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CodeTokens } from "@/components/CodeTokens";
import { codeHighlight } from "@/lib/code-highlighter";

async function lines(source: string, language: string) {
  const resource = codeHighlight(source, language);
  try { return resource.read(); } catch (pending) {
    if (!(pending instanceof Promise)) throw pending;
    await pending;
    return resource.read();
  }
}

describe("shared code highlighting", () => {
  it.each(["", "中文 😀\tconst x = 1;\n", "const a = 1;\r\n\tconst b = '中文';\r\n", "unterminated\r"])("preserves the complete source %j", async (source) => {
    const value = await lines(source, "typescript");
    expect(value.map(line => line.text).join("")).toBe(source);
    expect(value.flatMap(line => line.tokens).map(token => token.content).join("")).toBe(source);
  });

  it("tokenizes the complete large code block without pagination or dropping rows", async () => {
    const source = Array.from({ length: 1200 }, (_, index) => `const value${index} = ${index};`).join("\n");
    const value = await lines(source, "typescript");
    expect(value).toHaveLength(1200);
    expect(value.flatMap(line => line.tokens).map(token => token.content).join("")).toBe(source);
  });

  it("keeps multiline lexical context and produces the existing keyword/string palette", async () => {
    const value = await lines("/* start\ncomment\n*/\nexport const value = 'yes';", "typescript");
    expect(value[1].tokens.some(token => token.color === "var(--code-comment)" && token.fontStyle === 1)).toBe(true);
    expect(value[3].tokens.some(token => token.color === "var(--code-keyword)" && token.content.trim() === "export")).toBe(true);
    expect(value[3].tokens.some(token => token.color === "var(--code-string)" && token.content === "'yes'")).toBe(true);
  });

  it("retains INI syntax through the grammar backend instead of dropping configuration-file colors", async () => {
    const source = "; comment\n[server]\nhost=localhost\n";
    const value = await lines(source, "ini");
    expect(value.flatMap(line => line.tokens).map(token => token.content).join("")).toBe(source);
    expect(value[0].tokens.some(token => token.color === "var(--code-comment)")).toBe(true);
    expect(value[1].tokens.some(token => token.color === "var(--code-property)")).toBe(true);
  });

  it("keeps an unknown language readable and never turns source into active HTML", async () => {
    const source = "<script>alert('x')</script><img onerror='bad()'>";
    render(<pre data-testid="source"><CodeTokens lines={await lines(source, "unknown-file-format")} /></pre>);
    expect(screen.getByTestId("source").textContent).toBe(source);
    expect(document.querySelector("script, img")).toBeNull();
  });

  it("reuses source revisions but does not return stale text after an edit", async () => {
    const source = "export const value = 1;";
    expect(codeHighlight(source, "typescript")).toBe(codeHighlight(source, "typescript"));
    const changed = await lines(source.replace("1", "2"), "typescript");
    expect(changed.flatMap(line => line.tokens).map(token => token.content).join("")).toBe("export const value = 2;");
  });
});
