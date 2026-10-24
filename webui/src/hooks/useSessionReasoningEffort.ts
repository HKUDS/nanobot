import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { fetchSessionReasoningEffort, setSessionReasoningEffort } from "@/lib/api";
import type { SessionReasoningEffort, SettingsPayload } from "@/lib/types";
import { useClient } from "@/providers/ClientProvider";

export function useSessionReasoningEffort({ sessionKey, preset, settings, open, disabled }: {
  sessionKey: string | null;
  preset: string;
  settings: SettingsPayload | null;
  open: boolean;
  disabled: boolean;
}) {
  const { client, getToken, token, webuiCapabilities } = useClient();
  const enabled = !disabled && webuiCapabilities.includes("webui.reasoning-effort.v1");
  const owner = useMemo(() => ({ client, sessionKey, preset, settings, token, enabled }),
    [client, sessionKey, preset, settings, token, enabled]);
  const currentOwner = useRef(owner);
  currentOwner.current = owner;
  const [snapshot, setSnapshot] = useState<{ owner: typeof owner; data: SessionReasoningEffort } | null>(null);
  const [operation, setOperation] = useState<{ owner: typeof owner; error: boolean; pending: boolean } | null>(null);
  const draft = useRef<{ owner: typeof owner; value: string | null; scope: string } | null>(null);
  const write = useRef<{ owner: typeof owner; settled: Promise<boolean> } | null>(null);
  const discovery = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!enabled || !open) return;
    const controller = new AbortController();
    discovery.current = controller;
    void fetchSessionReasoningEffort(getToken(), preset, sessionKey, controller.signal).then((data) => {
      if (controller.signal.aborted || write.current?.owner === owner) return;
      const choice = draft.current;
      setSnapshot({ owner, data: !sessionKey && choice?.owner === owner && choice.scope === data.scope
        ? { ...data, value: choice.value } : data });
    }).catch(() => {
      // Discovery is advisory: no reliable options means no quick control.
    });
    return () => controller.abort();
  }, [enabled, getToken, open, owner, preset, sessionKey]);

  const data = enabled && snapshot?.owner === owner ? snapshot.data : null;
  const select = useCallback(async (value: string | null) => {
    if (!data || currentOwner.current !== owner || write.current?.owner === owner) return;
    discovery.current?.abort();
    if (!sessionKey) {
      draft.current = { owner, value, scope: data.scope };
      setSnapshot({ owner, data: { ...data, value } });
      return;
    }
    const save = setSessionReasoningEffort(client, sessionKey, data, value);
    const request = { owner, settled: save.then(() => true, () => false) };
    write.current = request;
    setOperation({ owner, error: false, pending: true });
    try {
      const updated = await save;
      if (currentOwner.current === owner) {
        setSnapshot({ owner, data: updated });
        setOperation({ owner, error: false, pending: false });
      }
    } catch {
      if (currentOwner.current === owner) setOperation({ owner, error: true, pending: false });
    } finally {
      if (write.current === request) write.current = null;
    }
  }, [client, data, owner, sessionKey]);

  const persistDraft = useCallback(async (key: string) => {
    const choice = draft.current;
    if (!enabled || !data || choice?.owner !== owner || choice.value === null) return;
    await setSessionReasoningEffort(client, key, data, choice.value);
  }, [client, data, enabled, owner]);

  const settle = useCallback(() => {
    const request = write.current;
    if (request?.owner !== owner) return currentOwner.current === owner;
    return request.settled.then((saved) => saved && currentOwner.current === owner);
  }, [owner]);

  return {
    data,
    pending: operation?.owner === owner && operation.pending,
    error: operation?.owner === owner && operation.error,
    select,
    persistDraft,
    settle,
    enabled,
  };
}
