import { useState } from "react";

import { CodeBlock } from "@/components/CodeBlock";
import { MarkdownText } from "@/components/MarkdownText";
import { ThemeProvider, useTheme } from "@/hooks/useTheme";

const preview = "<!--\n" + "preserve comment context 中文 😀\n".repeat(79) + "-->\n" + Array.from({ length: 520 }, (_, index) => `<p data-index="${index}">Line ${index} 😀 ${"wide-source ".repeat(12)}</p>`).join("\n");
const source = 'export const result = <span className="badge">中文 😀</span>;\n';
const markdown = `Before code.\n\n\`\`\`tsx\n${source}\`\`\`\n\nAfter code.`;

export function CodeHighlightingFixture() {
  const { theme, toggle } = useTheme();
  const [streaming, setStreaming] = useState(false);
  const [changed, setChanged] = useState(false);
  const [wrap, setWrap] = useState(false);
  const [showLarge, setShowLarge] = useState(false);
  return <ThemeProvider theme={theme}><main className="h-full overflow-auto p-4" data-testid="code-fixture-scroll">
    <button onClick={toggle}>Toggle theme</button>
    <button onClick={() => setStreaming(true)}>Start streaming</button>
    <button onClick={() => setStreaming(false)}>Finish streaming</button>
    <button onClick={() => setChanged(true)}>Change source</button>
    <button onClick={() => setWrap(value => !value)}>Toggle wrapping</button>
    <button onClick={() => setShowLarge(true)}>Show large code</button>
    {showLarge ? <section aria-label="Large code"><CodeBlock language="typescript" code={Array.from({ length: 1200 }, (_, index) => `const value${index} = ${index};`).join("\n")} showLineNumbers /></section> : null}
    <section aria-label="Markdown"><MarkdownText streaming={streaming}>{streaming ? markdown.slice(0, markdown.indexOf("中文")) : markdown}</MarkdownText></section>
    <section aria-label="TypeScript"><CodeBlock language="tsx" code={changed ? source.replace("result", "updated") : source} showLineNumbers /></section>
    <section aria-label="INI"><CodeBlock language="ini" code={"; comment\n[server]\nhost=localhost\n"} /></section>
    <section aria-label="Unknown"><CodeBlock language="unknown-file-format" code={'<script>alert("not executable")</script>'} /></section>
    <section aria-label="ANSI"><CodeBlock language="ansi" code={'\x1b[32mPASS\x1b[0m <img src=x onerror="bad()">'} /></section>
    <section aria-label="File preview"><div data-file-preview-scroll className="code-content h-80 overflow-auto border">
      <CodeBlock language="html" code={preview} chrome="none" showLineNumbers wrapLongLines={wrap} viewportHighlight />
    </div></section>
  </main></ThemeProvider>;
}
