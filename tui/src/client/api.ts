import { isRecoveryState } from "../../../packages/client-events/notifications"

import type {
  ApiReauthenticator,
  GatewayApiConnection,
  HistoryMessage,
  HistorySnapshot,
  InboundEvent,
  MentionCandidate,
  RuntimeControls,
  SessionContextSnapshot,
  SessionSummary,
  SessionUsageSnapshot,
  SkillCandidate,
  SlashCommand,
  SlashCommandLifecycle,
  TokenUsage,
} from "./types"
import {
  decodeInboundEvent,
  isRecord,
  isTokenUsage,
  isWorkspaceScope,
  optional,
} from "./validation"

const SKILL_REFERENCE_NAME = /^[A-Za-z0-9_-]+$/u
const SLASH_COMMAND_LIFECYCLES = new Set([
  "side_channel",
  "finalize_active_turn",
  "stop_active_turn",
  "agent_turn",
  "agent_turn_with_args",
])

async function fetchApi(
  apiUrl: string,
  apiToken: string,
  path: string,
  reauthenticate?: ApiReauthenticator,
  signal?: AbortSignal,
): Promise<Response> {
  const request = (connection: GatewayApiConnection) => {
    signal?.throwIfAborted()
    return fetch(`${connection.apiUrl}${path}`, {
      headers: { Authorization: `Bearer ${connection.apiToken}` },
      ...(signal ? { signal } : {}),
    })
  }
  const response = await request({ apiUrl, apiToken })
  signal?.throwIfAborted()
  if (response.status !== 401 || !reauthenticate) return response
  return request(await reauthenticate(apiToken))
}

type HistoryEvent = Extract<InboundEvent, { event:
  | "user_message" | "message" | "file_edit" | "delta" | "stream_end"
  | "reasoning_delta" | "reasoning_end" | "context_compaction" | "turn_end"
}> & { round_usages?: TokenUsage[] }

interface ThreadPage {
  events: HistoryEvent[]
  page?: { has_more_before?: boolean; before_cursor?: string; user_message_offset?: number }
}

function parseHistoryEvents(values: unknown[]): HistoryEvent[] {
  const events: HistoryEvent[] = []
  const seen = new Set<string>()
  for (const value of values) {
    const event = decodeInboundEvent(value)
    if (!event || !isRecord(value) || !optional(value.turn_id, "string")) {
      throw new Error("Invalid history event")
    }
    if (typeof value.projection_id === "string") {
      if (seen.has(value.projection_id)) continue
      seen.add(value.projection_id)
    }
    switch (event.event) {
      case "user_message":
      case "message":
      case "file_edit":
      case "delta":
      case "stream_end":
      case "reasoning_delta":
      case "reasoning_end":
      case "context_compaction":
        events.push(event)
        break
      case "turn_end":
        events.push({
          ...event,
          round_usages: Array.isArray(value.round_usages) ? value.round_usages.filter(isTokenUsage) : [],
        })
        break
      default:
        throw new Error(`Unsupported history event: ${event.event}`)
    }
  }
  return events
}

async function fetchThreadPage(
  apiUrl: string,
  apiToken: string,
  chatId: string,
  beforeCursor?: string | null,
  reauthenticate?: ApiReauthenticator,
  signal?: AbortSignal,
): Promise<ThreadPage> {
  if (!apiUrl || !apiToken) return { events: [] }
  const key = encodeURIComponent(`websocket:${chatId}`)
  const params = new URLSearchParams({ limit: "120", direction: "latest" })
  if (beforeCursor) params.set("before", beforeCursor)
  const response = await fetchApi(
    apiUrl,
    apiToken,
    `/api/sessions/${key}/webui-thread?${params}`,
    reauthenticate,
    signal,
  )
  if (response.status === 404) return { events: [] }
  if (!response.ok) throw new Error(`history request failed: HTTP ${response.status}`)
  const payload: unknown = await response.json()
  if (!isRecord(payload) || typeof payload.schemaVersion !== "number") {
    throw new Error("Invalid history response")
  }
  const page = isRecord(payload.page) ? payload.page : undefined
  const pagination = {
    has_more_before: page?.has_more_before === true,
    before_cursor: typeof page?.before_cursor === "string" ? page.before_cursor : undefined,
    user_message_offset: typeof page?.user_message_offset === "number" ? page.user_message_offset : undefined,
  }
  if (payload.projection === "events" && Array.isArray(payload.events)) {
    return { events: parseHistoryEvents(payload.events), page: pagination }
  }
  throw new Error("Unsupported history response format")
}

