import { useEffect, useState } from "react";

import { MessageBubble } from "@/components/MessageBubble";
import { AppearanceSettingsView } from "@/components/settings/overview/AppearanceSettingsView";
import { ThreadComposer } from "@/components/thread/ThreadComposer";
import { DiffSyntaxHighlight } from "@/components/thread/activity/DiffSyntaxHighlight";
import { ThemeProvider, useTheme } from "@/hooks/useTheme";
import { useReadingTypography } from "@/hooks/useReadingTypography";
import { readLocalPreferences, writeLocalPreferences } from "@/lib/local-preferences";
import type { ChatSummary, UIMessage } from "@/lib/types";

const session: ChatSummary = {
  key: "websocket:typography", channel: "websocket", chatId: "typography",
  createdAt: null, updatedAt: null, title: "排版讨论 Typography", preview: "",
  handle: { id: "handle_12345678901234567890123456789012", name: "typography" },
};
const content = `# 阅读，让思路自然延续

排版应当帮助理解，而不是抢走注意力。中文与 English、API identifiers 混排时，也需要清楚的层级与自然的节奏。字号、行高和列宽一起决定阅读体验。

## 保留层级，减少干扰

普通正文使用稳定的字重，**重点内容保持清晰**。Inline code 如 \`readingTextSize\` 仍应与句子协调。A comfortable reading rhythm leaves enough room for the next thought, without making every line feel disconnected.

> 好的工具让人专注于内容。Reading is a conversation between the reader and the page.

### 可执行的检查清单

1. 即时切换字号，保留其他界面偏好。
2. 长段落和 long-unbroken-identifiers-without-spaces-abcdefghijklmnopqrstuvwxyz0123456789 可以换行。
3. 操作仍然可达，导航尺寸保持稳定。
   - 嵌套列表保留清楚的缩进。
   - 中文、English 与数字 12345 的组合。

- [x] 已完成的任务与正文一致
- [ ] 接下来确认视觉舒适度

| 内容角色 | 示例 | 设计意图 |
| --- | --- | --- |
| 正文 Body | 中文 English 混排 | 舒适、连续的阅读节奏 |
| 标题 Heading | 清楚的内容层级 | 保留结构，而非所有文字同大 |
| Code | configuration.readingTextSize | 完整显示，必要时在局部滚动 |

\`\`\`typescript
// 中文注释与 English code
const preference = { readingTextSize: "standard" };
function welcome(name: string) {
  return \`你好，\${name} — keep exploring.\`;
}
\`\`\`

#### 进一步阅读

The quick brown fox jumps over the lazy dog. 继续探索，保持好奇。

<details><summary>展开查看补充说明</summary>

这里的正文与折叠标题也应保持协调，不因字号变化发生裁切。

</details>
`;
const stressContent = `

## 长内容阅读 Long content

${Array.from({ length: 30 }, (_, index) => `${index + 1}. 第 ${index + 1} 项：中文与 English 混排的长列表内容，保持自然换行和清楚的编号。`).join("\n")}

\`\`\`typescript
const longIdentifier = "${"long-path-segment/".repeat(20)}";
${Array.from({ length: 80 }, (_, index) => `const item${index} = "第 ${index + 1} 行 — readable code";`).join("\n")}
\`\`\`
`;
const messages: UIMessage[] = [
  { id: "typography-user", role: "user", content: "请用中文与 English 解释这套排版，保持标题、引用和代码清楚。", createdAt: 1 },
  { id: "typography-answer", role: "assistant", content, createdAt: 2 },
];

export function TypographyFixture() {
  useReadingTypography();
  const { theme, toggle } = useTheme();
  const [preferences, setPreferences] = useState(readLocalPreferences);
  const [sent, setSent] = useState<UIMessage[]>([]);
  const previewMessages = new URLSearchParams(window.location.search).has("stress")
    ? messages.map((message) => message.role === "assistant" ? { ...message, content: content + stressContent } : message)
    : messages;
  useEffect(() => writeLocalPreferences(preferences), [preferences]);
  return <ThemeProvider theme={theme}>
    <main className="h-full overflow-y-auto">
      <div className="settings-grid mx-auto py-6">
        <AppearanceSettingsView theme={theme} onToggleTheme={toggle} localPrefs={preferences}
          onChangeLocalPrefs={setPreferences} />
      </div>
      <section className="mx-auto max-w-[var(--content-column-width)] space-y-6 px-4 pb-8" aria-label="Reading preview">
        {[...previewMessages, ...sent].map((message) => <MessageBubble key={message.id} message={message} />)}
        <div className="overflow-x-auto"><DiffSyntaxHighlight language="typescript" lines={[
          { kind: "delete", content: "const size = 16;", old_lineno: 1, new_lineno: null },
          { kind: "add", content: "const size = preferences.readingTextSize;", old_lineno: null, new_lineno: 1 },
        ]} /></div>
        <ThreadComposer compactWhenIdle sessions={[session]} modelLabel="Fixture" persistDraft={false} onSend={(text) => {
          setSent((current) => [...current, { id: `sent-${current.length}`, role: "user", content: text, createdAt: 3 + current.length }]);
        }} />
      </section>
    </main>
  </ThemeProvider>;
}
