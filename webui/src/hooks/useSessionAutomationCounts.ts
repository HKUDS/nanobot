import { useEffect, useRef, useState } from "react";

import { fetchAutomations } from "@/lib/api";

const EMPTY_COUNTS: ReadonlyMap<string, number> = new Map();

/**
 * Lightweight, pure-frontend lookup of bound automations per session key.
 * Uses the existing `/api/automations` endpoint so sessions with active schedules
 * are visibly protected from accidental cleanup without backend changes.
 */
export function useSessionAutomationCounts(
  getToken: () => string,
  sessionCount: number,
  enabled = true,
): ReadonlyMap<string, number> {
  const [counts, setCounts] = useState<ReadonlyMap<string, number>>(EMPTY_COUNTS);
  const inFlightRef = useRef(false);

  useEffect(() => {
    if (!enabled || sessionCount === 0) return;
    let cancelled = false;
    const load = async () => {
      if (inFlightRef.current) return;
      inFlightRef.current = true;
      try {
        const payload = await fetchAutomations(getToken());
        if (cancelled) return;
        const next = new Map<string, number>();
        for (const job of payload.jobs ?? []) {
          const sessionKey = job.origin?.session_key?.trim();
          if (!sessionKey) continue;
          next.set(sessionKey, (next.get(sessionKey) ?? 0) + 1);
        }
        setCounts(next);
      } catch {
        // Automations catalog is optional enrichment; never block session views.
      } finally {
        inFlightRef.current = false;
      }
    };
    const timer = window.setTimeout(() => {
      void load();
    }, 150);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [enabled, getToken, sessionCount]);

  return counts;
}
