import { useEffect, useRef, useState } from "react";

import { usePageVisibility } from "@/hooks/usePageVisibility";
import { fetchSessionAutomations } from "@/lib/api";
import type { SessionAutomationJob } from "@/lib/types";

const AUTOMATIONS_REFRESH_MS = 3000;

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

  useEffect(() => {
    if (!open || !pageVisible) return;
    let cancelled = false;
    let refreshing = false;
    setSnapshot((current) => current.sessionKey === sessionKey
      ? { ...current, loadFailed: false }
      : { sessionKey, jobs: null, loadFailed: false });

    const refresh = async () => {
      if (refreshing) return;
      refreshing = true;
      try {
        const next = await fetchSessionAutomations(tokenRef.current, sessionKey);
        if (!cancelled) setSnapshot({ sessionKey, jobs: next.jobs, loadFailed: false });
      } catch {
        if (!cancelled) setSnapshot((current) => current.jobs !== null
          ? current : { sessionKey, jobs: null, loadFailed: true });
      } finally {
        refreshing = false;
      }
    };

    void refresh();
    const refreshId = window.setInterval(() => void refresh(), AUTOMATIONS_REFRESH_MS);
    const refreshOnFocus = () => void refresh();
    window.addEventListener("focus", refreshOnFocus);
    return () => {
      cancelled = true;
      window.clearInterval(refreshId);
      window.removeEventListener("focus", refreshOnFocus);
    };
  }, [open, pageVisible, sessionKey]);

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
