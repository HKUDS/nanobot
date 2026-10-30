import { createContext } from "react";

import type { HostAnchor, EmbeddedHost } from "./host-bridge";
import type { HostConnectionState } from "./remote-context";

export interface HostPicker {
  kind: "shell";
  name: string;
  hostname: string;
  localName: string;
  currentId: string | null;
  profiles: { id: string; name: string; host: string; state: HostConnectionState }[];
  recentIds: string[];
  pending: { id: string; name: string } | null;
  error: string;
  offline: boolean;
  offlineLabel?: string;
  select: (id: string | null) => void;
  manage: () => void;
  cancel: () => void;
  clearError: () => void;
  restoreFocus: () => void;
}
export interface EmbeddedPicker extends EmbeddedHost {
  kind: "embedded";
  open: (anchor: HostAnchor) => void;
}
export const HostNavigationContext = createContext<HostPicker | EmbeddedPicker | null>(null);
