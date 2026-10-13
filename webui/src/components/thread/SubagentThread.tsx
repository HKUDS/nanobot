import { useEffect, useMemo, useRef, useState } from "react";
import { LoaderCircle } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ThreadMessages } from "@/components/thread/ThreadMessages";
import { Button } from "@/components/ui/button";
import { usePageVisibility } from "@/hooks/usePageVisibility";
import { fetchSubagentThread } from "@/lib/api";
import { projectWebuiThreadMessages } from "@/lib/thread-display-projection";
import { projectThreadEvents } from "@/lib/thread-event-projection";
import type { SubagentTaskSnapshot, UIMessage, WebuiThreadPersistedPayload } from "@/lib/types";

interface SubagentThreadProps {
  token: string;
  sessionKey: string;
  task: SubagentTaskSnapshot;
  historyEnabled: boolean;
  isStreaming: boolean;
}

export function SubagentThread({ token, sessionKey, task, historyEnabled, isStreaming }: SubagentThreadProps) {
  const { t } = useTranslation();
  const pageVisible = usePageVisibility();
  const [thread, setThread] = useState<WebuiThreadPersistedPayload | null>(null);
  const [failed, setFailed] = useState(false);
  const refreshRef = useRef<(() => void) | null>(null);
  const taskId = task.task_id;

  useEffect(() => {
    if (!historyEnabled || !pageVisible) return;
    let cancelled = false;
    let refreshing = false;
    let pending = false;
    const controller = new AbortController();
    const refresh = async () => {
      if (refreshing) { pending = true; return; }
      refreshing = true;
      try {
        const payload = await fetchSubagentThread(token, sessionKey, taskId, controller.signal);
        if (!cancelled) { setThread(payload); setFailed(false); }
      } catch {
        if (!cancelled) setFailed(true);
      } finally {
        refreshing = false;
        if (pending && !cancelled) { pending = false; void refresh(); }
      }
    };
    refreshRef.current = () => { void refresh(); };
    return () => { cancelled = true; refreshRef.current = null; controller.abort(); };
  }, [historyEnabled, pageVisible, sessionKey, taskId, token]);

  // Task revisions already arrive through the owning chat's event stream.
  useEffect(() => {
    refreshRef.current?.();
  }, [historyEnabled, pageVisible, sessionKey, taskId, task.revision, token]);

  const messages = useMemo(() => {
    if (historyEnabled) return thread ? projectWebuiThreadMessages(projectThreadEvents(thread.events)) : [];
    // Protocol 1 hosts without history still expose a task description and result.
    const summary: UIMessage[] = [{ id: `${taskId}-description`, role: "user", content: task.task_description, createdAt: task.created_at * 1000 }];
    if (task.result) summary.push({ id: `${taskId}-result`, role: "assistant", content: task.result,
      createdAt: (task.completed_at ?? task.created_at) * 1000 });
    return summary;
  }, [historyEnabled, taskId, task.task_description, task.created_at, task.completed_at, task.result, thread]);

  return <>
    {failed ? <div role="alert" className="mb-4 flex items-center gap-2 px-5 text-sm text-destructive">
      <span>{t("thread.history.error")}</span>
      <Button type="button" variant="ghost" size="sm" onClick={() => refreshRef.current?.()}>{t("thread.history.retry")}</Button>
    </div> : historyEnabled && thread === null ? <p role="status" className="flex items-center gap-2 px-5 text-sm text-muted-foreground">
      <LoaderCircle className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" aria-hidden />{t("chat.loading")}
    </p> : null}
    <ThreadMessages messages={messages} isStreaming={isStreaming} activeTurnId={thread?.active_turn_id}
      runStartedAt={task.created_at} />
  </>;
}
