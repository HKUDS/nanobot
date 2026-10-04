import { useEffect, type Dispatch, type SetStateAction } from "react";

import type { ApplySettingsPayload } from "@/components/settings/contracts";
import { providerFormFromRow } from "@/components/settings/models/ProviderSettings";
import type { ModelSettingsState } from "@/components/settings/models/useModelSettingsState";
import { cancelProviderOAuth, completeProviderOAuth } from "@/lib/api";
import type { NanobotClient } from "@/lib/nanobot-client";
import type {
  ProviderOAuthCompletionResult,
  ProviderOAuthPending,
  SettingsPayload,
} from "@/lib/types";

function isProviderOAuthPending(
  payload: ProviderOAuthCompletionResult,
): payload is ProviderOAuthPending {
  return (payload as ProviderOAuthPending).status === "pending";
}

interface ProviderOAuthPollingOptions {
  state: ModelSettingsState;
  client: NanobotClient;
  applyPayload: ApplySettingsPayload;
  setError: Dispatch<SetStateAction<string | null>>;
  closeProviderOAuthFlow: (cancelPending?: boolean) => void;
}

export function useProviderOAuthPolling({
  state,
  client,
  applyPayload,
  setError,
  closeProviderOAuthFlow,
}: ProviderOAuthPollingOptions) {
  const {
    providerOAuthFlow,
    providerOAuthFlowRef,
  } = state;

  useEffect(() => {
    if (!providerOAuthFlow) return;
    let cancelled = false;
    let timer: number | null = null;
    const poll = async () => {
      try {
        const payload = await completeProviderOAuth(
          client,
          providerOAuthFlow.provider,
          providerOAuthFlow.flow_id,
        );
        if (
          cancelled
          || providerOAuthFlowRef.current?.flow_id !== providerOAuthFlow.flow_id
        ) return;
        if (isProviderOAuthPending(payload)) {
          timer = window.setTimeout(() => void poll(), 1000);
          return;
        }
        applyPayload(payload, { preserveAgentForm: true });
        setError(null);
        closeProviderOAuthFlow(false);
      } catch (err) {
        if (
          cancelled
          || providerOAuthFlowRef.current?.flow_id !== providerOAuthFlow.flow_id
        ) return;
        setError((err as Error).message);
        closeProviderOAuthFlow();
      }
    };
    timer = window.setTimeout(() => void poll(), 1000);
    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
      if (providerOAuthFlow.completion_input === "device_code"
        && providerOAuthFlowRef.current?.flow_id === providerOAuthFlow.flow_id) {
        providerOAuthFlowRef.current = null;
        void cancelProviderOAuth(client, providerOAuthFlow.provider, providerOAuthFlow.flow_id)
          .catch(() => {});
      }
    };
  }, [applyPayload, client, closeProviderOAuthFlow, providerOAuthFlow]);
}

export function useProviderFormsSync(
  state: ModelSettingsState,
  settings: SettingsPayload | null,
) {
  const { setProviderForms } = state;

  useEffect(() => {
    if (!settings) return;
    setProviderForms((prev) => {
      const next = { ...prev };
      for (const provider of settings.providers) {
        next[provider.name] = next[provider.name] ?? providerFormFromRow(provider);
      }
      return next;
    });
  }, [settings]);
}
