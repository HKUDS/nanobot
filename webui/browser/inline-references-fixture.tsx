import { useState } from "react";

import { MessageBubble } from "@/components/MessageBubble";
import { ThreadComposer } from "@/components/thread/ThreadComposer";
import { ThemeProvider, useTheme } from "@/hooks/useTheme";
import { useReadingTypography } from "@/hooks/useReadingTypography";
import type { ChatSummary, CliAppInfo, McpPresetInfo, SkillSummary, SlashCommand, UIMessage } from "@/lib/types";

const session: ChatSummary = {
  key: "websocket:typography", channel: "websocket", chatId: "typography",
  createdAt: null, updatedAt: null, title: "Reference target", preview: "",
  handle: { id: "handle_12345678901234567890123456789012", name: "typography" },
};
const longSession: ChatSummary = {
  ...session, key: "websocket:long-reference", chatId: "long-reference", title: "A longer conversation title",
  handle: { id: "handle_abcdefabcdefabcdefabcdefabcdefab", name: "mimamimamimamima" },
};
const logo = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20'%3E%3Crect width='20' height='20' fill='navy'/%3E%3C/svg%3E";
const cliApps: CliAppInfo[] = [{
  name: "drawio", display_name: "Draw.io", category: "diagram", description: "Diagram editor",
  requires: "", source: "fixture", entry_point: "drawio", install_supported: true,
  installed: true, available: true, status: "installed", skill_installed: true, logo_url: logo,
}];
const linearPreset: McpPresetInfo = {
  name: "linear", display_name: "Linear", category: "productivity", description: "Issue tracker",
  docs_url: "", transport: "streamableHttp", requires: "", note: "", install_supported: true,
  installed: true, configured: true, available: true, status: "configured", required_fields: [],
  connection_summary: "", logo_url: logo,
};
const mcpPresets = [linearPreset, { ...linearPreset, name: "adobe-express-docs", display_name: "Adobe Express Developer" }];
const commands: SlashCommand[] = [
  {
    command: "/goal", title: "Start a goal", description: "Start a sustained goal.",
    icon: "activity", lifecycle: "agent_turn_with_args", acceptsArgs: true,
  },
  {
    command: "/compact", title: "Compact context", description: "Compact context and continue chatting.",
    icon: "archive", lifecycle: "finalize_active_turn", acceptsArgs: false,
  },
  {
    command: "/model", title: "Model", description: "View or switch the current model preset.",
    icon: "brain", argHint: "[preset]", lifecycle: "side_channel", acceptsArgs: true,
  },
  {
    command: "/status", title: "Show status", description: "Check runtime, provider, and channel status.",
    icon: "activity", lifecycle: "side_channel", acceptsArgs: false,
  },
  {
    command: "/pairing", title: "Pairing", description: "Manage pairing requests.",
    icon: "shield", argHint: "[list|approve <code>|deny <code>|revoke <user_id>]",
    lifecycle: "side_channel", acceptsArgs: true,
  },
];
const skills: SkillSummary[] = [
  {
    name: "frontend-design",
    description: "Build polished interfaces with balanced typography, motion, and responsive layout across light and dark themes.",
    source: "workspace", enabled: true, available: true,
  },
  {
    name: "nanobot-document",
    description: "Look up nanobot configuration, architecture, and troubleshooting guides.",
    source: "builtin", enabled: true, available: true,
  },
  {
    name: "skill-creator",
    description: "Create or update reusable AgentSkills in the workspace.",
    source: "builtin", enabled: true, available: true,
  },
];
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
      <ThreadComposer compactWhenIdle sessions={[session, longSession]} cliApps={cliApps} mcpPresets={mcpPresets} modelLabel="Fixture" persistDraft={false} slashCommands={commands} skills={skills}
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
