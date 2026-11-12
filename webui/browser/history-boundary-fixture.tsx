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
    <div className="flex h-10 shrink-0 items-center gap-4 px-4 text-sm">
      <button onClick={() => setKey((current) => current.endsWith("-a") ? "websocket:boundary-b" : "websocket:boundary-a")}>Switch conversation</button>
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
      composer={<div className="border-t px-4 py-6" style={{ height: 96 }}>History boundary fixture</div>} />
    </SubagentTasksProvider>
    </Profiler>
  </main>;
}
