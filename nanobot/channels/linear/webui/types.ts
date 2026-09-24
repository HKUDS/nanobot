export interface LinearInstallationSummary {
  organization_id: string;
  organization_name?: string;
  scopes?: string[];
  authorization_status?: "authorized" | "refresh_required" | "missing_scopes";
  missing_scopes?: string[];
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
