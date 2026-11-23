import { useState } from "react";

import { MessageBubble } from "@/components/MessageBubble";
import { DiagramScope } from "@/components/markdown-diagrams/context";
import { ThemeProvider, useTheme } from "@/hooks/useTheme";

export const diagramExamples = {
  flowchart: 'flowchart LR\nA[开始：接收用户请求] --> B{检查权限}\nB -->|允许| C[执行任务 ✅]\nB -->|拒绝| D[返回说明]',
  sequence: 'sequenceDiagram\nparticipant 用户\nparticipant 助手\n用户->>助手: 分析这个问题\n助手-->>用户: 返回结果 ✅',
  state: 'stateDiagram-v2\n[*] --> 等待\n等待 --> 处理中: 收到请求\n处理中 --> 完成: 成功\n完成 --> [*]',
  invalid: 'flowchart LR\nA[Unclosed',
};

export function DiagramFixture({ parameters }: { parameters: URLSearchParams }) {
  const { theme, toggle } = useTheme();
  const [streaming, setStreaming] = useState(parameters.has("stream"));
  const [identity, setIdentity] = useState("first");
  const [source, setSource] = useState(diagramExamples[parameters.get("type") as keyof typeof diagramExamples] ?? diagramExamples.flowchart);
  const examples = parameters.has("many")
    ? Array.from({ length: 12 }, (_, index) => `flowchart LR\nA[输入 ${index}] --> B[处理 ${index}] --> C[输出 ${index}]`)
    : parameters.has("multiple") ? Object.values(diagramExamples).slice(0, 3) : [source];
  const replies = parameters.has("many")
    ? [examples.map((example) => `\`\`\`mermaid\n${example}\n\`\`\``).join("\n\n")]
    : examples.map((example, index) => `A ${index + 1} diagram.\n\n\`\`\`mermaid\n${example}\n\`\`\`\n\nThe source stays available.`);
  return <ThemeProvider theme={theme}><main className="mx-auto max-w-3xl space-y-4 p-4 sm:p-6">
    <div className="flex flex-wrap gap-3">
      <button onClick={toggle}>Toggle theme</button>
      <button onClick={() => setStreaming(false)}>Complete message</button>
      <button onClick={() => { setIdentity((value) => value === "first" ? "second" : "first"); setSource(diagramExamples.state); }}>Switch conversation</button>
    </div>
    {parameters.has("edit") && <textarea aria-label="Diagram source" className="h-32 w-full border" value={source} onChange={(event) => setSource(event.target.value)} />}
    <DiagramScope identity={identity}>{replies.map((content, index) => <MessageBubble key={index} message={{
      id: `diagram-${index}`, role: "assistant", createdAt: index + 1, isStreaming: streaming,
      content,
    }} />)}</DiagramScope>
  </main></ThemeProvider>;
}
