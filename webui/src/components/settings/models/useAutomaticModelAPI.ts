import { useEffect, useState } from "react";

import { fetchAutomaticModelAPI } from "@/lib/api";
import type { AutomaticModelAPIPayload, SettingsPayload } from "@/lib/types";

export function useAutomaticModelAPI({
  token, provider, model, reasoningEffort, providers, supported, editorOpen,
}: {
  token: string;
  provider: string;
  model: string;
  reasoningEffort: string;
  providers: SettingsPayload["providers"];
  supported: boolean;
  editorOpen: boolean;
}): AutomaticModelAPIPayload | null {
  const scope = JSON.stringify([token, provider, model, reasoningEffort, providers]);
  const [preview, setPreview] = useState<{
    scope: string;
    result: AutomaticModelAPIPayload;
  } | null>(null);

  useEffect(() => {
    if (!editorOpen || !supported || !model.trim()) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void fetchAutomaticModelAPI(token, provider, model, reasoningEffort)
        .then((result) => {
          if (!cancelled) setPreview({ scope, result });
        })
        .catch(() => {
          if (!cancelled) setPreview(null);
        });
    }, 150);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [editorOpen, supported, scope, token, provider, model, reasoningEffort]);

  return supported && preview?.scope === scope ? preview.result : null;
}
