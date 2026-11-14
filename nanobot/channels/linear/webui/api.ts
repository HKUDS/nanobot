import { startChannelConnect, type WebUIMutationTransport } from "@/lib/api";

import type { LinearMembersPayload, LinearWorkspacePayload, LinearWorkspaceProfile } from "./types";

export function getLinearWorkspaceProfile(
  transport: WebUIMutationTransport, organizationId: string,
): Promise<LinearWorkspaceProfile> {
  return startChannelConnect<LinearWorkspaceProfile>(transport, "linear", {
    operation: "workspace_profile", organization_id: organizationId,
  });
}

export function manageLinearWorkspace(
  transport: WebUIMutationTransport,
  params: { operation: "inspect" } | { operation: "disconnect"; organization_id: string },
): Promise<LinearWorkspacePayload> {
  return startChannelConnect<LinearWorkspacePayload>(transport, "linear", params);
}

export function manageLinearMembers(
  transport: WebUIMutationTransport,
  params: { operation: "members"; organization_id: string }
    | { operation: "member_access"; organization_id: string; user_id: string; allowed: boolean },
): Promise<LinearMembersPayload> {
  return startChannelConnect<LinearMembersPayload>(transport, "linear", params);
}
