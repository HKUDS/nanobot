export interface LinearInstallationSummary {
  organization_id: string;
  organization_name?: string;
  scopes?: string[];
  authorization_status?: "authorized" | "refresh_required" | "missing_scopes";
  missing_scopes?: string[];
}

export interface LinearWorkspaceProfile {
  organization_id: string;
  logo_url: string | null;
}

export interface LinearWorkspacePayload {
  session_id: string;
  status: "inspected" | "disconnected";
  message?: string;
  organization_id?: string;
  installations: LinearInstallationSummary[];
  webhook_url?: string;
  redirect_uri?: string;
}

export interface LinearMember {
  id: string;
  name: string;
  teams: string[];
  avatar_url?: string | null;
  allowed: boolean;
}

export interface LinearMembersPayload {
  session_id: string;
  status: "members" | "member_access_saved";
  organization_id: string;
  legacy_allow_all: boolean;
  members: LinearMember[];
}
