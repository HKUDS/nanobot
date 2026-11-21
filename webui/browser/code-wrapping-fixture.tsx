import { lazy, Suspense, useState } from "react";

import { MessageBubble } from "@/components/MessageBubble";

// Keep this lazy: history-boundary tests hold the renderer request while the fixture loads.
const MarkdownTextRenderer = lazy(() => import("@/components/MarkdownTextRenderer"));

const outsideCode = `begin  \t${"word ".repeat(25)}end`;
const inlineSource = [
  `Before \`${"word ".repeat(23)}wordx\` after.`,
  `Before \`${"word ".repeat(24)}x\` after.`,
  `Spaces \`begin  \t${"word ".repeat(30)}end\` after.`,
  `Token \`${"x".repeat(180)}\` after.`,
  `CJK \`${"中文".repeat(70)}\` after.`,
  "Short `one  \ttwo` after.",
  `Link [\`${"x".repeat(180)}\`](https://example.com) after.`,
  `| Identifier | One | Two | Three | Four | Five |\n| --- | --- | --- | --- | --- | --- |\n| ${"identifier".repeat(4)} | \`default\` | \`release\` | \`private\` | \`enabled\` | \`compact\` |`,
  `\`\`\`text\n${"f".repeat(180)}\nsecond line\n\`\`\``,
  `    ${"i".repeat(180)}\n    indented line two`,
  `| Label | Code |\n| --- | --- |\n| Long | \`${outsideCode}\` |`,
  `## Heading \`${outsideCode}\``,
  `- List \`${outsideCode}\``,
].join("\n\n");

const source = [
  "# Environment",
  "",
  "- `ncode` 启动器在 `C:\\Users\\reader\\.config\\powershell\\profile.ps1`，使用 `uv run --project D:\\projects\\nanobot`；默认配置在 `C:\\Users\\reader\\.nanobot\\config.json`。",
  "- 缓存与工具链：npm cache `D:\\cache\\npm`，uv cache `D:\\cache\\uv`，Node/npm 在 `D:\\program\\nodejs`；WezTerm 桌面启动用 `wezterm-gui`。",
  "- 末行：中文与 English 仍保持连续排版。",
].join("\n");

export function CodeWrappingFixture() {
  const [code, setCode] = useState(source);
  const [streaming, setStreaming] = useState(true);
  const [inlineMessage, setInlineMessage] = useState("Before `");
  const [inlineStreaming, setInlineStreaming] = useState(true);
  return <main className="mx-auto max-w-3xl space-y-4 p-4">
    <textarea aria-label="Code source" className="h-24 w-full font-mono text-code" value={code}
      onChange={event => setCode(event.target.value)} />
    <button onClick={() => setStreaming(false)}>Complete message</button>
    <MessageBubble message={{
      id: "wrapped-code", role: "assistant", createdAt: 1, isStreaming: streaming,
      content: `\`\`\`markdown\n${code}\n\`\`\``,
    }} />
    <section data-testid="inline-code-wrapping">
      <Suspense fallback={null}>
        <MarkdownTextRenderer streaming={streaming} highlightCode={false}>{inlineSource}</MarkdownTextRenderer>
      </Suspense>
    </section>
    <textarea aria-label="Inline message source" value={inlineMessage}
      onChange={event => setInlineMessage(event.target.value)} />
    <button onClick={() => setInlineStreaming(false)}>Complete inline message</button>
    <section data-testid="inline-message-wrapping">
      <MessageBubble message={{
        id: "inline-code", role: "assistant", createdAt: 1, isStreaming: inlineStreaming,
        content: inlineMessage,
      }} />
    </section>
  </main>;
}
