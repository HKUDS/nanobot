import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  type ReactNode,
} from "react";

import type { NanobotClient } from "@/lib/nanobot-client";
import type { WebUIIngressLimits } from "@/lib/types";
import { VersionCheckProvider } from "@/providers/VersionCheckProvider";
import { UpdateFlowProvider } from "@/providers/UpdateFlowProvider";

interface ClientContextValue {
  client: NanobotClient;
  token: string;
  getToken: () => string;
  modelName: string | null;
  ingressLimits: WebUIIngressLimits | null;
  webuiCapabilities: string[];
}

const ClientContext = createContext<ClientContextValue | null>(null);

export function ClientProvider({
  client,
  token,
  modelName = null,
  ingressLimits = null,
  webuiCapabilities = [],
  allowUpdateFlow = true,
  children,
}: {
  client: NanobotClient;
  token: string;
  modelName?: string | null;
  ingressLimits?: WebUIIngressLimits | null;
  webuiCapabilities?: string[];
  allowUpdateFlow?: boolean;
  children: ReactNode;
}) {
  const tokenRef = useRef(token);
  tokenRef.current = token;
  const getToken = useCallback(() => tokenRef.current, []);
  const value = useMemo(
    () => ({ client, token, getToken, modelName, ingressLimits, webuiCapabilities }),
    [client, getToken, ingressLimits, modelName, token, webuiCapabilities],
  );

  return (
    <ClientContext.Provider value={value}>
      <VersionCheckProvider token={token} client={client}
        channels={allowUpdateFlow && webuiCapabilities.includes("webui.update-channels.v1")}>
        <UpdateFlowProvider client={client} token={token} enabled={allowUpdateFlow && webuiCapabilities.includes("webui.update-flow.v1")}
          canSettleHandoff={webuiCapabilities.includes("webui.update-jobs.settle-handoff.v1")}>
          {children}
        </UpdateFlowProvider>
      </VersionCheckProvider>
    </ClientContext.Provider>
  );
}

export function useClient(): ClientContextValue {
  const ctx = useContext(ClientContext);
  if (!ctx) {
    throw new Error("useClient must be used within a ClientProvider");
  }
  return ctx;
}
