import { useEffect, useState, type ReactNode } from "react";

import { AutomationChatBindingView, type AutomationChatNames, type ChangeAutomationChat } from "./AutomationChatBindingView";
import { fetchAutomationChats } from "@/lib/api";
import { readLocalPreferences } from "@/lib/local-preferences";
import type { AutomationChatsPayload, SessionAutomationJob } from "@/lib/types";

export type { AutomationChatNames, ChangeAutomationChat } from "./AutomationChatBindingView";

export function AutomationChatBinding({ job, token, chatNames, onSave, children }: {
  job: SessionAutomationJob; token: string; onSave: ChangeAutomationChat;
  chatNames?: AutomationChatNames;
  children: (picker: ReactNode) => ReactNode;
}) {
  const [data, setData] = useState<AutomationChatsPayload | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoadError(false);
    void fetchAutomationChats(token, job.id, controller.signal).then(value => {
      if (!controller.signal.aborted) setData(value);
    }).catch(() => { if (!controller.signal.aborted) setLoadError(true); });
    return () => controller.abort();
  }, [token, job.id, job.chat_binding_revision, reload]);
  return <AutomationChatBindingView job={job} data={data} loadError={loadError}
    chatNames={chatNames} showBrandLogos={readLocalPreferences().brandLogos} onSave={onSave}
    onReload={() => setReload(value => value + 1)} onSaved={target => {
      setData(previous => previous ? { ...previous, current: target } : previous);
      setReload(value => value + 1);
    }}>{children}</AutomationChatBindingView>;
}
