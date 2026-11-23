import { useContext, useEffect, useState, type ComponentProps } from "react";

import { useClient } from "@/providers/ClientProvider";
import type { ConnectionStatus } from "@/lib/types";
import { HostNavigationContext } from "./host-navigation";
import { HostSwitcherView } from "./HostSwitcherView";

export { HostNavigationContext, type HostPicker } from "./host-navigation";
export { RemoteHostMenu } from "./HostSwitcherView";

export function HostSwitcher(props: Omit<ComponentProps<typeof HostSwitcherView>, "picker" | "status">) {
  const picker = useContext(HostNavigationContext);
  const { client } = useClient();
  const [status, setStatus] = useState<ConnectionStatus>(client.status);
  useEffect(() => client.onStatus(setStatus), [client]);
  return <HostSwitcherView {...props} picker={picker} status={status} />;
}