/** Same recent model-call samples and context boundary as the WebUI usage popover. */
export async function fetchSessionUsage(
  apiUrl: string,
  apiToken: string,
  chatId: string,
  reauthenticate?: ApiReauthenticator,
  signal?: AbortSignal,
): Promise<SessionUsageSnapshot> {
  const payload = await fetchThreadPage(apiUrl, apiToken, chatId, undefined, reauthenticate, signal)
  signal?.throwIfAborted()
  const snapshot: SessionUsageSnapshot = { context: null, rounds: [] }
  const seenTurns = new Set<unknown>()
  let contextResolved = false
  for (const event of [...payload.events].reverse()) {
    if (event.event === "context_compaction" && event.phase === "succeeded") contextResolved = true
    if (event.event !== "turn_end") continue
    const usage = event.usage
    if (!contextResolved && typeof usage?.context_tokens === "number"
      && Number.isFinite(usage.context_tokens) && usage.context_tokens >= 0) {
      const window = event.context_window_tokens
      snapshot.context = {
        tokens: usage.context_tokens,
        ...(typeof window === "number" && Number.isFinite(window) && window > 0
          ? { windowTokens: window } : {}),
      }
      contextResolved = true
    }
    const turnKey = event.turn_id || event
    if (seenTurns.has(turnKey)) continue
    seenTurns.add(turnKey)
    for (const round of [...(event.round_usages ?? [])].reverse()) {
      if (snapshot.rounds.length >= 8) break
      if (typeof round.prompt_tokens === "number"
        && Number.isFinite(round.prompt_tokens) && round.prompt_tokens > 0) {
        snapshot.rounds.push(round)
      }
    }
  }
  snapshot.rounds.reverse()
  return snapshot
}

export async function fetchHistory(
  apiUrl: string,
  apiToken: string,
  chatId: string,
  beforeCursor?: string | null,
  reauthenticate?: ApiReauthenticator,
): Promise<HistorySnapshot> {
  const payload = await fetchThreadPage(apiUrl, apiToken, chatId, beforeCursor, reauthenticate)
  let userIndex = typeof payload.page?.user_message_offset === "number"
    ? Math.max(0, payload.page.user_message_offset)
    : 0
  const messages: HistoryMessage[] = []
  let stream: { row: HistoryMessage; turnId?: string } | null = null
  let lastAnswer: { row: HistoryMessage; turnId?: string } | null = null
  for (const event of payload.events) {
    switch (event.event) {
      case "user_message": {
        if (event.starts_turn) stream = null
        const media = event.media_urls ?? []
        if (!event.text.trim() && !media.length) break
        userIndex += 1
        messages.push({
          role: "user", content: event.text,
          ...(media.length ? { media } : {}),
          ...(event.turn_id ? { turnId: event.turn_id } : {}),
        })
        lastAnswer = null
        break
      }
      case "delta":
      case "stream_end":
        if (!stream || stream.turnId !== event.turn_id) {
          const row: HistoryMessage = { role: "assistant", content: "", forkIndex: userIndex }
          messages.push(row)
          stream = { row, turnId: event.turn_id }
        }
        if (event.event === "delta") stream.row.content += event.text
        else if (event.text !== undefined) stream.row.content = event.text
        lastAnswer = stream
        if (event.event === "stream_end" && !(event.resuming && event.merge_next)) stream = null
        break
      case "message":
        if (event.kind === "reasoning") break
        if (event.kind === "tool_hint" || event.kind === "progress") {
          messages.push({
            role: "activity", content: event.text,
            ...(event.tool_events?.length ? { toolEvents: event.tool_events } : {}),
          })
        } else {
          // A final message can repeat the answer already saved by stream_end.
          if (stream && stream.turnId === event.turn_id) stream.row.content = event.text
          else if (!lastAnswer || lastAnswer.turnId !== event.turn_id || lastAnswer.row.content !== event.text) {
            const row: HistoryMessage = { role: "assistant", content: event.text, forkIndex: userIndex }
            messages.push(row)
            lastAnswer = { row, turnId: event.turn_id }
          }
          stream = null
        }
        break
      case "file_edit":
        if (event.edits.length) messages.push({ role: "activity", content: "", fileEdits: event.edits })
        break
      case "context_compaction":
        stream = null
        messages.push({
          role: "activity", content: "",
          compaction: { id: event.compaction_id, phase: event.phase },
        })
        break
      case "turn_end":
        stream = null
        lastAnswer = null
        break
      case "reasoning_delta":
      case "reasoning_end":
        break
    }
  }
  return {
    messages: messages.filter((row) => row.role !== "assistant" || row.content.trim()),
    hasMoreBefore: payload.page?.has_more_before === true,
    beforeCursor: typeof payload.page?.before_cursor === "string"
      ? payload.page.before_cursor
      : null,
    userMessageOffset: typeof payload.page?.user_message_offset === "number"
      ? Math.max(0, payload.page.user_message_offset)
      : 0,
  }
}

