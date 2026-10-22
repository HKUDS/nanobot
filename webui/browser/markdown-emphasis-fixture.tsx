import { useState } from "react";

import { MarkdownText } from "@/components/MarkdownText";

const source = [
  "**`ThreadTranscript` 已经朝这个方向走了一步：它把正文、来源覆盖和分页接纳集中起来，因此可以看作一个隐式的状态转换模型。**但“集中到一个类”不等于已经有清晰的状态机。",
  "前文**「重点」**后文。**参考 [说明](https://example.com) 的结论。**继续阅读。",
  "**日本語。**続き。**한국어(설명)**입니다。",
  "**中文。** 继续。**English.** Next.",
  "**边界说明： **issue",
].join("\n\n");

export function MarkdownEmphasisFixture() {
  const [end, setEnd] = useState(0);
  const [streaming, setStreaming] = useState(true);
  return <main className="mx-auto max-w-3xl p-6">
    <button onClick={() => setEnd((value) => Math.min(source.length, value + 1))}>Next character</button>
    <button onClick={() => { setEnd(source.length); setStreaming(false); }}>Complete</button>
    <div data-testid="reply"><MarkdownText streaming={streaming} preserveStreamingLayout>{source.slice(0, end)}</MarkdownText></div>
  </main>;
}
