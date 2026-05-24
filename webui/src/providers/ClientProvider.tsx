import { createContext, useContext, type ReactNode } from "react";

import type { NanobotClient } from "@/lib/nanobot-client";
import type { SettingsPayload } from "@/lib/types";

export type ModelPresetInfo = SettingsPayload["model_presets"][number];

interface ClientContextValue {
  client: NanobotClient;
  token: string;
  modelName: string | null;
  modelPreset: string | null;
  modelPresets: ModelPresetInfo[];
}

const ClientContext = createContext<ClientContextValue | null>(null);

export function ClientProvider({
  client,
  token,
  modelName = null,
  modelPreset = null,
  modelPresets = [],
  children,
}: {
  client: NanobotClient;
  token: string;
  modelName?: string | null;
  modelPreset?: string | null;
  modelPresets?: ModelPresetInfo[];
  children: ReactNode;
}) {
  return (
    <ClientContext.Provider
      value={{ client, token, modelName, modelPreset, modelPresets }}
    >
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