export async function fetchSessionContext(
  apiUrl: string,
  apiToken: string,
  chatId: string,
  reauthenticate?: ApiReauthenticator,
): Promise<SessionContextSnapshot | null> {
  if (!apiUrl || !apiToken) return null
  const key = encodeURIComponent(`websocket:${chatId}`)
  const response = await fetchApi(
    apiUrl,
    apiToken,
    `/api/sessions/${key}/context`,
    reauthenticate,
  )
  if (response.status === 404) return null
  if (!response.ok) throw new Error(`context request failed: HTTP ${response.status}`)
  const value = await response.json() as Record<string, unknown>
  const number = (key: string) => typeof value[key] === "number" ? value[key] as number : 0
  return {
    totalMessages: number("total_messages"),
    archivedMessages: number("archived_messages"),
    replayMessages: number("replay_messages"),
    estimatedReplayTokens: number("estimated_replay_tokens"),
    estimatedSummaryTokens: number("estimated_summary_tokens"),
    estimatedSessionTokens: number("estimated_session_tokens"),
    archivedSummary: typeof value.archived_summary === "string" ? value.archived_summary : null,
    archivedSummaryAt: typeof value.archived_summary_at === "string"
      ? value.archived_summary_at
      : null,
    lastUsage: isTokenUsage(value.last_usage) ? value.last_usage : null,
  }
}

export async function fetchSlashCommands(
  apiUrl: string,
  apiToken: string,
  reauthenticate?: ApiReauthenticator,
): Promise<SlashCommand[]> {
  if (!apiUrl || !apiToken) return []
  const response = await fetchApi(apiUrl, apiToken, "/api/commands", reauthenticate)
  if (!response.ok) throw new Error(`command request failed: HTTP ${response.status}`)
  const payload = await response.json() as { commands?: unknown[] }
  return (payload.commands || []).flatMap((value) => {
    if (
      !isRecord(value)
      || typeof value.command !== "string"
      || typeof value.lifecycle !== "string"
      || !SLASH_COMMAND_LIFECYCLES.has(value.lifecycle)
    ) return []
    return [{
      command: value.command,
      title: typeof value.title === "string" ? value.title : value.command,
      description: typeof value.description === "string" ? value.description : "",
      argHint: typeof value.arg_hint === "string" ? value.arg_hint : "",
      lifecycle: value.lifecycle as SlashCommandLifecycle,
      acceptsArgs: value.accepts_args === true,
    }]
  })
}

