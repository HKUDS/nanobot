import { useSyncExternalStore } from "react";

import { useClient } from "@/providers/ClientProvider";

import { linearMemberAccessStore } from "./member-access-store";
import { LinearMemberAccessView } from "./LinearMemberAccessView";

export function LinearMemberAccess({ organizationId, configScope = "", disabled = false }: {
  organizationId: string;
  configScope?: string;
  disabled?: boolean;
}) {
  const { client, token } = useClient();
  const store = linearMemberAccessStore(client, token, configScope, organizationId);
  const snapshot = useSyncExternalStore(store.subscribe, store.getSnapshot);
  return <LinearMemberAccessView snapshot={snapshot} disabled={disabled}
    onLoad={store.load} onSetAllowed={store.setAllowed} />;
}
