import { Profiler, useCallback, useState } from "react";
import { ThreadViewport } from "@/components/thread/ThreadViewport";
import { SubagentTasksProvider } from "@/components/thread/SubagentTasks";
import { useClient } from "@/providers/ClientProvider";
import { useSessionHistory } from "@/hooks/useSessions";
import { usePromptHistory } from "@/hooks/usePromptHistory";
import type { UIMessage } from "@/lib/types";

const localMessages: UIMessage[] = Array.from({ length: 280 }, (_, index) => ({
  id: `local-${index}`, role: index % 2 ? "assistant" : "user",
  content: `Cached message ${index}`, createdAt: index + 1,
}));

export function HistoryBoundaryFixture({ local = false, navigate = false, tasks = false }: { local?: boolean; navigate?: boolean; tasks?: boolean }) {
  const { client, token } = useClient();
  const preview = new URLSearchParams(location.search).get("preview");
  const [key, setKey] = useState("websocket:boundary-a");
  const history = useSessionHistory(local ? null : key);
  const messages = local ? localMessages : history.messages;
  const navigation = usePromptHistory(local ? null : key, history.version, messages);
  const [taskWindow, setTaskWindow] = useState<{ key: string; turnIds: string[] } | null>(null);
  const reportVisibleMessages = useCallback((visible: UIMessage[]) => {
    const turnIds = [...new Set(visible.flatMap(message => message.role === "user" && message.turnId ? [message.turnId] : []))];
    setTaskWindow(current => current?.key === key && current.turnIds.length === turnIds.length
      && current.turnIds.every((turnId, index) => turnId === turnIds[index]) ? current : { key, turnIds });
  }, [key]);
  return <main className="bg-background text-foreground" style={{ height: "100vh", display: "flex", flexDirection: "column" }}>
    <div className="flex min-h-10 shrink-0 flex-wrap items-center gap-4 px-4 py-2 text-sm">
      {preview ? <>
        <span className="text-muted-foreground">历史加载预览</span>
        {([["slow", "慢加载"], ["pages", "连续分页"], ["fast", "快速完成"], ["error", "失败重试"]] as const).map(([mode, label]) =>
          <a key={mode} href={`?case=history-boundary&preview=${mode}&lang=zh-CN`}
            className={preview === mode ? "font-medium underline underline-offset-4" : "text-muted-foreground"}>{label}</a>)}
      </> : <button onClick={() => setKey((current) => current.endsWith("-a") ? "websocket:boundary-b" : "websocket:boundary-a")}>Switch conversation</button>}
    </div>
    <Profiler id="history-boundary" onRender={(_, phase, actualDuration) => {
      window.dispatchEvent(new CustomEvent("history-boundary-render", { detail: { phase, actualDuration } }));
    }}>
    <SubagentTasksProvider client={client} token={token} sessionKey={key} enabled={tasks} liveEvents={false}
      turnIds={taskWindow?.key === key ? taskWindow.turnIds : []}
      windowReady={taskWindow?.key === key && (!history.loading || messages.length > 0)}>
    <ThreadViewport messages={messages} isStreaming={false} conversationKey={key}
      messagesKey={local ? key : history.messagesKey}
      conversationReady={local || history.messagesReady} hasMoreBefore={history.hasMoreBefore}
      onVisibleMessagesChange={tasks ? reportVisibleMessages : undefined}
      initialLoading={history.loading} initialError={history.error} onRetryInitial={history.refresh}
      loadingOlder={history.loadingOlder} olderError={history.olderError} onLoadOlder={history.loadOlder}
      navigation={navigate ? navigation : undefined} userMessageOffset={history.userMessageOffset}
      composer={<div className="border-t px-4 py-6 text-sm text-muted-foreground" style={{ height: 96 }}>
        {preview ? "滚到顶部后继续向上滚；触屏在顶部向下拉。仅使用示例消息，不连接真实会话。" : "History boundary fixture"}
      </div>} />
    </SubagentTasksProvider>
    </Profiler>
  </main>;
}
