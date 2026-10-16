import { createContext, useContext } from "react";

import type { RemoteDirectory } from "@/lib/remote-instances";
import type { HostAnchor } from "./host-bridge";

export type HostConnectionState = "open" | "closed" | "connecting" | "error";

export const RemoteContext = createContext<{
  available: boolean;
  localActive: boolean;
  activeHostId: string | null;
  hostStates: Record<string, HostConnectionState>;
  managing: boolean;
  embeddedManagement?: boolean;
  reportManagementSurface?: (rect: HostAnchor, theme: "light" | "dark") => void;
  closeManagement: () => void;
  selectLocal: () => void;
  openHostIds: string[];
  directory: RemoteDirectory | null;
  directoryError: boolean;
  refresh: () => Promise<RemoteDirectory>;
  rename: (id: string, name: string) => Promise<void>;
  connect: (id: string, stillWanted?: () => boolean) => Promise<void>;
  disconnect: (id: string) => Promise<void>;
  remove: (id: string) => Promise<void>;
  cancel: () => void;
} | null>(null);
export function useRemoteConnections() { return useContext(RemoteContext); }
