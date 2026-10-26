import { useState } from "react";

import { MessageBubble } from "@/components/MessageBubble";
import { ThreadComposer } from "@/components/thread/ThreadComposer";
import { ThemeProvider, useTheme } from "@/hooks/useTheme";
import { useReadingTypography } from "@/hooks/useReadingTypography";
import type { ChatSummary, SlashCommand, UIMessage } from "@/lib/types";

const session: ChatSummary = {
  key: "websocket:typography", channel: "websocket", chatId: "typography",
  createdAt: null, updatedAt: null, title: "Reference target", preview: "",
  handle: { id: "handle_12345678901234567890123456789012", name: "typography" },
};
const commands: SlashCommand[] = [{
  command: "/goal", title: "Start a goal", description: "Start a sustained goal.",
  icon: "activity", lifecycle: "agent_turn_with_args", acceptsArgs: true,
}];
const answer: UIMessage = {
  id: "reference-answer", role: "assistant", createdAt: 1,
  content: "[相关会话](#session/websocket%3Atypography) · [外部文档](https://example.com/reference)",
};

export function InlineReferencesFixture() {
  useReadingTypography();
  const { theme } = useTheme();
  const [sent, setSent] = useState<UIMessage[]>([]);
  return <ThemeProvider theme={theme}>
    <main className="mx-auto h-full max-w-[var(--content-column-width)] space-y-6 overflow-y-auto p-4">
      {[answer, ...sent].map(message => <MessageBubble key={message.id} message={message} slashCommands={commands} />)}
      <ThreadComposer compactWhenIdle sessions={[session]} modelLabel="Fixture" persistDraft={false} slashCommands={commands}
        onSend={(text, _media, options) => setSent(current => [...current, {
          id: `sent-${current.length}`, role: "user", content: text, createdAt: current.length + 2,
        }, ...(options?.userShell ? [{
          id: `shell-${current.length}`, role: "assistant" as const, renderAs: "text" as const,
          content: "  __pycache__\n```mermaid\nflowchart LR\n```\n![preview](local.png)\n<b>raw</b>\n",
          createdAt: current.length + 3,
        }] : [])])} />
    </main>
  </ThemeProvider>;
}
