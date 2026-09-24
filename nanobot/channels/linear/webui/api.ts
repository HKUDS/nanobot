import { startChannelConnect, type WebUIMutationTransport } from "@/lib/api";

import type { LinearWorkspacePayload } from "./types";

export function manageLinearWorkspace(
  transport: WebUIMutationTransport,
  params: { operation: "inspect" } | { operation: "disconnect"; organization_id: string },
): Promise<LinearWorkspacePayload> {
  return startChannelConnect<LinearWorkspacePayload>(transport, "linear", params);
}
