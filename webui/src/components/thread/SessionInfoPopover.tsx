import { useCallback, useState } from "react";

import type { AutomationAction } from "@/components/settings/system/AutomationsSettings";
import { SessionInfoPopoverView } from "@/components/thread/SessionInfoPopoverView";
import { useSessionAutomationJobs } from "@/hooks/useSessionAutomationJobs";
import { runAutomationAction, updateAutomation } from "@/lib/api";
import type { WebUIMutationTransport } from "@/lib/api";
import type { AutomationUpdatePayload, SessionAutomationJob } from "@/lib/types";

interface SessionInfoPopoverProps {
  client: WebUIMutationTransport;
  sessionKey: string;
  token: string;
  title: string;
}

export function SessionInfoPopover({ client, sessionKey, token, title }: SessionInfoPopoverProps) {
  const [surfacesOpen, setSurfacesOpen] = useState(false);
  const { jobs, loading, loadFailed, now } = useSessionAutomationJobs(surfacesOpen, token, sessionKey);
  const act = useCallback(async (action: AutomationAction, job: SessionAutomationJob) =>
    (await runAutomationAction(client, action, job.id)).jobs, [client]);
  const edit = useCallback(async (job: SessionAutomationJob, values: AutomationUpdatePayload) =>
    (await updateAutomation(client, job.id, values)).jobs, [client]);
  return <SessionInfoPopoverView title={title} jobs={jobs} loading={loading} loadFailed={loadFailed} now={now}
    onAction={act} onEdit={edit} onSurfacesOpenChange={setSurfacesOpen} calendarHref="#/automations" />;
}