export async function fetchAvailableSkills(
  apiUrl: string,
  apiToken: string,
  reauthenticate?: ApiReauthenticator,
): Promise<SkillCandidate[]> {
  if (!apiUrl || !apiToken) return []
  const response = await fetchApi(apiUrl, apiToken, "/api/webui/skills", reauthenticate)
  if (!response.ok) throw new Error(`skill request failed: HTTP ${response.status}`)
  const payload = await response.json() as { skills?: unknown[] }
  return (payload.skills || []).flatMap((value) => {
    if (
      !isRecord(value)
      || typeof value.name !== "string"
      || !SKILL_REFERENCE_NAME.test(value.name)
      || value.enabled !== true
      || value.available !== true
    ) return []
    return [{
      name: value.name,
      description: typeof value.description === "string" ? value.description : value.name,
      source: typeof value.source === "string" ? value.source : "unknown",
    }]
  })
}

export async function fetchRuntimeControls(
  apiUrl: string,
  apiToken: string,
  reauthenticate?: ApiReauthenticator,
): Promise<RuntimeControls> {
  if (!apiUrl || !apiToken) return { modelPresets: [], canUseFullAccess: false }
  const [settingsResponse, workspacesResponse] = await Promise.all([
    fetchApi(apiUrl, apiToken, "/api/settings", reauthenticate),
    fetchApi(apiUrl, apiToken, "/api/workspaces", reauthenticate).catch(() => null),
  ])
  if (!settingsResponse.ok) {
    throw new Error(`settings request failed: HTTP ${settingsResponse.status}`)
  }
  const settings = await settingsResponse.json() as { model_presets?: unknown[] }
  const workspaces = workspacesResponse?.ok
    ? await workspacesResponse.json() as { controls?: unknown }
    : {}
  const modelPresets = (settings.model_presets || []).flatMap((value) => {
    if (!isRecord(value) || typeof value.name !== "string" || typeof value.model !== "string") {
      return []
    }
    const name = value.name.trim()
    return name ? [{ name, model: value.model.trim() }] : []
  })
  const controls = isRecord(workspaces.controls) ? workspaces.controls : {}
  return {
    modelPresets,
    canUseFullAccess: controls.can_use_full_access === true,
  }
}

export async function fetchSessions(
  apiUrl: string,
  apiToken: string,
  reauthenticate?: ApiReauthenticator,
): Promise<SessionSummary[]> {
  if (!apiUrl || !apiToken) return []
  const [response, sidebarResponse] = await Promise.all([
    fetchApi(apiUrl, apiToken, "/api/sessions", reauthenticate),
    fetchApi(apiUrl, apiToken, "/api/webui/sidebar-state", reauthenticate).catch(() => null),
  ])
  if (!response.ok) throw new Error(`session request failed: HTTP ${response.status}`)
  const payload = await response.json() as { sessions?: unknown[] }
  let sidebar: Record<string, unknown> = {}
  if (sidebarResponse?.ok) {
    try {
      const value: unknown = await sidebarResponse.json()
      if (isRecord(value)) sidebar = value
    } catch {
      // Session navigation remains available against older or damaged sidebar state.
    }
  }
  const pinned = new Set(Array.isArray(sidebar.pinned_keys) ? sidebar.pinned_keys : [])
  const archived = new Set(Array.isArray(sidebar.archived_keys) ? sidebar.archived_keys : [])
  const titles = isRecord(sidebar.title_overrides) ? sidebar.title_overrides : {}
  return (payload.sessions || []).flatMap((value) => {
    if (!isRecord(value) || typeof value.key !== "string" || !value.key.startsWith("websocket:")) {
      return []
    }
    const chatId = value.key.slice("websocket:".length)
    if (!chatId) return []
    const titleOverride = titles[value.key]
    return [{
      chatId,
      title: typeof titleOverride === "string"
        ? titleOverride
        : typeof value.title === "string" ? value.title : "",
      preview: typeof value.preview === "string" ? value.preview : "",
      createdAt: typeof value.created_at === "string" ? value.created_at : null,
      updatedAt: typeof value.updated_at === "string" ? value.updated_at : null,
      runStartedAt: typeof value.run_started_at === "number" ? value.run_started_at : null,
      modelPreset: typeof value.model_preset === "string" && value.model_preset.trim()
        ? value.model_preset.trim()
        : null,
      ...(isRecoveryState(value.recovery_state)
        ? { recoveryState: value.recovery_state }
        : {}),
      ...(isWorkspaceScope(value.workspace_scope) ? { workspaceScope: value.workspace_scope } : {}),
      pinned: pinned.has(value.key),
      archived: archived.has(value.key),
    }]
  })
}

