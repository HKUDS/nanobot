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

interface ClientContextValue {
  client: NanobotClient;
  token: string;
  getToken: () => string;
  modelName: string | null;
  ingressLimits: WebUIIngressLimits | null;
  webuiCapabilities: string[];
  onAccessPasswordChange?: (password: string) => void;
}

const ClientContext = createContext<ClientContextValue | null>(null);

export function ClientProvider({
  client,
  token,
  modelName = null,
  ingressLimits = null,
  webuiCapabilities = [],
  onAccessPasswordChange,
  children,
}: {
  client: NanobotClient;
  token: string;
  modelName?: string | null;
  ingressLimits?: WebUIIngressLimits | null;
  webuiCapabilities?: string[];
  onAccessPasswordChange?: (password: string) => void;
  children: ReactNode;
}) {
  const tokenRef = useRef(token);
  tokenRef.current = token;
  const getToken = useCallback(() => tokenRef.current, []);
  const value = useMemo(
    () => ({ client, token, getToken, modelName, ingressLimits, webuiCapabilities, onAccessPasswordChange }),
    [client, getToken, ingressLimits, modelName, token, webuiCapabilities, onAccessPasswordChange],
  );

  return (
    <ClientContext.Provider value={value}>
      {children}
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
