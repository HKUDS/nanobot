import { useState } from "react";

import { MessageBubble } from "@/components/MessageBubble";

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
  return <main className="mx-auto max-w-3xl space-y-4 p-4">
    <textarea aria-label="Code source" className="h-24 w-full font-mono text-code" value={code}
      onChange={event => setCode(event.target.value)} />
    <button onClick={() => setStreaming(false)}>Complete message</button>
    <MessageBubble message={{
      id: "wrapped-code", role: "assistant", createdAt: 1, isStreaming: streaming,
      content: `\`\`\`markdown\n${code}\n\`\`\``,
    }} />
  </main>;
}
