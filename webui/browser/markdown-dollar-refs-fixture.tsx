import { useState } from "react";

import { MessageBubble } from "@/components/MessageBubble";
import dollarRefsFixture from "@/tests/fixtures/markdown-dollar-refs.md?raw";

const source = dollarRefsFixture.replaceAll("\r\n", "\n");
const codeStart = source.indexOf("`$defs`");
const ends = [codeStart + 1, codeStart + 2, codeStart + 4, codeStart + 7, source.length];
const precedenceExamples = [
  "**$ref** supports `$defs / definitions`.",
  "**$ref** in C:\\Users\\me uses `$defs`.",
  "A $x`$th`",
  "Explicit \\(f(`x')\\)th`code`.",
].join("\n\n");

export function MarkdownDollarRefsFixture() {
  const [step, setStep] = useState(0);
  const [streaming, setStreaming] = useState(true);
  return <main className="mx-auto max-w-3xl space-y-4 p-6">
    <nav className="flex gap-4">
      <button onClick={() => setStep((value) => Math.min(value + 1, ends.length - 1))}>Advance stream</button>
      <button onClick={() => setStreaming(false)}>Complete</button>
    </nav>
    <section aria-label="Reported assistant reply">
      <MessageBubble message={{ id: "reported", role: "assistant", content: source.slice(0, ends[step]), createdAt: 1, isStreaming: streaming }} />
    </section>
    <section aria-label="Inline formulas">
      <MessageBubble message={{ id: "math", role: "assistant", content: "The $n$th term: $\\text{`value`}$.", createdAt: 2 }} />
    </section>
    <section aria-label="Code and math precedence">
      <MessageBubble message={{ id: "precedence", role: "assistant", content: precedenceExamples, createdAt: 3, isStreaming: streaming }} />
    </section>
  </main>;
}
