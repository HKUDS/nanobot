import { useEffect, useRef, useState } from "react";

import { usePageVisibility } from "@/hooks/usePageVisibility";
import { useStateRefresh } from "@/hooks/useStateRefresh";
import { fetchSessionAutomations } from "@/lib/api";
import type { SessionAutomationJob } from "@/lib/types";

export function useSessionAutomationJobs(open: boolean, token: string, sessionKey: string) {
  const pageVisible = usePageVisibility();
  const [snapshot, setSnapshot] = useState<{
    sessionKey: string;
    jobs: SessionAutomationJob[] | null;
    loadFailed: boolean;
  }>({ sessionKey, jobs: null, loadFailed: false });
  const [now, setNow] = useState(() => Date.now());
  const tokenRef = useRef(token);
  tokenRef.current = token;

  useStateRefresh("automations", open, async (signal, initial) => {
    if (initial) setSnapshot((current) => current.sessionKey === sessionKey
      ? { ...current, loadFailed: false }
      : { sessionKey, jobs: null, loadFailed: false });
    try {
      const next = await fetchSessionAutomations(tokenRef.current, sessionKey, "", signal);
      if (!signal.aborted) setSnapshot({ sessionKey, jobs: next.jobs, loadFailed: false });
    } catch (error) {
      if (!signal.aborted) setSnapshot((current) => current.jobs !== null
        ? current : { sessionKey, jobs: null, loadFailed: true });
      throw error;
    }
  }, sessionKey);

  useEffect(() => {
    if (!open || !pageVisible) return;
    setNow(Date.now());
    const tickId = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(tickId);
  }, [open, pageVisible]);

  const current = snapshot.sessionKey === sessionKey ? snapshot : null;
  return {
    jobs: current?.jobs ?? [],
    loading: open && current?.jobs == null && !current?.loadFailed,
    loadFailed: current?.loadFailed ?? false,
    now,
  };
}
