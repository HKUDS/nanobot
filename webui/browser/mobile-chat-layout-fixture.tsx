import { useEffect, useState } from "react";
import { CalendarClock, ListFilter } from "lucide-react";
import { ThreadComposer } from "@/components/thread/ThreadComposer";
import { ThreadHeader } from "@/components/thread/ThreadHeader";
import { ThreadViewport } from "@/components/thread/ThreadViewport";
import { Button } from "@/components/ui/button";
import type { UIMessage, WorkspaceScopePayload, WorkspacesPayload } from "@/lib/types";

const messages: UIMessage[] = [
  { id: "layout-question-1", role: "user", content: "手机上的聊天布局，能不能再紧凑自然一些？", createdAt: 1_700_000_000_000 },
  { id: "layout-answer-1", role: "assistant", content: "可以。先把空间分给真正需要阅读的消息，再整理输入框附近的辅助信息。\n\n工作区、上下文用量和权限都很有用，但不需要各占一行；减少空白，也不等于缩小按钮的点击范围。", createdAt: 1_700_000_001_000 },
  { id: "layout-question-2", role: "user", content: "Context 出现时不要把输入框顶上去，顶部的文字也别切得那么生硬。", createdAt: 1_700_000_002_000 },
  { id: "layout-answer-2", role: "assistant", content: "这版保留熟悉的输入方式，只调整空间和边缘。\n\n**辅助信息合成一行**\n\n工作区在左，上下文用量与权限在右。手机上用圆环和百分比表示 Context，详细用量仍可点开查看。\n\n**把空间还给消息**\n\n输入框下方不再堆两层状态，底部只保留舒适的安全间距，按钮仍然容易点击。\n\n**顶部自然收边**\n\n靠近顶栏的内容轻轻淡出，不再突然截成半行；正文仍然可以自由滚动。", createdAt: 1_700_000_003_000 },
];
const initialScope: WorkspaceScopePayload = { project_path: "/projects/nanobot", project_name: "nanobot", access_mode: "full" };
const catalog: WorkspacesPayload = {
  schema_version: 1,
  default_access_mode: "full",
  default_scope: initialScope,
  recent_projects: [{ path: "/projects/nanobot", name: "nanobot" }],
  controls: { can_change_project: true },
};

export function MobileChatLayoutFixture({ parameters }: { parameters: URLSearchParams }) {
  const [dark, setDark] = useState(parameters.has("dark"));
  const [scope, setScope] = useState<WorkspaceScopePayload>(() => parameters.has("long-project")
    ? { ...initialScope, project_name: "nanobot-mobile-layout-preview" }
    : initialScope);
  useEffect(() => { document.documentElement.classList.toggle("dark", dark); }, [dark]);
  return (
    <main className="thread-workspace relative flex min-w-0 flex-col overflow-hidden bg-background" style={{ height: "100dvh" }}>
      <ThreadHeader title="Mobile layout preview" hideTitle theme={dark ? "dark" : "light"}
        onToggleSidebar={() => {}} onToggleTheme={() => setDark(value => !value)}
        sessionInfoAction={<Button variant="ghost" size="icon" aria-label="Session details"><CalendarClock className="h-3.5 w-3.5" /></Button>}
        promptNavigatorAction={<Button variant="ghost" size="icon" aria-label="Conversation navigation"><ListFilter className="h-3.5 w-3.5" /></Button>}
      />
      <ThreadViewport messages={messages} isStreaming={false} conversationReady conversationKey="websocket:mobile-layout-preview"
        hasMoreBefore={false} showScrollToBottomButton
        composer={<ThreadComposer variant="thread" onSend={() => {}}
          modelLabel="6.1-max" modelProvider="openai-codex" onTranscribeAudio={async () => ""}
          contextUsage={parameters.has("no-context") ? null : { contextTokens: 44_000, contextWindowTokens: 200_000 }}
          workspaceScope={scope} workspaceDefaultScope={initialScope} workspaceControls={catalog.controls}
          workspaceProjectLocked={!parameters.has("project")}
          onWorkspaceScopeChange={setScope} onLoadWorkspaceProjects={async () => catalog}
          onResolveWorkspaceProject={async path => ({ path, name: "nanobot" })}
          onFavoriteWorkspaceProject={async () => []}
          onBrowseWorkspaceDirectories={async path => ({ path, parent: null, entries: [], truncated: false, host: "preview", platform: "Linux" })}
        />}
      />
    </main>
  );
}