function sessionMentionName(session: SessionSummary): string {
  const label = (session.title || session.preview || "session")
    .normalize("NFKC")
    .replace(/\s+/gu, "-")
    .replace(/[^\p{L}\p{N}_-]+/gu, "")
    .replace(/-+/gu, "-")
    .replace(/^-|-$/gu, "")
  return Array.from(label || "session").slice(0, 40).join("")
}

/** Installed capabilities and saved chats share one mention namespace. */
export async function fetchMentionCandidates(
  apiUrl: string,
  apiToken: string,
  reauthenticate?: ApiReauthenticator,
): Promise<MentionCandidate[]> {
  if (!apiUrl || !apiToken) return []
  const [sessions, appsResponse, mcpResponse] = await Promise.all([
    fetchSessions(apiUrl, apiToken, reauthenticate),
    fetchApi(
      apiUrl,
      apiToken,
      "/api/settings/cli-apps?installed_only=1",
      reauthenticate,
    ).catch(() => null),
    fetchApi(apiUrl, apiToken, "/api/settings/mcp-presets", reauthenticate).catch(() => null),
  ])
  const used = new Set<string>()
  const uniqueName = (raw: string) => {
    const base = raw || "session"
    let name = base
    let suffix = 2
    while (used.has(name.toLocaleLowerCase())) name = `${base}-${suffix++}`
    used.add(name.toLocaleLowerCase())
    return name
  }
  const candidates: MentionCandidate[] = []
  if (appsResponse?.ok) {
    const payload = await appsResponse.json() as { apps?: unknown[] }
    for (const value of payload.apps || []) {
      if (!isRecord(value) || value.installed !== true || typeof value.name !== "string") continue
      const name = uniqueName(value.name)
      candidates.push({
        kind: "cli",
        name,
        ...(name === value.name ? {} : { targetName: value.name }),
        displayName: typeof value.display_name === "string" ? value.display_name : name,
        description: typeof value.description === "string" ? value.description : "CLI app",
      })
    }
  }
  if (mcpResponse?.ok) {
    const payload = await mcpResponse.json() as { presets?: unknown[] }
    for (const value of payload.presets || []) {
      if (
        !isRecord(value)
        || value.installed !== true
        || value.configured !== true
        || typeof value.name !== "string"
      ) continue
      const name = uniqueName(value.name)
      candidates.push({
        kind: "mcp",
        name,
        ...(name === value.name ? {} : { targetName: value.name }),
        displayName: typeof value.display_name === "string" ? value.display_name : name,
        description: typeof value.description === "string" ? value.description : "MCP server",
      })
    }
  }
  for (const session of sessions) {
    const name = uniqueName(sessionMentionName(session))
    candidates.push({
      kind: "session",
      name,
      displayName: sessionLabelForMention(session),
      description: session.preview || "Saved session",
      session: {
        name,
        session_key: `websocket:${session.chatId}`,
        title: session.title || undefined,
      },
    })
  }
  return candidates
}

function sessionLabelForMention(session: SessionSummary): string {
  return (session.title || session.preview || "Untitled chat").replace(/\s+/gu, " ").trim()
}
