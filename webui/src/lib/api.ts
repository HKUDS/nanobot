import type {
  ApiServicePayload,
  AutomationsPayload,
  AutomationUpdatePayload,
  ChannelConfigurePayload,
  ChannelConnectPayload,
  ChannelValidationPayload,
  ChatSummary,
  CliAppsPayload,
  FilePreviewPayload,
  FileReferenceMetadata,
  ImageGenerationSettingsUpdate,
  McpPresetsPayload,
  McpOAuthFlowPayload,
  MarketplaceProvider,
  NanobotFeaturesPayload,
  ModelConfigurationCreate,
  ModelConfigurationUpdate,
  NetworkSafetySettingsUpdate,
  PairingPayload,
  ProviderCreationUpdate,
  ProviderModelsPayload,
  ProviderOAuthCompletionResult,
  ProviderOAuthLoginResult,
  ProviderSettingsUpdate,
  RecoveryState,
  SessionDeleteResult,
  SessionHandle,
  SessionAutomationsPayload,
  SettingsPayload,
  SidebarStatePayload,
  SkillDetail,
  SkillActionPayload,
  SkillInstallPayload,
  SkillsPayload,
  SkillsSearchPayload,
  SkillsTrendsPayload,
  SkillsTrendingPayload,
  SlashCommand,
  SlashCommandLifecycle,
  TranscriptionSettingsUpdate,
  ThreadProjectionEvent,
  WebSearchSettingsUpdate,
  WorkspacesPayload,
  WebuiThreadPersistedPayload,
  WebuiThreadTraceDetailPayload,
  WorkspaceScopePayload,
} from "./types";
import { fetchWithTimeout } from "./http";

const API_READ_TIMEOUT_MS = 20_000;
const API_MUTATION_TIMEOUT_MS = 20_000;
const PACKAGE_MUTATION_TIMEOUT_MS = 150_000;
const SLASH_COMMAND_LIFECYCLES = new Set<SlashCommandLifecycle>([
  "side_channel",
  "finalize_active_turn",
  "stop_active_turn",
  "agent_turn",
  "agent_turn_with_args",
]);

function isSlashCommandLifecycle(value: unknown): value is SlashCommandLifecycle {
  return (
    typeof value === "string"
    && SLASH_COMMAND_LIFECYCLES.has(value as SlashCommandLifecycle)
  );
}
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

export interface WebUIMutationTransport {
  requestMutation<T>(
    action: string,
    payload?: Record<string, unknown>,
    timeoutMs?: number,
  ): Promise<T>;
}

async function request<T>(
  url: string,
  token: string,
  init?: RequestInit,
  timeoutMs: number = 0,
): Promise<T> {
  const res = await fetchWithTimeout(
    url,
    {
      ...(init ?? {}),
      headers: {
        ...(init?.headers ?? {}),
        Authorization: `Bearer ${token}`,
      },
      credentials: "same-origin",
    },
    timeoutMs,
  );
  if (!res.ok) {
    const text = typeof res.text === "function" ? (await res.text()).trim() : "";
    let message = text;
    if (text.startsWith("{")) {
      try {
        const payload: unknown = JSON.parse(text);
        if (payload && typeof payload === "object") {
          const error = (payload as { error?: unknown }).error;
          if (typeof error === "string" && error.trim()) message = error.trim();
        }
      } catch {
        // Preserve non-JSON error bodies exactly as returned by the gateway.
      }
    }
    throw new ApiError(res.status, message || `HTTP ${res.status}`);
  }
  const contentType = res.headers?.get?.("content-type") ?? "";
  if (contentType && !contentType.toLowerCase().includes("application/json")) {
    const text = typeof res.text === "function" ? await res.text() : "";
    const isHtml = text.trimStart().toLowerCase().startsWith("<!doctype");
    throw new ApiError(
      res.status,
      isHtml
        ? "Gateway returned WebUI HTML instead of JSON. Restart nanobot gateway and try again."
        : "Gateway returned a non-JSON response.",
    );
  }
  return (await res.json()) as T;
}

async function mutation<T>(
  transport: WebUIMutationTransport,
  action: string,
  payload: Record<string, unknown> = {},
  timeoutMs: number = API_MUTATION_TIMEOUT_MS,
): Promise<T> {
  try {
    return await transport.requestMutation<T>(action, payload, timeoutMs);
  } catch (reason) {
    const status = (
      typeof reason === "object"
      && reason !== null
      && "status" in reason
      && typeof reason.status === "number"
    ) ? reason.status : 500;
    const message = reason instanceof Error ? reason.message : "WebUI mutation failed";
    throw new ApiError(status, message);
  }
}

