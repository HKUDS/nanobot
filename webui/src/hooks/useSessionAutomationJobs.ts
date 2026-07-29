import { useEffect, useState } from "react";

import { usePageVisibility } from "@/hooks/usePageVisibility";
import { fetchSessionAutomations } from "@/lib/api";
import type { SessionAutomationJob } from "@/lib/types";

const AUTOMATIONS_REFRESH_MS = 3000;

export function useSessionAutomationJobs(open: boolean, token: string, sessionKey: string) {
  const pageVisible = usePageVisibility();
  const [jobs, setJobs] = useState<SessionAutomationJob[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!open || !pageVisible) return;
    let cancelled = false;
    let loadedOnce = false;

    const refresh = async (showLoading = false) => {
      if (showLoading) {
        setLoading(true);
        setLoadFailed(false);
        setJobs([]);
      }
      try {
        const next = await fetchSessionAutomations(token, sessionKey);
        if (cancelled) return;
        setJobs(next.jobs);
        setLoadFailed(false);
        loadedOnce = true;
      } catch {
        if (!cancelled && !loadedOnce) setLoadFailed(true);
      } finally {
        if (!cancelled && showLoading) setLoading(false);
      }
    };

    void refresh(true);
    const refreshId = window.setInterval(() => void refresh(false), AUTOMATIONS_REFRESH_MS);
    const refreshOnFocus = () => void refresh(false);
    window.addEventListener("focus", refreshOnFocus);
    return () => {
      cancelled = true;
      window.clearInterval(refreshId);
      window.removeEventListener("focus", refreshOnFocus);
    };
  }, [open, pageVisible, sessionKey, token]);

  useEffect(() => {
    if (!open || !pageVisible) return;
    setNow(Date.now());
    const tickId = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(tickId);
  }, [open, pageVisible]);

  return { jobs, loading, loadFailed, now };
}
