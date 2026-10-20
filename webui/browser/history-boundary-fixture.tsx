import { Profiler, useState } from "react";
import { ThreadViewport } from "@/components/thread/ThreadViewport";
import { useSessionHistory } from "@/hooks/useSessions";
import { usePromptHistory } from "@/hooks/usePromptHistory";
import type { UIMessage } from "@/lib/types";

const localMessages: UIMessage[] = Array.from({ length: 280 }, (_, index) => ({
  id: `local-${index}`, role: index % 2 ? "assistant" : "user",
  content: `Cached message ${index}`, createdAt: index + 1,
}));

export function HistoryBoundaryFixture({ local = false, navigate = false }: { local?: boolean; navigate?: boolean }) {
  const [key, setKey] = useState("websocket:boundary-a");
  const history = useSessionHistory(local ? null : key);
  const messages = local ? localMessages : history.messages;
  const navigation = usePromptHistory(local ? null : key, history.version, messages);
  return <main className="bg-background text-foreground" style={{ height: "100vh", display: "flex", flexDirection: "column" }}>
    <div className="flex h-10 shrink-0 items-center gap-4 px-4 text-sm">
      <button onClick={() => setKey((current) => current.endsWith("-a") ? "websocket:boundary-b" : "websocket:boundary-a")}>Switch conversation</button>
    </div>
    <Profiler id="history-boundary" onRender={(_, phase, actualDuration) => {
      window.dispatchEvent(new CustomEvent("history-boundary-render", { detail: { phase, actualDuration } }));
    }}>
    <ThreadViewport messages={messages} isStreaming={false} conversationKey={key}
      conversationReady={local || !history.loading} hasMoreBefore={history.hasMoreBefore}
      loadingOlder={history.loadingOlder} olderError={history.olderError} onLoadOlder={history.loadOlder}
      navigation={navigate ? navigation : undefined} userMessageOffset={history.userMessageOffset}
      composer={<div className="border-t px-4 py-6" style={{ height: 96 }}>History boundary fixture</div>} />
    </Profiler>
  </main>;
}
