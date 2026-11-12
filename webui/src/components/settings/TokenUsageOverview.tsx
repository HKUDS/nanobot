import { useEffect, useMemo, useRef, useState } from "react";
import { TokenUsageCard } from "@/components/settings/TokenUsageCard";
import { usePageVisibility } from "@/hooks/usePageVisibility";
import { fetchSettingsUsage } from "@/lib/api";
import type { SettingsPayload } from "@/lib/types";
import { useClient } from "@/providers/ClientProvider";

type Usage = NonNullable<SettingsPayload["usage"]>;

export function TokenUsageOverview({ initialUsage, timeZone }: { initialUsage?: Usage; timeZone?: string }) {
  const { client, getToken } = useClient();
  const pageVisible = usePageVisibility();
  const [details, setDetails] = useState(false);
  const [usage, setUsage] = useState(initialUsage);
  const [modelsLoading, setModelsLoading] = useState(false);
  const cache = useMemo<{ overview?: Usage; models?: Usage }>(() => ({ overview: initialUsage }), [client, initialUsage, timeZone]);
  const previousDetails = useRef(false);

  useEffect(() => setUsage(cache.overview), [cache]);
  useEffect(() => {
    const closingDetails = previousDetails.current && !details;
    previousDetails.current = details;
    if (!pageVisible) return;
    if (details && cache.models) setUsage(cache.models);
    const controller = new AbortController();
    let refreshing = false;
    const refresh = async () => {
      if (refreshing) return;
      refreshing = true;
      const key = details ? "models" : "overview";
      if (details) setModelsLoading(!cache.models);
      try {
        const next = await fetchSettingsUsage(getToken(), { details, cached: cache[key], signal: controller.signal });
        if (!controller.signal.aborted) {
          cache[key] = next;
          setUsage(next);
        }
      } catch {
        // Keep the last telemetry snapshot during transient failures.
      } finally {
        if (!controller.signal.aborted) setModelsLoading(false);
        refreshing = false;
      }
    };
    if (!closingDetails) void refresh();
    const interval = window.setInterval(() => void refresh(), 5000);
    window.addEventListener("focus", refresh);
    return () => {
      controller.abort();
      window.clearInterval(interval);
      window.removeEventListener("focus", refresh);
    };
  }, [cache, details, getToken, pageVisible]);

  return <TokenUsageCard usage={usage} timeZone={timeZone} detailsLoading={modelsLoading} onDetailsOpenChange={setDetails} />;
}