function compactMcpValues(values: Record<string, unknown>): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  Object.entries(values).forEach(([key, value]) => {
    if (value === null || value === undefined) return;
    if (typeof value === "string") {
      const trimmed = value.trim();
      if (trimmed) payload[key] = trimmed;
      return;
    }
    payload[key] = value;
  });
  return payload;
}

function splitKey(key: string): { channel: string; chatId: string } {
  const idx = key.indexOf(":");
  if (idx === -1) return { channel: "", chatId: key };
  return { channel: key.slice(0, idx), chatId: key.slice(idx + 1) };
}

function normalizeSessionHandle(value: unknown): SessionHandle | null {
  if (!value || typeof value !== "object") return null;
  const handle = value as Partial<SessionHandle>;
  const id = typeof handle.id === "string" ? handle.id.trim() : "";
  const name = typeof handle.name === "string" ? handle.name.trim() : "";
  if (
    !/^handle_[a-f0-9]{32}$/i.test(id)
    || !name
    || !/^[\p{L}\p{N}_-]+$/u.test(name)
  ) return null;
  return { id, name };
}

export async function listSessions(
  token: string,
  base: string = "",
): Promise<ChatSummary[]> {
  type Row = {
    key: string;
    created_at: string | null;
    updated_at: string | null;
    title?: string;
    preview?: string;
    model_preset?: string | null;
    run_started_at?: number | null;
    recovery_state?: RecoveryState | null;
    workspace_scope?: WorkspaceScopePayload | null;
    handle?: SessionHandle | null;
  };
  const body = await request<{ sessions: Row[] }>(
    `${base}/api/sessions`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
  return body.sessions.map((s) => {
    const handle = normalizeSessionHandle(s.handle);
    return {
      key: s.key,
      ...splitKey(s.key),
      createdAt: s.created_at,
      updatedAt: s.updated_at,
      title: s.title ?? "",
      preview: s.preview ?? "",
      modelPreset: s.model_preset ?? null,
      runStartedAt: s.run_started_at ?? null,
      recoveryState: s.recovery_state ?? null,
      workspaceScope: s.workspace_scope ?? null,
      handle,
    };
  });
}

/** Disk-backed WebUI display thread snapshot (separate from agent session). */
export interface FetchWebuiThreadOptions {
  limit?: number;
  direction?: "latest";
  before?: string | null;
  signal?: AbortSignal;
  revision?: string;
  cached?: WebuiThreadPersistedPayload;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isRecordArray(value: unknown): value is Array<Record<string, unknown>> {
  return Array.isArray(value) && value.every(isRecord);
}

function isProjectionMedia(value: unknown): boolean {
  return isRecord(value)
    && typeof value.url === "string"
    && (value.name === undefined || typeof value.name === "string")
    && (value.kind === undefined || ["image", "video", "file"].includes(String(value.kind)));
}

function hasStringField(value: Record<string, unknown>, field: string): boolean {
  return typeof value[field] === "string";
}

function isProjectionFileEdit(value: unknown): boolean {
  return isRecord(value)
    && hasStringField(value, "call_id")
    && hasStringField(value, "tool")
    && hasStringField(value, "path")
    && typeof value.added === "number"
    && typeof value.deleted === "number"
    && ["editing", "done", "error"].includes(String(value.status));
}

function hasValidProjectionMetadata(value: Record<string, unknown>): boolean {
  return (
    (value.projection_id === undefined || typeof value.projection_id === "string")
    && (value.created_at_ms === undefined || typeof value.created_at_ms === "number")
    && (value.turn_id === undefined || typeof value.turn_id === "string")
    && (value.turn_phase === undefined || [
      "user", "reasoning", "activity", "answer", "complete",
    ].includes(String(value.turn_phase)))
    && (value.turn_seq === undefined || typeof value.turn_seq === "number")
    && (
      value.response_sources === undefined
      || (isRecordArray(value.response_sources) && value.response_sources.every((source) => (
        typeof source.provider === "string" && source.provider.length > 0
        && typeof source.model === "string" && source.model.length > 0
        && typeof source.preset === "string" && source.preset.length > 0
        && (source.fallback === undefined || typeof source.fallback === "boolean")
      )))
    )
    && (
      value.source === undefined
      || (
        isRecord(value.source)
        && typeof value.source.kind === "string"
        && (value.source.label === undefined || typeof value.source.label === "string")
      )
    )
  );
}

function isProjectionTraceDetail(value: unknown): boolean {
  return isRecord(value)
    && typeof value.ref === "string"
    && /^\d{1,12}\.history-[0-9a-f]{20}$/.test(value.ref)
    && typeof value.bytes === "number"
    && Number.isFinite(value.bytes)
    && value.bytes >= 0
    && typeof value.traceCount === "number"
    && Number.isInteger(value.traceCount)
    && value.traceCount >= 0;
}

function parseThreadProjectionEvent(value: unknown): ThreadProjectionEvent {
  if (!isRecord(value) || typeof value.event !== "string" || typeof value.chat_id !== "string") {
    throw new Error("Invalid WebUI thread event");
  }
  if (!hasValidProjectionMetadata(value)) {
    throw new Error("Invalid WebUI thread event metadata");
  }
  switch (value.event) {
    case "user_message":
      if (typeof value.text !== "string" || typeof value.starts_turn !== "boolean") break;
      if (value.media_urls !== undefined && (
        !Array.isArray(value.media_urls) || !value.media_urls.every(isProjectionMedia)
      )) break;
      if (value.cli_apps !== undefined && (
        !isRecordArray(value.cli_apps) || !value.cli_apps.every((item) => hasStringField(item, "name"))
      )) break;
      if (value.mcp_presets !== undefined && (
        !isRecordArray(value.mcp_presets)
        || !value.mcp_presets.every((item) => hasStringField(item, "name"))
      )) break;
      if (value.session_mentions !== undefined && (
        !isRecordArray(value.session_mentions)
        || !value.session_mentions.every((item) => (
          hasStringField(item, "name")
          && hasStringField(item, "session_key")
          && hasStringField(item, "title")
        ))
      )) break;
      if (value.provenance !== undefined && (
        !isRecord(value.provenance)
        || !isRecord(value.provenance.session_message)
        || !hasStringField(value.provenance.session_message, "message_id")
        || !isRecord(value.provenance.session_message.session)
      )) break;
      return value as unknown as ThreadProjectionEvent;
    case "message":
      if (typeof value.text !== "string") break;
      if (value.tool_events !== undefined && !isRecordArray(value.tool_events)) break;
      if (value.trace_detail !== undefined && (
        !["tool_hint", "progress"].includes(String(value.kind))
        || !isProjectionTraceDetail(value.trace_detail)
      )) break;
      if (value.media_urls !== undefined && (
        !Array.isArray(value.media_urls) || !value.media_urls.every(isProjectionMedia)
      )) break;
      return value as unknown as ThreadProjectionEvent;
    case "file_edit":
      if (!Array.isArray(value.edits) || !value.edits.every(isProjectionFileEdit)) break;
      return value as unknown as ThreadProjectionEvent;
    case "delta":
    case "reasoning_delta":
      if (typeof value.text !== "string") break;
      return value as unknown as ThreadProjectionEvent;
    case "stream_end":
    case "reasoning_end":
      if (value.text !== undefined && typeof value.text !== "string") break;
      return value as unknown as ThreadProjectionEvent;
    case "context_compaction":
      if (typeof value.compaction_id !== "string" || typeof value.phase !== "string") break;
      return value as unknown as ThreadProjectionEvent;
    case "turn_end":
      return value as unknown as ThreadProjectionEvent;
  }
  throw new Error(`Invalid WebUI thread projection event: ${value.event}`);
}

function parseWebuiThreadPayload(value: unknown): WebuiThreadPersistedPayload {
  if (!isRecord(value) || typeof value.schemaVersion !== "number") {
    throw new Error("Invalid WebUI thread response");
  }
  if (value.projection !== "events" || !Array.isArray(value.events)) {
    throw new Error("Invalid WebUI thread events");
  }
  const events = value.events.map(parseThreadProjectionEvent);
  return {
    ...value,
    projection: "events",
    events,
  } as unknown as WebuiThreadPersistedPayload;
}

function parseWebuiThreadTraceDetailPayload(value: unknown): WebuiThreadTraceDetailPayload {
  if (
    !isRecord(value)
    || typeof value.message_id !== "string"
    || !/^history-[0-9a-f]{20}$/.test(value.message_id)
    || !Array.isArray(value.events)
  ) {
    throw new Error("Invalid WebUI thread trace detail response");
  }
  return {
    message_id: value.message_id,
    events: value.events.map(parseThreadProjectionEvent),
  };
}

export async function fetchWebuiThread(
  token: string,
  key: string,
  optionsOrBase?: FetchWebuiThreadOptions | string,
  base: string = "",
): Promise<WebuiThreadPersistedPayload | null> {
  const options = typeof optionsOrBase === "string" ? undefined : optionsOrBase;
  const resolvedBase = typeof optionsOrBase === "string" ? optionsOrBase : base;
  const params = new URLSearchParams();
  if (options?.limit !== undefined) params.set("limit", String(options.limit));
  if (options?.direction) params.set("direction", options.direction);
  if (options?.before) params.set("before", options.before);
  const query = params.toString();
  const suffix = query ? `?${query}` : "";
  const url = `${resolvedBase}/api/sessions/${encodeURIComponent(key)}/webui-thread${suffix}`;
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  if (options?.revision) headers["If-None-Match"] = `"${options.revision}"`;
  const res = await fetchWithTimeout(url, {
    headers,
    credentials: "same-origin",
    cache: "no-store",
    signal: options?.signal,
  });
  if (res.status === 304 && options?.cached) return options.cached;
  if (res.status === 404) return null;
  if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`);
  return parseWebuiThreadPayload(await res.json());
}

export async function fetchWebuiThreadTraceDetail(
  token: string,
  key: string,
  ref: string,
  base: string = "",
): Promise<WebuiThreadTraceDetailPayload> {
  const query = new URLSearchParams({ ref });
  const url = `${base}/api/sessions/${encodeURIComponent(key)}/webui-thread/trace-detail?${query}`;
  const res = await fetchWithTimeout(url, {
    headers: { Authorization: `Bearer ${token}` },
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`);
  return parseWebuiThreadTraceDetailPayload(await res.json());
}

export async function fetchFilePreview(
  token: string,
  key: string,
  path: string,
  base: string = "",
): Promise<FilePreviewPayload> {
  const query = new URLSearchParams();
  query.set("path", path);
  return request<FilePreviewPayload>(
    `${base}/api/sessions/${encodeURIComponent(key)}/file-preview?${query}`,
    token,
    { cache: "no-store" },
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchFileReferenceMetadata(
  token: string,
  key: string,
  path: string,
): Promise<FileReferenceMetadata> {
  const query = new URLSearchParams({ path, metadata: "1" });
  return request<FileReferenceMetadata>(
    `/api/sessions/${encodeURIComponent(key)}/file-preview?${query}`,
    token,
    { cache: "no-store" },
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchFilePreviewAvailability(
  token: string,
  key: string,
  path: string,
  base: string = "",
): Promise<boolean> {
  const query = new URLSearchParams();
  query.set("path", path);
  query.set("probe", "1");
  const payload = await request<{ available?: boolean }>(
    `${base}/api/sessions/${encodeURIComponent(key)}/file-preview?${query}`,
    token,
    { cache: "no-store" },
    API_READ_TIMEOUT_MS,
  );
  return payload.available !== false;
}

export async function fetchSessionAutomations(
  token: string,
  key: string,
  base: string = "",
): Promise<SessionAutomationsPayload> {
  return request<SessionAutomationsPayload>(
    `${base}/api/sessions/${encodeURIComponent(key)}/automations`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchAutomations(
  token: string,
  base: string = "",
): Promise<AutomationsPayload> {
  return request<AutomationsPayload>(
    `${base}/api/webui/automations`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchAutomationRunResult(
  token: string,
  id: string,
  runAtMs: number,
  kind: "cron" | "local_trigger",
  signal?: AbortSignal,
): Promise<{ response: string | null }> {
  const query = new URLSearchParams({ id, run_at_ms: String(runAtMs), kind });
  return request<{ response: string | null }>(
    `/api/webui/automations/result?${query}`, token, { signal }, API_READ_TIMEOUT_MS,
  );
}

export async function runAutomationAction(
  transport: WebUIMutationTransport,
  action: "enable" | "disable" | "delete" | "run",
  id: string,
): Promise<AutomationsPayload> {
  return mutation<AutomationsPayload>(transport, `automation.${action}`, { id });
}

export async function updateAutomation(
  transport: WebUIMutationTransport,
  id: string,
  values: AutomationUpdatePayload,
): Promise<AutomationsPayload> {
  return mutation<AutomationsPayload>(transport, "automation.update", { id, values });
}

export async function fetchSkills(
  token: string,
  base: string = "",
): Promise<SkillsPayload> {
  return request<SkillsPayload>(
    `${base}/api/webui/skills`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchSkillDetail(
  token: string,
  name: string,
  base: string = "",
): Promise<SkillDetail> {
  return request<SkillDetail>(
    `${base}/api/webui/skills/${encodeURIComponent(name)}`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function updateSkillEnabled(
  transport: WebUIMutationTransport,
  name: string,
  enabled: boolean,
): Promise<SkillActionPayload> {
  return mutation<SkillActionPayload>(transport, "skill.update", { name, enabled });
}

export async function deleteSkill(
  transport: WebUIMutationTransport,
  name: string,
): Promise<SkillActionPayload> {
  return mutation<SkillActionPayload>(transport, "skill.delete", { name });
}

export async function searchMarketplaceSkills(
  token: string,
  query: string,
  provider: MarketplaceProvider = "all",
  base: string = "",
): Promise<SkillsSearchPayload> {
  const params = new URLSearchParams({ q: query, provider });
  return request<SkillsSearchPayload>(
    `${base}/api/webui/skills/search?${params}`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchTrendingMarketplaceSkills(
  token: string,
  provider: MarketplaceProvider = "all",
  base: string = "",
): Promise<SkillsTrendingPayload> {
  const params = new URLSearchParams({ provider });
  return request<SkillsTrendingPayload>(
    `${base}/api/webui/skills/trending?${params}`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchMarketplaceSkillTrends(
  token: string,
  skillIds: string[],
  base: string = "",
): Promise<SkillsTrendsPayload> {
  const params = new URLSearchParams();
  skillIds.forEach((id) => params.append("id", id));
  return request<SkillsTrendsPayload>(
    `${base}/api/webui/skills/trends?${params}`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function installMarketplaceSkill(
  transport: WebUIMutationTransport,
  provider: Exclude<MarketplaceProvider, "all">,
  source: string,
  skill: string,
  version: string = "",
): Promise<SkillInstallPayload> {
  return mutation<SkillInstallPayload>(
    transport,
    "skill.install",
    { provider, source, skill, ...(version ? { version } : {}) },
    PACKAGE_MUTATION_TIMEOUT_MS,
  );
}

export async function deleteSession(
  transport: WebUIMutationTransport,
  key: string,
  optionsOrBase?: { deleteAutomations?: boolean } | string,
): Promise<SessionDeleteResult> {
  const options = typeof optionsOrBase === "string" ? undefined : optionsOrBase;
  return mutation<SessionDeleteResult>(
    transport,
    "session.delete",
    {
      key,
      ...(options?.deleteAutomations ? { delete_automations: true } : {}),
    },
  );
}

export async function fetchSettings(
  token: string,
  base: string = "",
): Promise<SettingsPayload> {
  return request<SettingsPayload>(
    `${base}/api/settings`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchSettingsUsage(
  token: string,
  base: string = "",
): Promise<NonNullable<SettingsPayload["usage"]>> {
  return request<NonNullable<SettingsPayload["usage"]>>(
    `${base}/api/settings/usage`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export interface VersionCheckResult {
  updateAvailable: {
    currentVersion: string;
    latestVersion: string;
    pypiUrl?: string;
  } | null;
}

export async function checkVersion(
  token: string,
  base: string = "",
): Promise<VersionCheckResult> {
  return request<VersionCheckResult>(
    `${base}/api/settings/version-check`,
    token,
    undefined,
    10_000,
  );
}

export async function fetchWorkspaces(
  token: string,
  base: string = "",
): Promise<WorkspacesPayload> {
  return request<WorkspacesPayload>(
    `${base}/api/workspaces`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchCliApps(
  token: string,
  base: string = "",
): Promise<CliAppsPayload> {
  return request<CliAppsPayload>(
    `${base}/api/settings/cli-apps`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchInstalledCliApps(
  token: string,
  base: string = "",
): Promise<CliAppsPayload> {
  return request<CliAppsPayload>(
    `${base}/api/settings/cli-apps?installed_only=1`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchNanobotFeatures(
  token: string,
  base: string = "",
): Promise<NanobotFeaturesPayload> {
  return request<NanobotFeaturesPayload>(
    `${base}/api/settings/nanobot-features`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchApiService(token: string, base: string = ""): Promise<ApiServicePayload> {
  return request<ApiServicePayload>(`${base}/api/settings/api-service`, token);
}

export async function startApiService(
  transport: WebUIMutationTransport,
  values: { host: string; port: number; timeout: number; apiKey?: string },
): Promise<ApiServicePayload> {
  return mutation<ApiServicePayload>(
    transport,
    "settings.api_service.start",
    {
      host: values.host,
      port: values.port,
      timeout: values.timeout,
      ...(values.apiKey !== undefined ? { api_key: values.apiKey } : {}),
    },
    PACKAGE_MUTATION_TIMEOUT_MS,
  );
}

export async function stopApiService(
  transport: WebUIMutationTransport,
): Promise<ApiServicePayload> {
  return mutation<ApiServicePayload>(transport, "settings.api_service.stop");
}

export async function enableNanobotFeature(
  transport: WebUIMutationTransport,
  name: string,
  options: { instanceId?: string; installOnly?: boolean } = {},
): Promise<NanobotFeaturesPayload> {
  return mutation<NanobotFeaturesPayload>(
    transport,
    "settings.feature.enable",
    {
      name,
      ...(options.instanceId ? { instance_id: options.instanceId } : {}),
      ...(options.installOnly ? { install_only: true } : {}),
    },
    PACKAGE_MUTATION_TIMEOUT_MS,
  );
}

export async function disableNanobotFeature(
  transport: WebUIMutationTransport,
  name: string,
  options: { instanceId?: string } = {},
): Promise<NanobotFeaturesPayload> {
  return mutation<NanobotFeaturesPayload>(
    transport,
    "settings.feature.disable",
    { name, ...(options.instanceId ? { instance_id: options.instanceId } : {}) },
  );
}

export async function fetchPairingRequests(
  token: string,
  base: string = "",
): Promise<PairingPayload> {
  return request<PairingPayload>(
    `${base}/api/settings/pairing`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function runPairingAction(
  transport: WebUIMutationTransport,
  action: "approve" | "deny",
  code: string,
): Promise<PairingPayload> {
  return mutation<PairingPayload>(transport, `settings.pairing.${action}`, { code });
}

export async function startChannelConnect<T = ChannelConnectPayload>(
  transport: WebUIMutationTransport,
  channel: string,
  params: Readonly<Record<string, string | boolean>> = {},
): Promise<T> {
  return mutation<T>(
    transport,
    "settings.channel.connect.start",
    {
      ...params,
      channel,
    },
    PACKAGE_MUTATION_TIMEOUT_MS,
  );
}

export async function pollChannelConnect(
  transport: WebUIMutationTransport,
  channel: string,
  sessionId: string,
  params: Readonly<Record<string, string>> = {},
): Promise<ChannelConnectPayload> {
  const values = Object.fromEntries(
    Object.entries(params).filter(([key]) => key !== "session_id"),
  );
  return mutation<ChannelConnectPayload>(
    transport,
    "settings.channel.connect.poll",
    { channel, session_id: sessionId, ...values },
    PACKAGE_MUTATION_TIMEOUT_MS,
  );
}

export async function cancelChannelConnect(
  transport: WebUIMutationTransport,
  channel: string,
  sessionId: string,
): Promise<ChannelConnectPayload> {
  return mutation<ChannelConnectPayload>(
    transport,
    "settings.channel.connect.cancel",
    { channel, session_id: sessionId },
  );
}

export async function configureChannel(
  transport: WebUIMutationTransport,
  name: string,
  values: Record<string, string | null>,
  options: { enable?: boolean; instanceId?: string } = {},
): Promise<ChannelConfigurePayload> {
  return mutation<ChannelConfigurePayload>(
    transport,
    "settings.channel.configure",
    {
      name,
      values,
      ...(options.enable !== undefined ? { enable: options.enable } : {}),
      ...(options.instanceId ? { instance_id: options.instanceId } : {}),
    },
    PACKAGE_MUTATION_TIMEOUT_MS,
  );
}

export async function validateChannel(
  transport: WebUIMutationTransport,
  name: string,
  values: Record<string, string | null> = {},
  options: { instanceId?: string } = {},
): Promise<ChannelValidationPayload> {
  return mutation<ChannelValidationPayload>(
    transport,
    "settings.channel.validate",
    { name, values, ...(options.instanceId ? { instance_id: options.instanceId } : {}) },
  );
}

export async function runCliAppAction(
  transport: WebUIMutationTransport,
  action: "install" | "update" | "uninstall" | "test",
  name: string,
): Promise<CliAppsPayload> {
  return mutation<CliAppsPayload>(
    transport,
    `settings.cli_app.${action}`,
    { name },
    action === "install" || action === "update"
      ? PACKAGE_MUTATION_TIMEOUT_MS
      : API_MUTATION_TIMEOUT_MS,
  );
}

export async function fetchMcpPresets(
  token: string,
  base: string = "",
): Promise<McpPresetsPayload> {
  return request<McpPresetsPayload>(
    `${base}/api/settings/mcp-presets`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function startMcpOAuth(
  transport: WebUIMutationTransport,
  name: string,
  reset: boolean = false,
): Promise<McpOAuthFlowPayload> {
  return mutation<McpOAuthFlowPayload>(
    transport,
    "settings.mcp.oauth_start",
    { name, ...(reset ? { reset: true } : {}) },
    30_000,
  );
}

export async function fetchMcpOAuthStatus(
  token: string,
  flowId: string,
  base: string = "",
): Promise<McpOAuthFlowPayload> {
  const query = new URLSearchParams({ flow_id: flowId });
  return request<McpOAuthFlowPayload>(
    `${base}/api/settings/mcp-oauth/status?${query}`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function completeMcpOAuth(
  transport: WebUIMutationTransport,
  flowId: string,
  callbackUrl: string,
): Promise<McpOAuthFlowPayload> {
  return mutation<McpOAuthFlowPayload>(
    transport,
    "settings.mcp.oauth_complete",
    { flow_id: flowId, callback_url: callbackUrl },
  );
}

export async function cancelMcpOAuth(
  transport: WebUIMutationTransport,
  flowId: string,
): Promise<McpOAuthFlowPayload> {
  return mutation<McpOAuthFlowPayload>(
    transport,
    "settings.mcp.oauth_cancel",
    { flow_id: flowId },
  );
}

export async function fetchProviderModels(
  token: string,
  provider: string,
  base: string = "",
): Promise<ProviderModelsPayload> {
  const query = new URLSearchParams();
  query.set("provider", provider);
  return request<ProviderModelsPayload>(
    `${base}/api/settings/provider-models?${query}`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function runMcpPresetAction(
  transport: WebUIMutationTransport,
  action: "enable" | "disable" | "remove" | "test" | "reconnect",
  name: string,
  values: Record<string, string> = {},
): Promise<McpPresetsPayload> {
  return mutation<McpPresetsPayload>(
    transport,
    `settings.mcp.${action}`,
    { name, ...compactMcpValues(values) },
  );
}

export async function saveCustomMcpServer(
  transport: WebUIMutationTransport,
  values: Record<string, string>,
): Promise<McpPresetsPayload> {
  return mutation<McpPresetsPayload>(
    transport,
    "settings.mcp.custom",
    compactMcpValues(values),
  );
}

export async function importMcpConfig(
  transport: WebUIMutationTransport,
  config: string,
): Promise<McpPresetsPayload> {
  return mutation<McpPresetsPayload>(transport, "settings.mcp.import", { config });
}

export async function updateMcpServerTools(
  transport: WebUIMutationTransport,
  name: string,
  enabledTools: string[],
): Promise<McpPresetsPayload> {
  return mutation<McpPresetsPayload>(
    transport,
    "settings.mcp.tools",
    { name, enabled_tools: enabledTools },
  );
}

export async function listSlashCommands(
  token: string,
  base: string = "",
): Promise<SlashCommand[]> {
  type Row = {
    command: string;
    title: string;
    description: string;
    icon: string;
    arg_hint?: string;
    lifecycle?: unknown;
    accepts_args?: unknown;
  };
  const body = await request<{ commands: Row[] }>(
    `${base}/api/commands`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
  return body.commands
    .flatMap((command) => {
      if (!isSlashCommandLifecycle(command.lifecycle)) return [];
      return [{
        command: command.command,
        title: command.title,
        description: command.description,
        icon: command.icon,
        argHint: command.arg_hint ?? "",
        lifecycle: command.lifecycle,
        acceptsArgs: command.accepts_args === true,
      }];
    });
}

export async function fetchSidebarState(
  token: string,
  base: string = "",
): Promise<SidebarStatePayload> {
  return request<SidebarStatePayload>(
    `${base}/api/webui/sidebar-state`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function updateSidebarState(
  transport: WebUIMutationTransport,
  state: SidebarStatePayload,
): Promise<SidebarStatePayload> {
  return mutation<SidebarStatePayload>(transport, "sidebar.update", { state });
}

function modelGenerationSettingsPayload(
  configuration: Pick<
    ModelConfigurationCreate,
    "maxTokens" | "contextWindowTokens" | "temperature" | "reasoningEffort"
  >,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  if (configuration.maxTokens !== undefined) {
    payload.max_tokens = configuration.maxTokens;
  }
  if (configuration.contextWindowTokens !== undefined) {
    payload.context_window_tokens = configuration.contextWindowTokens;
  }
  if (configuration.temperature !== undefined) {
    payload.temperature = configuration.temperature;
  }
  if (configuration.reasoningEffort !== undefined) {
    payload.reasoning_effort = configuration.reasoningEffort ?? "";
  }
  return payload;
}

export async function createModelConfiguration(
  transport: WebUIMutationTransport,
  configuration: ModelConfigurationCreate,
): Promise<SettingsPayload> {
  return mutation<SettingsPayload>(
    transport,
    "settings.model_configuration.create",
    {
      name: configuration.name,
      provider: configuration.provider,
      model: configuration.model,
      ...modelGenerationSettingsPayload(configuration),
    },
  );
}

export async function updateModelConfiguration(
  transport: WebUIMutationTransport,
  configuration: ModelConfigurationUpdate,
): Promise<SettingsPayload> {
  return mutation<SettingsPayload>(
    transport,
    "settings.model_configuration.update",
    {
      name: configuration.name,
      ...(configuration.newName !== undefined ? { new_name: configuration.newName } : {}),
      ...(configuration.provider !== undefined ? { provider: configuration.provider } : {}),
      ...(configuration.model !== undefined ? { model: configuration.model } : {}),
      ...modelGenerationSettingsPayload(configuration),
    },
  );
}

export async function deleteModelConfiguration(
  transport: WebUIMutationTransport,
  name: string,
): Promise<SettingsPayload> {
  return mutation<SettingsPayload>(
    transport,
    "settings.model_configuration.delete",
    { name },
  );
}

export async function migrateModelConfigurations(
  transport: WebUIMutationTransport,
): Promise<SettingsPayload> {
  return mutation<SettingsPayload>(transport, "settings.model_configuration.migrate");
}

export async function updateModelCallOrder(
  transport: WebUIMutationTransport,
  order: string[],
): Promise<SettingsPayload> {
  return mutation<SettingsPayload>(transport, "settings.model_call_order.update", { order });
}

export async function updateProviderSettings(
  transport: WebUIMutationTransport,
  update: ProviderSettingsUpdate,
): Promise<SettingsPayload> {
  return mutation<SettingsPayload>(transport, "settings.provider.update", { ...update });
}

export async function createProviderSettings(
  transport: WebUIMutationTransport,
  update: ProviderCreationUpdate,
): Promise<SettingsPayload> {
  return mutation<SettingsPayload>(transport, "settings.provider.create", { ...update });
}

export async function loginProviderOAuth(
  transport: WebUIMutationTransport,
  provider: string,
  remoteBrowserAccess: boolean = false,
): Promise<ProviderOAuthLoginResult> {
  return mutation<ProviderOAuthLoginResult>(
    transport,
    "settings.provider.oauth_login",
    { provider, ...(remoteBrowserAccess ? { remote_browser: true } : {}) },
  );
}

export async function completeProviderOAuth(
  transport: WebUIMutationTransport,
  provider: string,
  flowId: string,
  authorizationResponse?: string,
): Promise<ProviderOAuthCompletionResult> {
  return mutation<ProviderOAuthCompletionResult>(
    transport,
    "settings.provider.oauth_complete",
    {
      provider,
      flow_id: flowId,
      ...(authorizationResponse ? { authorization_response: authorizationResponse } : {}),
    },
  );
}

export async function cancelProviderOAuth(
  transport: WebUIMutationTransport,
  provider: string,
  flowId: string,
): Promise<void> {
  await mutation(transport, "settings.provider.oauth_complete", {
    provider, flow_id: flowId, cancel: true,
  });
}

export async function logoutProviderOAuth(
  transport: WebUIMutationTransport,
  provider: string,
): Promise<SettingsPayload> {
  return mutation<SettingsPayload>(transport, "settings.provider.oauth_logout", { provider });
}

export async function updateWebSearchSettings(
  transport: WebUIMutationTransport,
  update: WebSearchSettingsUpdate,
): Promise<SettingsPayload> {
  return mutation<SettingsPayload>(
    transport,
    "settings.web_search.update",
    {
      provider: update.provider,
      ...(update.apiKey !== undefined ? { api_key: update.apiKey } : {}),
      ...(update.baseUrl !== undefined ? { base_url: update.baseUrl } : {}),
      ...(update.maxResults !== undefined ? { max_results: update.maxResults } : {}),
      ...(update.timeout !== undefined ? { timeout: update.timeout } : {}),
      ...(update.useJinaReader !== undefined
        ? { use_jina_reader: update.useJinaReader }
        : {}),
    },
  );
}

export async function updateNetworkSafetySettings(
  transport: WebUIMutationTransport,
  update: NetworkSafetySettingsUpdate,
): Promise<SettingsPayload> {
  return mutation<SettingsPayload>(
    transport,
    "settings.network_safety.update",
    {
      webui_allow_local_service_access: update.webuiAllowLocalServiceAccess,
      webui_default_access_mode: update.webuiDefaultAccessMode,
    },
  );
}

export async function updateImageGenerationSettings(
  transport: WebUIMutationTransport,
  update: ImageGenerationSettingsUpdate,
): Promise<SettingsPayload> {
  return mutation<SettingsPayload>(
    transport,
    "settings.image_generation.update",
    {
      enabled: update.enabled,
      provider: update.provider,
      model: update.model,
      default_aspect_ratio: update.defaultAspectRatio,
      default_image_size: update.defaultImageSize,
      max_images_per_turn: update.maxImagesPerTurn,
    },
  );
}

export async function updateTranscriptionSettings(
  transport: WebUIMutationTransport,
  update: TranscriptionSettingsUpdate,
): Promise<SettingsPayload> {
  return mutation<SettingsPayload>(
    transport,
    "settings.transcription.update",
    {
      enabled: update.enabled,
      provider: update.provider,
      model: update.model,
      language: update.language,
      max_duration_sec: update.maxDurationSec,
      max_upload_mb: update.maxUploadMb,
    },
  );
}


export async function updateRuntimeConfigSettings(
  transport: WebUIMutationTransport,
  values: Record<string, import("@/lib/types").RuntimeConfigValue>,
): Promise<SettingsPayload> {
  return mutation<SettingsPayload>(transport, "settings.runtime_config.update", { values });
}
