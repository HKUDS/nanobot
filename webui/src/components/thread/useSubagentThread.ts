import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { usePageVisibility } from "@/hooks/usePageVisibility";
import { fetchSubagentThread } from "@/lib/api";
import { projectWebuiThreadMessages } from "@/lib/thread-display-projection";
import { projectThreadEvents } from "@/lib/thread-event-projection";
import type { SubagentTaskSnapshot, UIMessage, WebuiThreadPersistedPayload } from "@/lib/types";

export function useSubagentThread({ token, sessionKey, task, historyEnabled }: {
  token: string;
  sessionKey: string;
  task: SubagentTaskSnapshot;
  historyEnabled: boolean;
}) {
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

  const retry = useCallback(() => refreshRef.current?.(), []);
  return { messages, failed, loading: historyEnabled && thread === null, activeTurnId: thread?.active_turn_id, retry };
}
