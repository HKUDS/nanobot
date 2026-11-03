import { useContext, useEffect, useState } from "react";

import { useClient } from "@/providers/ClientProvider";
import type { ConnectionStatus } from "@/lib/types";
import { HostNavigationContext } from "./host-navigation";
import { HostSwitcherView } from "./HostSwitcherView";

export { HostNavigationContext, type HostPicker } from "./host-navigation";
export { RemoteHostMenu } from "./HostSwitcherView";

export function HostSwitcher({ collapsed = false, portalContainer }: { collapsed?: boolean; portalContainer?: HTMLElement | null }) {
  const picker = useContext(HostNavigationContext);
  const { client } = useClient();
  const [status, setStatus] = useState<ConnectionStatus>(client.status);
  useEffect(() => client.onStatus(setStatus), [client]);
  return <HostSwitcherView picker={picker} status={status} collapsed={collapsed} portalContainer={portalContainer} />;
}
