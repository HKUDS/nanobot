import type { WebUIMutationTransport } from "./api";
import { fetchWithTimeout } from "./http";

export interface HostCompatibility {
  status: "compatible" | "unknown" | "update_host" | "update_client";
  client_version: string;
  host_version: string;
}

export function isCompatibilityError(code: string): boolean {
  return ["webui_compatibility_unknown", "host_update_required", "client_update_required"].includes(code);
}

export interface RemoteProfile {
  id: string;
  name: string;
  host: string;
  port: number | null;
  ssh_config: string;
  identity_file: string;
  config_path: string;
  runtime_user: string;
  connected: boolean;
  gateway_id?: string;
  view_id?: string;
  connection_error?: string;
  paired?: boolean;
  /** Opaque grouping ID supplied only after the local backend verifies receipts. */
  instance_id?: string;
  revoke_command?: string;
  authorized_until?: number;
  compatibility?: HostCompatibility;
}

export interface RemoteProfileGroup {
  id: string;
  profile: RemoteProfile;
  connections: RemoteProfile[];
}

/** One visible instance; keep every underlying grant available in details. */
export function groupRemoteProfiles(profiles: RemoteProfile[], currentId: string | null): RemoteProfileGroup[] {
  const groups = new Map<string, RemoteProfile[]>();
  for (const profile of profiles) {
    const id = profile.instance_id || profile.id;
    const group = groups.get(id) || [];
    group.push(profile);
    groups.set(id, group);
  }
  return [...groups].map(([id, connections]) => {
    const preferred = connections.find((item) => item.id === currentId)
      || connections.find((item) => item.connected)
      || [...connections].reverse().find((item) => item.authorized_until != null && item.authorized_until * 1000 > Date.now())
      || connections[0];
    return { id, profile: { ...preferred, name: connections[0].name }, connections };
  });
}

/** Persistent setup problems need a repair path, not an endless Retry button. */
export function needsRemoteSetup(code: string): boolean {
  return isCompatibilityError(code) || /^(pair_|host_key_|ssh_auth_failed$|ssh_agent_refused$|ssh_key_permissions$|ssh_config_|local_file_not_found$|local_webui_unavailable$|remote_auth_failed$|incompatible_gateway$|webui_disabled$|profile_not_found$)/.test(code);
}

export interface RemoteDirectory {
  available: boolean;
  machine_name?: string;
  client_version?: string;
  profiles: RemoteProfile[];
}

export interface SSHDiscovery {
  hosts: { host: string; source: string; ssh_config: string }[];
  files: string[];
  incomplete: boolean;
}

export interface RemoteConnection {
  id: string;
  name: string;
  host: string;
  hostname: string;
  config_path: string;
  gateway_id: string;
  view_id?: string;
  url: string;
}

export interface RemoteLocation {
  config_path: string;
  runtime_user: string;
  service: string;
}

export interface RemoteInspection {
  hostname: string;
  candidates: RemoteLocation[];
  incomplete: boolean;
}

export async function readRemoteInstances(token: string): Promise<RemoteDirectory> {
  const response = await fetchWithTimeout("/api/remote-instances", {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (response.status === 403 || response.status === 404) return { available: false, profiles: [] };
  if (!response.ok) throw new Error("directory_unavailable");
  return response.json() as Promise<RemoteDirectory>;
}

export function remoteAction<T>(
  client: WebUIMutationTransport, action: string, payload: Record<string, unknown>,
): Promise<T> {
  return client.requestMutation<T>(`remote.${action}`, payload, action === "pick_file" ? 310_000 : 65_000);
}

/** Never let a server response navigate the shell to an arbitrary origin. */
export function validateRemoteConnection(connection: RemoteConnection): RemoteConnection {
  const url = new URL(connection.url);
  if (url.protocol !== "http:" || url.hostname !== "127.0.0.1" || !url.port
    || url.username || url.password || url.pathname !== "/") {
    throw new Error("invalid_remote_url");
  }
  return connection;
}

export type SelectedRemote = Pick<RemoteConnection, "id" | "name" | "hostname">;
const SELECTED_REMOTE = "nanobot.remote-instance";
const RECENT_REMOTES = "nanobot.recent-remote-instances";

/** Only profile IDs are persisted, never connection URLs or credentials. */
export function readRecentRemotes(): string[] {
  try {
    const value: unknown = JSON.parse(window.localStorage.getItem(RECENT_REMOTES) || "[]");
    return Array.isArray(value) ? [...new Set(value.filter((id): id is string =>
      typeof id === "string" && /^[a-f0-9-]{36}$/.test(id)))].slice(0, 20) : [];
  } catch { return []; }
}

export function rememberRecentRemote(id: string, previous: string[]): string[] {
  const next = [id, ...previous.filter((item) => item !== id)].slice(0, 20);
  try { window.localStorage.setItem(RECENT_REMOTES, JSON.stringify(next)); }
  catch { /* Switching still works when browser storage is disabled. */ }
  return next;
}

export function readSelectedRemote(): SelectedRemote | null {
  try {
    // A remote WebUI embedded by another nanobot must not inherit a local host's selector.
    if (window.top !== window) return null;
    const value = JSON.parse(window.sessionStorage.getItem(SELECTED_REMOTE) || "null") as SelectedRemote | null;
    return value && /^[a-f0-9-]{36}$/.test(value.id) && typeof value.name === "string"
      && typeof value.hostname === "string" ? value : null;
  } catch { return null; }
}

export function rememberSelectedRemote(value: SelectedRemote | null): void {
  try {
    if (value) window.sessionStorage.setItem(SELECTED_REMOTE, JSON.stringify({ id: value.id, name: value.name, hostname: value.hostname }));
    else window.sessionStorage.removeItem(SELECTED_REMOTE);
  } catch { /* Storage can be disabled; the live connection still works. */ }
}
