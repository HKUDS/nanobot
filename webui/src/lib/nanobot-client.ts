import type {
  ConnectionStatus,
  InboundEvent,
  Outbound,
  OutboundCliAppMention,
  OutboundMcpPresetMention,
  OutboundMedia,
  GoalStateWsPayload,
  WorkspaceScopePayload,
} from "./types";
import { createHostWebSocket } from "./runtime";

/** WebSocket readyState constants, referenced by value to stay portable
 * across runtimes that don't expose a global ``WebSocket`` (tests, SSR). */
const WS_OPEN = 1;
const WS_CLOSING = 2;
const HOST_SOCKET_URL_PREFIX = "nanobot-host://";

function createDefaultSocket(url: string): WebSocket {
  if (url.startsWith(HOST_SOCKET_URL_PREFIX)) {
    return createHostWebSocket(url);
  }
  return new WebSocket(url);
}

/** Inbound WebSocket ``console.log`` / parse-failure ``console.warn``.
 *
 * - **Dev** (non-production bundle): **on by default** — messages appear at default log level.
 * - **Production**: off unless ``localStorage.setItem('nanobot_debug_ws','1')`` (or ``true``).
 * - **Silence anywhere**: ``localStorage.setItem('nanobot_debug_ws','0')`` (or ``false`` / ``off``).
 * Values are read on every frame; no reload needed.
 */
function wsInboundDebugEnabled(): boolean {
  if (typeof globalThis === "undefined") return false;
  try {
    if (import.meta.env.MODE === "test") return false;
    const ls = (globalThis as unknown as { localStorage?: Storage }).localStorage;
    const raw = ls?.getItem("nanobot_debug_ws")?.trim().toLowerCase() ?? "";
    if (raw === "0" || raw === "false" || raw === "off" || raw === "no") {
      return false;
    }
    if (raw === "1" || raw === "true" || raw === "on" || raw === "yes") {
      return true;
    }
    return !import.meta.env.PROD;
  } catch {
    return !import.meta.env.PROD;
  }
}

/** Shorten streaming text fields so logging stays usable for huge deltas. */
function summarizeInboundWsPayload(ev: InboundEvent): unknown {
  const kind = (ev as { event?: string }).event;
  if (kind !== "delta" && kind !== "reasoning_delta") return ev;
  const row = { ...(ev as object) } as Record<string, unknown>;
  const text = typeof row.text === "string" ? row.text : "";
  const max = 240;
  if (text.length > max) {
    row.text = `${text.slice(0, max)}… (${text.length} chars)`;
  }
  return row;
}

type Unsubscribe = () => void;
type EventHandler = (ev: InboundEvent) => void;
type StatusHandler = (status: ConnectionStatus) => void;
type RuntimeModelHandler = (modelName: string | null, modelPreset?: string | null) => void;
type SessionUpdateScope = "metadata" | "thread" | string;
type SessionUpdateHandler = (
  chatId: string,
  scope?: SessionUpdateScope,
  workspaceScope?: WorkspaceScopePayload,
) => void;
type RunStatusHandler = (chatId: string, startedAt: number | null) => void;

/** Structured errors surfaced to the UI.
 *
 * Most entries are transport-level or protocol-level faults. Workspace scope
 * rejections are server application errors promoted here because they affect
 * controls outside the message stream and must be visible immediately.
 */
export type StreamError =
  /** Server rejected the inbound frame as too large (WS close code 1009).
   * This is the transport fallback after text and attachment policies have
   * already been checked independently. */
  | { kind: "message_too_big"; chatId?: string; turnId?: string }
  | {
      kind: "workspace_scope_rejected";
      reason?: string;
      chatId?: string;
      turnId?: string;
    }
  | {
      kind: "turn_rejected";
      detail?: string;
      reason?: string;
      chatId: string;
      turnId: string;
    };

type ErrorHandler = (error: StreamError) => void;

interface PendingRequest<T> {
  resolve: (value: T) => void;
  reject: (err: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

const SYSTEM_COMMAND_TURN_PREFIX = "webui-system:";
const TURN_REJECTION_DETAILS = new Set([
  "access_denied",
  "attachment_rejected",
  "message_rejected",
  "missing content",
  "workspace_scope_rejected",
]);

export function isSystemCommandTurnId(value: string | null | undefined): value is string {
  return typeof value === "string" && value.startsWith(SYSTEM_COMMAND_TURN_PREFIX);
}

export interface NanobotClientOptions {
  url: string;
  reconnect?: boolean;
  /** Maximum UTF-8 bytes accepted for one websocket message. */
  maxFrameBytes?: number;
  /** Called when a connection drops so the app can refresh its token. */
  onReauth?: () => Promise<string | null>;
  /** Inject a custom WebSocket factory (used by unit tests). */
  socketFactory?: (url: string) => WebSocket;
  /** Delay-cap for reconnect backoff (ms). */
  maxBackoffMs?: number;
}

export interface CanonicalRunSnapshot {
  /** User turn ids present in the canonical transcript page. */
  observedTurnIds: readonly string[];
  /** Whether the server still considers the transcript tail active. */
  hasPendingToolCalls: boolean;
  /** Exact active turn when supplied by a current gateway. */
  activeTurnId?: string | null;
}

type PendingMessageState = "queued" | "sent" | "unknown" | "accepted";

interface PendingMessageSend {
  chatId: string;
  turnId: string;
  startsNewRun: boolean;
  state: PendingMessageState;
}

/**
 * Singleton WebSocket client that multiplexes chat streams.
 *
 * One socket carries many chat_ids: the server tags every outbound event with
 * ``chat_id``, and this class fans those events out to handlers registered
 * per chat. Reconnects are transparent and re-attach every known chat_id.
 */
export class NanobotClient {
  private socket: WebSocket | null = null;
  private statusHandlers = new Set<StatusHandler>();
  private runtimeModelHandlers = new Set<RuntimeModelHandler>();
  private sessionUpdateHandlers = new Set<SessionUpdateHandler>();
  private runStatusHandlers = new Set<RunStatusHandler>();
  private errorHandlers = new Set<ErrorHandler>();
  // chat_id -> handlers listening on it
  private chatHandlers = new Map<string, Set<EventHandler>>();
  /** Inbound frames received while no subscriber is registered (e.g. user switched away). */
  private pendingInboundByChat = new Map<string, InboundEvent[]>();
  private static readonly PENDING_INBOUND_MAX = 2000;
  // chat_ids we've attached to since connect; re-attached after reconnects
  private knownChats = new Set<string>();
  /** Wall-clock run strip: updated from ``goal_status`` even with no ``onChat`` subscriber. */
  private runStartedAtByChatId = new Map<string, number>();
  /** Per-turn clocks let a rejected newer turn fall back without borrowing its timer. */
  private runStartedAtByTurnKey = new Map<string, number>();
  /** Monotonic per-chat generation for local sends and observed backend runs. */
  private runGenerationByChatId = new Map<string, number>();
  /** Turn associated with the latest generation, retained after idle for reconciliation. */
  private latestRunTurnIdByChatId = new Map<string, string>();
  /** Submitted or running turns not yet closed by lifecycle or canonical state. */
  private unsettledRunTurnIdsByChatId = new Map<string, Set<string>>();
  /** Correlated WebUI sends retained until protocol/canonical disposition. */
  private pendingMessageSends = new Map<string, PendingMessageSend>();
  /** Message sends written to the current socket but not yet acknowledged. */
  private socketPendingMessageSendKeys = new Set<string>();
  /** Last application frame written, used only for conservative 1009 attribution. */
  private lastSocketMessageSendKey: string | null = null;
  /** Canonically completed turns whose delayed websocket frames must be ignored. */
  private canonicalCompletedTurnIdsByChatId = new Map<string, Set<string>>();
  private static readonly COMPLETED_TURN_FENCE_MAX = 256;
  /** Latest ``goal_state`` snapshot per ``chat_id`` (multi-session isolation). */
  private goalStateByChatId = new Map<string, GoalStateWsPayload>();
  private pendingNewChat: PendingRequest<string> | null = null;
  private pendingTranscriptions = new Map<string, PendingRequest<string>>();
  private pendingSystemCommands = new Map<string, PendingRequest<void>>();
  // Frames queued while the socket is not yet OPEN
  private sendQueue: Outbound[] = [];
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly shouldReconnect: boolean;
  private readonly maxBackoffMs: number;
  private maxFrameBytes: number | undefined;
  private socketFactory: (url: string) => WebSocket;
  private currentUrl: string;
  private status_: ConnectionStatus = "idle";
  private readyChatId: string | null = null;
  // Set by ``close()`` so the onclose handler knows the drop was intentional
  // and must not schedule a reconnect or flip status back to "reconnecting".
  private intentionallyClosed = false;

  constructor(private options: NanobotClientOptions) {
    this.shouldReconnect = options.reconnect ?? true;
    this.maxBackoffMs = options.maxBackoffMs ?? 15_000;
    this.maxFrameBytes = this.normalizeMaxFrameBytes(options.maxFrameBytes);
    this.socketFactory = options.socketFactory ?? createDefaultSocket;
    this.currentUrl = options.url;
  }

  get status(): ConnectionStatus {
    return this.status_;
  }

  get defaultChatId(): string | null {
    return this.readyChatId;
  }

  /** Swap the URL (e.g. after fetching a fresh token) then reconnect. */
  updateUrl(url: string, socketFactory?: (url: string) => WebSocket): void {
    this.currentUrl = url;
    if (socketFactory) {
      this.socketFactory = socketFactory;
    }
  }

  onStatus(handler: StatusHandler): Unsubscribe {
    this.statusHandlers.add(handler);
    handler(this.status_);
    return () => {
      this.statusHandlers.delete(handler);
    };
  }

  onRuntimeModelUpdate(handler: RuntimeModelHandler): Unsubscribe {
    this.runtimeModelHandlers.add(handler);
    return () => {
      this.runtimeModelHandlers.delete(handler);
    };
  }

  onSessionUpdate(handler: SessionUpdateHandler): Unsubscribe {
    this.sessionUpdateHandlers.add(handler);
    return () => {
      this.sessionUpdateHandlers.delete(handler);
    };
  }

  onRunStatus(handler: RunStatusHandler): Unsubscribe {
    this.runStatusHandlers.add(handler);
    for (const [chatId, startedAt] of this.runStartedAtByChatId) {
      handler(chatId, startedAt);
    }
    return () => {
      this.runStatusHandlers.delete(handler);
    };
  }

  /** Subscribe to transport-level faults (see :type:`StreamError`). */
  onError(handler: ErrorHandler): Unsubscribe {
    this.errorHandlers.add(handler);
    return () => {
      this.errorHandlers.delete(handler);
    };
  }

  /** Last ``goal_status`` ``started_at`` (unix sec) for *chatId*, if the turn is running. */
  getRunStartedAt(chatId: string): number | null {
    const v = this.runStartedAtByChatId.get(chatId);
    return v === undefined ? null : v;
  }

  /** Refresh transport policy after bootstrap token renewal. */
  updateMaxFrameBytes(maxFrameBytes?: number): void {
    this.maxFrameBytes = this.normalizeMaxFrameBytes(maxFrameBytes);
  }

  /** Generation captured when an HTTP thread reconciliation starts. */
  getRunGeneration(chatId: string): number {
    return this.runGenerationByChatId.get(chatId) ?? 0;
  }

  /** Whether a locally submitted lifecycle turn still lacks a terminal disposition. */
  hasUnsettledRun(chatId: string): boolean {
    return (this.unsettledRunTurnIdsByChatId.get(chatId)?.size ?? 0) > 0;
  }

  private normalizeMaxFrameBytes(value: number | undefined): number | undefined {
    if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
      return undefined;
    }
    return Math.floor(value);
  }

  private canonicalTurnWillSettle(
    chatId: string,
    turnId: string,
    completed: ReadonlySet<string>,
    observed: ReadonlySet<string>,
    snapshot?: CanonicalRunSnapshot,
  ): boolean {
    if (completed.has(turnId)) return true;
    if (!snapshot || snapshot.activeTurnId === turnId) return false;
    if (snapshot.hasPendingToolCalls) return false;
    if (observed.has(turnId)) return true;
    const pending = this.pendingMessageSends.get(this.runSendKey(chatId, turnId));
    return pending?.state === "unknown" || pending?.state === "accepted";
  }

  private settleNonLifecycleCanonicalSends(
    chatId: string,
    completed: ReadonlySet<string>,
    observed: ReadonlySet<string>,
    snapshot?: CanonicalRunSnapshot,
  ): void {
    for (const pending of [...this.pendingMessageSends.values()]) {
      if (pending.chatId !== chatId || pending.startsNewRun) continue;
      if (!this.canonicalTurnWillSettle(
        chatId,
        pending.turnId,
        completed,
        observed,
        snapshot,
      )) continue;
      this.clearPendingMessageSend(chatId, pending.turnId);
    }
  }

  private prunePendingInboundTurn(chatId: string, turnId: string): void {
    const pending = this.pendingInboundByChat.get(chatId);
    if (!pending) return;
    const remaining = pending.filter((event) => (
      !("turn_id" in event)
      || event.turn_id !== turnId
    ));
    if (remaining.length > 0) this.pendingInboundByChat.set(chatId, remaining);
    else this.pendingInboundByChat.delete(chatId);
  }

  /**
   * Pure preflight for canonical reconciliation.
   *
   * Unlike ``reconcileCanonicalCompletion``, this does not add completion
   * fences, prune queued frames, settle turns, or emit run-status updates.
   */
  canReconcileCanonicalCompletion(
    chatId: string,
    expectedRunGeneration: number,
    completedTurnIds: readonly string[],
    snapshot?: CanonicalRunSnapshot,
  ): boolean {
    const completed = new Set(this.canonicalCompletedTurnIdsByChatId.get(chatId));
    for (const turnId of completedTurnIds) {
      if (turnId) completed.add(turnId);
    }
    const observed = new Set(
      snapshot?.observedTurnIds.filter((turnId) => turnId.length > 0) ?? [],
    );
    const willSettle = (turnId: string): boolean => this.canonicalTurnWillSettle(
      chatId,
      turnId,
      completed,
      observed,
      snapshot,
    );
    const latestRunTurnId = this.latestRunTurnIdByChatId.get(chatId);
    const latestRunIsRepresented = (
      typeof latestRunTurnId === "string"
      && (
        completed.has(latestRunTurnId)
        || (
          observed.has(latestRunTurnId)
          && willSettle(latestRunTurnId)
        )
      )
    );
    const unsettledTurnIds = this.unsettledRunTurnIdsByChatId.get(chatId);
    const hasUnrepresentedTurn = (
      unsettledTurnIds !== undefined
      && Array.from(unsettledTurnIds).some((turnId) => !willSettle(turnId))
    );
    const hasUnidentifiedActiveRun = (
      this.runStartedAtByChatId.has(chatId)
      && latestRunTurnId === undefined
      && (snapshot === undefined || snapshot.hasPendingToolCalls)
    );
    if (hasUnrepresentedTurn || hasUnidentifiedActiveRun) return false;
    return (
      this.getRunGeneration(chatId) === expectedRunGeneration
      || latestRunIsRepresented
    );
  }

  /**
   * Atomically accept an HTTP snapshot as completed if no unrepresented run
   * started while the request was in flight.
   *
   * Completed turn ids are fenced even when the snapshot loses the generation
   * race: delayed websocket frames for older turns must never mutate newer UI.
   */
  reconcileCanonicalCompletion(
    chatId: string,
    expectedRunGeneration: number,
    completedTurnIds: readonly string[],
    snapshot?: CanonicalRunSnapshot,
  ): boolean {
    const fences = this.canonicalCompletedTurnIdsByChatId.get(chatId) ?? new Set<string>();
    for (const turnId of completedTurnIds) {
      if (!turnId) continue;
      fences.add(turnId);
    }
    while (fences.size > NanobotClient.COMPLETED_TURN_FENCE_MAX) {
      const oldest = fences.values().next().value;
      if (typeof oldest !== "string") break;
      fences.delete(oldest);
    }
    if (fences.size > 0) this.canonicalCompletedTurnIdsByChatId.set(chatId, fences);
    const pendingInbound = this.pendingInboundByChat.get(chatId);
    if (pendingInbound) {
      const remaining = pendingInbound.filter((event) => {
        const turnId = "turn_id" in event && typeof event.turn_id === "string"
          ? event.turn_id
          : null;
        return turnId === null || !fences.has(turnId);
      });
      if (remaining.length > 0) this.pendingInboundByChat.set(chatId, remaining);
      else this.pendingInboundByChat.delete(chatId);
    }

    if (!this.canReconcileCanonicalCompletion(
      chatId,
      expectedRunGeneration,
      [],
      snapshot,
    )) {
      return false;
    }

    const completed = new Set(fences);
    const observed = new Set(
      snapshot?.observedTurnIds.filter((turnId) => turnId.length > 0) ?? [],
    );
    const unsettledTurnIds = this.unsettledRunTurnIdsByChatId.get(chatId);
    if (unsettledTurnIds) {
      for (const turnId of [...unsettledTurnIds]) {
        if (!this.canonicalTurnWillSettle(
          chatId,
          turnId,
          completed,
          observed,
          snapshot,
        )) continue;
        unsettledTurnIds.delete(turnId);
        this.clearPendingMessageSend(chatId, turnId);
        this.runStartedAtByTurnKey.delete(this.runSendKey(chatId, turnId));
      }
      if (unsettledTurnIds.size === 0) this.unsettledRunTurnIdsByChatId.delete(chatId);
    }
    this.settleNonLifecycleCanonicalSends(chatId, completed, observed, snapshot);
    if (this.runStartedAtByChatId.delete(chatId)) {
      this.emitRunStatus(chatId, null);
    }
    return true;
  }

  /** Last ``goal_state`` payload for *chatId*, if any frame has arrived this connection. */
  getGoalState(chatId: string): GoalStateWsPayload | undefined {
    return this.goalStateByChatId.get(chatId);
  }

  private advanceRunGeneration(chatId: string, turnId?: string): void {
    this.runGenerationByChatId.set(chatId, this.getRunGeneration(chatId) + 1);
    if (turnId) {
      this.latestRunTurnIdByChatId.set(chatId, turnId);
      const unsettled = this.unsettledRunTurnIdsByChatId.get(chatId) ?? new Set<string>();
      unsettled.add(turnId);
      this.unsettledRunTurnIdsByChatId.set(chatId, unsettled);
    } else {
      this.latestRunTurnIdByChatId.delete(chatId);
    }
  }

  private settleRunTurn(chatId: string, turnId?: string): void {
    if (!turnId) return;
    this.clearPendingMessageSend(chatId, turnId);
    this.runStartedAtByTurnKey.delete(this.runSendKey(chatId, turnId));
    const unsettled = this.unsettledRunTurnIdsByChatId.get(chatId);
    if (!unsettled) return;
    unsettled.delete(turnId);
    if (unsettled.size === 0) this.unsettledRunTurnIdsByChatId.delete(chatId);
  }

  private runSendKey(chatId: string, turnId: string): string {
    return `${chatId}\u0000${turnId}`;
  }

  private trackPendingMessageSend(
    chatId: string,
    turnId: string,
    startsNewRun: boolean,
  ): void {
    const key = this.runSendKey(chatId, turnId);
    this.pendingMessageSends.set(key, {
      chatId,
      turnId,
      startsNewRun,
      state: "queued",
    });
  }

  private clearPendingMessageSend(chatId: string, turnId: string): void {
    const key = this.runSendKey(chatId, turnId);
    this.pendingMessageSends.delete(key);
    this.socketPendingMessageSendKeys.delete(key);
    this.sendQueue = this.sendQueue.filter((frame) => !(
      frame.type === "message"
      && frame.chat_id === chatId
      && frame.turn_id === turnId
    ));
  }

  private recordRunAcceptance(chatId: string, turnId?: string): void {
    if (!turnId) return;
    const key = this.runSendKey(chatId, turnId);
    const pending = this.pendingMessageSends.get(key);
    if (!pending) return;
    this.socketPendingMessageSendKeys.delete(key);
    if (!pending.startsNewRun) {
      this.pendingMessageSends.delete(key);
      return;
    }
    pending.state = "accepted";
  }

  private recordRunRejection(chatId: string, turnId?: string): void {
    if (!turnId) return;
    const rejectedLatest = this.latestRunTurnIdByChatId.get(chatId) === turnId;
    this.settleRunTurn(chatId, turnId);
    this.prunePendingInboundTurn(chatId, turnId);
    if (!rejectedLatest) return;

    const unsettled = this.unsettledRunTurnIdsByChatId.get(chatId);
    const previousTurnId = unsettled ? Array.from(unsettled).at(-1) : undefined;
    if (previousTurnId) {
      this.latestRunTurnIdByChatId.set(chatId, previousTurnId);
      const previousStartedAt = this.runStartedAtByTurnKey.get(
        this.runSendKey(chatId, previousTurnId),
      );
      const currentStartedAt = this.runStartedAtByChatId.get(chatId);
      if (previousStartedAt === undefined) {
        if (this.runStartedAtByChatId.delete(chatId)) {
          this.emitRunStatus(chatId, null);
        }
      } else {
        this.runStartedAtByChatId.set(chatId, previousStartedAt);
        if (currentStartedAt !== previousStartedAt) {
          this.emitRunStatus(chatId, previousStartedAt);
        }
      }
      return;
    }
    this.latestRunTurnIdByChatId.delete(chatId);
    if (this.runStartedAtByChatId.delete(chatId)) {
      this.emitRunStatus(chatId, null);
    }
  }

  private legacyRejectionTarget(ev: Extract<InboundEvent, { event: "error" }>): {
    chatId: string;
    turnId: string;
  } | null {
    if (!ev.detail || !TURN_REJECTION_DETAILS.has(ev.detail)) return null;
    if (
      ev.detail === "workspace_scope_rejected"
      && ev.chat_id === undefined
      && this.pendingNewChat
    ) return null;
    const candidates = [...this.pendingMessageSends.values()].filter((pending) => (
      // A legacy error can only reject a frame currently awaiting its first
      // server disposition. Accepted or prior-connection unknown sends are
      // not safe candidates for an uncorrelated frame.
      pending.state === "sent"
      && (ev.chat_id === undefined || pending.chatId === ev.chat_id)
    ));
    if (candidates.length !== 1) return null;
    const [candidate] = candidates;
    if (
      this.lastSocketMessageSendKey
      !== this.runSendKey(candidate.chatId, candidate.turnId)
    ) return null;
    return { chatId: candidate.chatId, turnId: candidate.turnId };
  }

  private uniqueUnsettledTurnId(chatId: string): string | null {
    const unsettled = this.unsettledRunTurnIdsByChatId.get(chatId);
    if (!unsettled || unsettled.size !== 1) return null;
    return unsettled.values().next().value ?? null;
  }

  private isCanonicalCompletedTurnEvent(chatId: string, ev: InboundEvent): boolean {
    const turnId = "turn_id" in ev && typeof ev.turn_id === "string" ? ev.turn_id : null;
    return (
      turnId !== null
      && this.canonicalCompletedTurnIdsByChatId.get(chatId)?.has(turnId) === true
    );
  }

  private isSupersededRunCompletion(chatId: string, ev: InboundEvent): boolean {
    if (
      ev.event !== "turn_end"
      && !(ev.event === "goal_status" && ev.status === "idle")
    ) {
      return false;
    }
    const turnId = "turn_id" in ev && typeof ev.turn_id === "string" ? ev.turn_id : undefined;
    const latestRunTurnId = this.latestRunTurnIdByChatId.get(chatId);
    if (turnId === undefined && latestRunTurnId !== undefined) return true;
    return (
      turnId !== undefined
      && latestRunTurnId !== undefined
      && turnId !== latestRunTurnId
    );
  }

  private recordRunCompletion(chatId: string, turnId?: string): void {
    this.settleRunTurn(chatId, turnId);
    const latestRunTurnId = this.latestRunTurnIdByChatId.get(chatId);
    const closesCurrentRun = latestRunTurnId === undefined || turnId === latestRunTurnId;
    if (closesCurrentRun && this.runStartedAtByChatId.delete(chatId)) {
      this.emitRunStatus(chatId, null);
    }
  }

  private recordGoalStatusForRunStrip(chatId: string, ev: InboundEvent): void {
    if (ev.event === "turn_end") {
      this.recordRunCompletion(chatId, ev.turn_id);
      return;
    }
    if (ev.event !== "goal_status") return;
    if (ev.status === "running" && typeof ev.started_at === "number") {
      this.advanceRunGeneration(chatId, ev.turn_id);
      if (ev.turn_id) {
        this.runStartedAtByTurnKey.set(
          this.runSendKey(chatId, ev.turn_id),
          ev.started_at,
        );
      }
      const previous = this.runStartedAtByChatId.get(chatId);
      this.runStartedAtByChatId.set(chatId, ev.started_at);
      if (previous !== ev.started_at) this.emitRunStatus(chatId, ev.started_at);
    } else {
      this.recordRunCompletion(chatId, ev.turn_id);
    }
  }

  private recordGoalStateSnapshot(chatId: string, ev: InboundEvent): void {
    if (ev.event === "goal_state") {
      this.goalStateByChatId.set(chatId, ev.goal_state);
      return;
    }
    if (ev.event === "turn_end" && ev.goal_state != null && typeof ev.goal_state === "object") {
      this.goalStateByChatId.set(chatId, ev.goal_state);
    }
  }

  /** Subscribe to events for a given chat_id. Auto-attaches on the next open. */
  onChat(chatId: string, handler: EventHandler): Unsubscribe {
    let handlers = this.chatHandlers.get(chatId);
    if (!handlers) {
      handlers = new Set();
      this.chatHandlers.set(chatId, handlers);
    }
    handlers.add(handler);
    const pending = this.pendingInboundByChat.get(chatId);
    if (pending !== undefined && pending.length > 0) {
      const flushed = pending.splice(0);
      this.pendingInboundByChat.delete(chatId);
      for (const ev of flushed) {
        handler(ev);
      }
    }
    this.attach(chatId);
    return () => {
      const current = this.chatHandlers.get(chatId);
      if (!current) return;
      current.delete(handler);
      if (current.size === 0) this.chatHandlers.delete(chatId);
    };
  }

  connect(): void {
    if (this.socket && this.socket.readyState < WS_CLOSING) return;
    this.intentionallyClosed = false;
    this.setStatus("connecting");
    const sock = this.socketFactory(this.currentUrl);
    this.socket = sock;
    sock.onopen = () => this.handleOpen();
    sock.onmessage = (ev) => this.handleMessage(ev);
    sock.onerror = () => this.setStatus("error");
    sock.onclose = (ev) => this.handleClose(ev);
  }

  close(): void {
    this.intentionallyClosed = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    const sock = this.socket;
    this.socket = null;
    try {
      sock?.close();
    } catch {
      // ignore
    }
    this.setStatus("closed");
  }

  /** Ask the server to provision a new chat_id; resolves with the assigned id. */
  newChat(timeoutMs: number = 5_000, workspaceScope?: WorkspaceScopePayload | null): Promise<string> {
    if (this.pendingNewChat) {
      return Promise.reject(new Error("newChat already in flight"));
    }
    return new Promise<string>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pendingNewChat = null;
        reject(new Error("newChat timed out"));
      }, timeoutMs);
      this.pendingNewChat = { resolve, reject, timer };
      this.queueSend({
        type: "new_chat",
        ...(workspaceScope ? { workspace_scope: workspaceScope } : {}),
      });
    });
  }

  transcribeAudio(
    dataUrl: string,
    options?: { durationMs?: number; timeoutMs?: number },
  ): Promise<string> {
    const requestId = crypto.randomUUID();
    const timeoutMs = options?.timeoutMs ?? 120_000;
    return new Promise<string>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pendingTranscriptions.delete(requestId);
        reject(new Error("transcription timed out"));
      }, timeoutMs);
      this.pendingTranscriptions.set(requestId, { resolve, reject, timer });
      this.queueSend({
        type: "transcribe_audio",
        request_id: requestId,
        data_url: dataUrl,
        ...(options?.durationMs !== undefined ? { duration_ms: options.durationMs } : {}),
      });
    });
  }

  /** Ask the server to create a non-destructive fork before a user-message index. */
  forkChat(
    sourceChatId: string,
    beforeUserIndex: number,
    title?: string,
    timeoutMs: number = 5_000,
  ): Promise<string> {
    if (this.pendingNewChat) {
      return Promise.reject(new Error("newChat already in flight"));
    }
    return new Promise<string>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pendingNewChat = null;
        reject(new Error("forkChat timed out"));
      }, timeoutMs);
      this.pendingNewChat = { resolve, reject, timer };
      this.queueSend({
        type: "fork_chat",
        source_chat_id: sourceChatId,
        before_user_index: beforeUserIndex,
        ...(title?.trim() ? { title: title.trim() } : {}),
      });
    });
  }

  attach(chatId: string): void {
    this.knownChats.add(chatId);
    if (this.socket?.readyState === WS_OPEN) {
      this.queueSend({ type: "attach", chat_id: chatId });
    }
  }

  sendMessage(
    chatId: string,
    content: string,
    media?: OutboundMedia[],
    options?: {
      cliApps?: OutboundCliAppMention[];
      mcpPresets?: OutboundMcpPresetMention[];
      quotedContext?: string;
      workspaceScope?: WorkspaceScopePayload | null;
      turnId?: string;
      /** False for side-channel or injected messages that do not own a lifecycle. */
      startsNewRun?: boolean;
    },
  ): void {
    this.knownChats.add(chatId);
    const frame: Outbound = {
      type: "message",
      chat_id: chatId,
      content,
      ...(media && media.length > 0 ? { media } : {}),
      ...(options?.cliApps?.length ? { cli_apps: options.cliApps } : {}),
      ...(options?.mcpPresets?.length ? { mcp_presets: options.mcpPresets } : {}),
      ...(options?.quotedContext?.trim() ? { quoted_context: options.quotedContext.trim() } : {}),
      ...(options?.workspaceScope ? { workspace_scope: options.workspaceScope } : {}),
      ...(options?.turnId ? { turn_id: options.turnId } : {}),
      webui: true,
    };
    if (!this.frameFitsTransport(frame)) {
      if (options?.turnId && isSystemCommandTurnId(options.turnId)) {
        this.rejectSystemCommand(options.turnId, "message_too_big");
      }
      this.emitError({
        kind: "message_too_big",
        chatId,
        ...(options?.turnId ? { turnId: options.turnId } : {}),
      });
      return;
    }
    if (options?.turnId && !isSystemCommandTurnId(options.turnId)) {
      const startsNewRun = options.startsNewRun !== false;
      if (startsNewRun) this.advanceRunGeneration(chatId, options.turnId);
      this.trackPendingMessageSend(chatId, options.turnId, startsNewRun);
    }
    this.queueSend(frame);
  }

  sendSystemCommand(chatId: string, command: string, timeoutMs = 5_000): Promise<void> {
    const normalized = command.trim();
    const turnId = `${SYSTEM_COMMAND_TURN_PREFIX}${crypto.randomUUID()}`;
    return new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pendingSystemCommands.delete(turnId);
        reject(new Error("system command timed out"));
      }, timeoutMs);
      this.pendingSystemCommands.set(turnId, { resolve, reject, timer });
      this.sendMessage(chatId, normalized, undefined, { turnId });
    });
  }

  setWorkspaceScope(chatId: string, workspaceScope: WorkspaceScopePayload): void {
    this.knownChats.add(chatId);
    this.queueSend({
      type: "set_workspace_scope",
      chat_id: chatId,
      workspace_scope: workspaceScope,
    });
  }

  // -- internals ---------------------------------------------------------

  private setStatus(status: ConnectionStatus): void {
    if (this.status_ === status) return;
    this.status_ = status;
    for (const handler of this.statusHandlers) handler(status);
  }

  private clearRunStatusesForReconnect(): void {
    if (this.runStartedAtByChatId.size === 0) return;
    const chatIds = [...this.runStartedAtByChatId.keys()];
    this.runStartedAtByChatId.clear();
    this.runStartedAtByTurnKey.clear();
    for (const chatId of chatIds) this.emitRunStatus(chatId, null);
  }

  private handleOpen(): void {
    this.setStatus("open");
    this.reconnectAttempts = 0;
    // Re-attach every known chat_id so deliveries continue routing after a drop.
    for (const chatId of this.knownChats) {
      this.rawSend({ type: "attach", chat_id: chatId });
    }
    // Flush anything queued during reconnect.
    const queued = this.sendQueue.splice(0);
    for (const frame of queued) this.rawSend(frame);
  }

  private handleMessage(ev: MessageEvent): void {
    let parsed: InboundEvent;
    try {
      parsed = JSON.parse(typeof ev.data === "string" ? ev.data : "") as InboundEvent;
    } catch {
      if (wsInboundDebugEnabled()) {
        const raw = typeof ev.data === "string" ? ev.data : String(ev.data);
        console.warn(
          "[nanobot ws inbound] invalid JSON",
          raw.length > 400 ? `${raw.slice(0, 400)}… (${raw.length} chars)` : raw,
        );
      }
      return;
    }

    if (wsInboundDebugEnabled()) {
      console.log("[nanobot ws inbound]", summarizeInboundWsPayload(parsed));
    }

    if (parsed.event === "error" && !parsed.turn_id) {
      const fallback = this.legacyRejectionTarget(parsed);
      if (fallback) {
        parsed = {
          ...parsed,
          chat_id: parsed.chat_id ?? fallback.chatId,
          turn_id: fallback.turnId,
        };
      }
    }
    if (
      (parsed.event === "goal_status" || parsed.event === "turn_end")
      && !parsed.turn_id
    ) {
      const fallbackTurnId = this.uniqueUnsettledTurnId(parsed.chat_id);
      if (fallbackTurnId) parsed = { ...parsed, turn_id: fallbackTurnId };
    }

    const turnId = "turn_id" in parsed && typeof parsed.turn_id === "string"
      ? parsed.turn_id
      : null;
    if (parsed.event === "message_accepted") {
      this.recordRunAcceptance(parsed.chat_id, parsed.turn_id);
      if (!isSystemCommandTurnId(turnId)) {
        this.dispatch(parsed.chat_id, parsed);
      }
      return;
    }
    if (isSystemCommandTurnId(turnId)) {
      if (parsed.event === "error") {
        this.rejectSystemCommand(
          turnId,
          [parsed.detail, parsed.reason].filter(Boolean).join(":") || "server error",
        );
      } else if (parsed.event === "message" || parsed.event === "turn_end") {
        this.resolveSystemCommand(turnId);
      }
      return;
    }

    const correlatedChatId = (parsed as { chat_id?: string }).chat_id;
    if (parsed.event === "error" && correlatedChatId && turnId) {
      this.recordRunRejection(correlatedChatId, turnId);
      if (parsed.detail !== "workspace_scope_rejected") {
        this.emitError({
          kind: "turn_rejected",
          detail: parsed.detail,
          reason: parsed.reason,
          chatId: correlatedChatId,
          turnId,
        });
      }
    } else if (parsed.event !== "error" && correlatedChatId && turnId) {
      // Lifecycle traffic is also an implicit acceptance signal for clients
      // connected to an older gateway that doesn't emit message_accepted.
      this.recordRunAcceptance(correlatedChatId, turnId);
    }

    if (parsed.event === "ready") {
      this.readyChatId = parsed.chat_id;
      this.knownChats.add(parsed.chat_id);
      return;
    }

    if (parsed.event === "attached") {
      this.knownChats.add(parsed.chat_id);
      if (this.pendingNewChat) {
        clearTimeout(this.pendingNewChat.timer);
        this.pendingNewChat.resolve(parsed.chat_id);
        this.pendingNewChat = null;
      }
      this.dispatch(parsed.chat_id, parsed);
      return;
    }

    if (parsed.event === "runtime_model_updated") {
      this.emitRuntimeModelUpdate(parsed.model_name || null, parsed.model_preset ?? null);
      return;
    }

    if (parsed.event === "transcription_result") {
      this.resolveTranscription(parsed.request_id, parsed.text);
      return;
    }

    if (parsed.event === "transcription_error") {
      this.rejectTranscription(parsed.request_id, parsed.detail || "error");
      return;
    }

    if (parsed.event === "session_updated") {
      this.emitSessionUpdate(parsed.chat_id, parsed.scope, parsed.workspace_scope);
      return;
    }

    if (parsed.event === "error" && parsed.detail === "workspace_scope_rejected") {
      this.emitError({
        kind: "workspace_scope_rejected",
        reason: parsed.reason,
        chatId: parsed.chat_id,
        turnId: parsed.turn_id,
      });
      if (this.pendingNewChat) {
        clearTimeout(this.pendingNewChat.timer);
        this.pendingNewChat.reject(new Error(`workspace_scope_rejected:${parsed.reason || ""}`));
        this.pendingNewChat = null;
      }
    }

    if (parsed.event === "error" && this.pendingNewChat) {
      clearTimeout(this.pendingNewChat.timer);
      const detail = typeof parsed.detail === "string" ? parsed.detail : "server error";
      const reason = typeof parsed.reason === "string" && parsed.reason ? `:${parsed.reason}` : "";
      this.pendingNewChat.reject(new Error(`${detail}${reason}`));
      this.pendingNewChat = null;
    }

    const chatId = (parsed as { chat_id?: string }).chat_id;
    if (chatId) {
      if (this.isCanonicalCompletedTurnEvent(chatId, parsed)) return;
      const supersededRunCompletion = this.isSupersededRunCompletion(chatId, parsed);
      this.recordGoalStatusForRunStrip(chatId, parsed);
      if (supersededRunCompletion) return;
      this.recordGoalStateSnapshot(chatId, parsed);
      this.dispatch(chatId, parsed);
    }
  }

  private emitRuntimeModelUpdate(modelName: string | null, modelPreset?: string | null): void {
    for (const handler of this.runtimeModelHandlers) {
      handler(modelName, modelPreset);
    }
  }

  private emitSessionUpdate(
    chatId: string,
    scope?: SessionUpdateScope,
    workspaceScope?: WorkspaceScopePayload,
  ): void {
    for (const handler of this.sessionUpdateHandlers) {
      handler(chatId, scope, workspaceScope);
    }
  }

  private emitRunStatus(chatId: string, startedAt: number | null): void {
    for (const handler of this.runStatusHandlers) {
      handler(chatId, startedAt);
    }
  }

  private dispatch(chatId: string, ev: InboundEvent): void {
    const handlers = this.chatHandlers.get(chatId);
    if (handlers !== undefined && handlers.size > 0) {
      for (const h of handlers) {
        h(ev);
      }
      return;
    }
    let q = this.pendingInboundByChat.get(chatId);
    if (!q) {
      q = [];
      this.pendingInboundByChat.set(chatId, q);
    }
    q.push(ev);
    const over = q.length - NanobotClient.PENDING_INBOUND_MAX;
    if (over > 0) {
      q.splice(0, over);
    }
  }

  private handleClose(event?: { code?: number }): void {
    this.socket = null;
    if (this.pendingNewChat) {
      clearTimeout(this.pendingNewChat.timer);
      this.pendingNewChat.reject(new Error("socket closed"));
      this.pendingNewChat = null;
    }
    this.rejectAllTranscriptions("socket closed");
    for (const pending of this.pendingSystemCommands.values()) {
      clearTimeout(pending.timer);
      pending.reject(new Error("socket closed"));
    }
    this.pendingSystemCommands.clear();
    // Surface structured reasons *before* reconnect logic so the UI can
    // display the error even while the client transparently reconnects.
    // Browsers populate ``CloseEvent.code`` with the wire-level close code;
    // 1009 = Message Too Big (server's max frame guard).
    const unacknowledged = Array.from(this.socketPendingMessageSendKeys)
      .map((key) => this.pendingMessageSends.get(key))
      .filter((pending): pending is PendingMessageSend => pending !== undefined);
    if (event?.code === 1009) {
      const soleKey = unacknowledged.length === 1
        ? this.runSendKey(unacknowledged[0].chatId, unacknowledged[0].turnId)
        : null;
      if (
        unacknowledged.length === 1
        && this.lastSocketMessageSendKey === soleKey
      ) {
        const [rejected] = unacknowledged;
        this.recordRunRejection(rejected.chatId, rejected.turnId);
        this.emitError({
          kind: "message_too_big",
          chatId: rejected.chatId,
          turnId: rejected.turnId,
        });
        this.dispatch(rejected.chatId, {
          event: "error",
          detail: "message_too_big",
          chat_id: rejected.chatId,
          turn_id: rejected.turnId,
        });
      } else {
        // A close frame identifies no offending application message. Never
        // roll back multiple chats merely because they shared one socket.
        this.emitError({ kind: "message_too_big" });
      }
    }
    for (const pending of unacknowledged) {
      const current = this.pendingMessageSends.get(
        this.runSendKey(pending.chatId, pending.turnId),
      );
      if (current?.state === "sent") current.state = "unknown";
    }
    this.socketPendingMessageSendKeys.clear();
    this.lastSocketMessageSendKey = null;
    if (this.intentionallyClosed || !this.shouldReconnect) {
      this.setStatus("closed");
      return;
    }
    this.scheduleReconnect();
  }

  private emitError(error: StreamError): void {
    // Isolate subscribers so a throwing handler cannot abort the surrounding
    // ``handleClose`` flow (which still owes us a reconnect decision + status
    // update). We deliberately swallow here: error reporting is best-effort
    // and must never be allowed to compound the failure it's reporting.
    for (const handler of this.errorHandlers) {
      try {
        handler(error);
      } catch {
        // best-effort: subscriber fault must not stall transport bookkeeping
      }
    }
  }

  private resolveTranscription(requestId: string, text: string): void {
    const pending = this.pendingTranscriptions.get(requestId);
    if (!pending) return;
    clearTimeout(pending.timer);
    this.pendingTranscriptions.delete(requestId);
    pending.resolve(text);
  }

  private rejectTranscription(requestId: string | undefined, detail: string): void {
    if (!requestId) {
      this.rejectAllTranscriptions(detail);
      return;
    }
    const pending = this.pendingTranscriptions.get(requestId);
    if (!pending) return;
    clearTimeout(pending.timer);
    this.pendingTranscriptions.delete(requestId);
    pending.reject(new Error(detail));
  }

  private rejectAllTranscriptions(detail: string): void {
    for (const [requestId, pending] of this.pendingTranscriptions) {
      clearTimeout(pending.timer);
      pending.reject(new Error(detail));
      this.pendingTranscriptions.delete(requestId);
    }
  }

  private resolveSystemCommand(turnId: string): void {
    const pending = this.pendingSystemCommands.get(turnId);
    if (!pending) return;
    clearTimeout(pending.timer);
    this.pendingSystemCommands.delete(turnId);
    pending.resolve();
  }

  private rejectSystemCommand(turnId: string, detail: string): void {
    const pending = this.pendingSystemCommands.get(turnId);
    if (!pending) return;
    clearTimeout(pending.timer);
    this.pendingSystemCommands.delete(turnId);
    pending.reject(new Error(detail));
  }

  private scheduleReconnect(): void {
    this.clearRunStatusesForReconnect();
    this.setStatus("reconnecting");
    const attempt = this.reconnectAttempts++;
    // Exponential backoff: 0.5s, 1s, 2s, 4s, capped.
    const delay = Math.min(500 * 2 ** attempt, this.maxBackoffMs);
    this.reconnectTimer = setTimeout(async () => {
      this.reconnectTimer = null;
      if (this.options.onReauth) {
        try {
          const refreshed = await this.options.onReauth();
          if (refreshed) this.currentUrl = refreshed;
        } catch {
          // fall through to retry with current URL
        }
      }
      this.connect();
    }, delay);
  }

  private queueSend(frame: Outbound): void {
    if (this.socket?.readyState === WS_OPEN) {
      this.rawSend(frame);
    } else {
      this.sendQueue.push(frame);
    }
  }

  private frameFitsTransport(frame: Outbound): boolean {
    if (this.maxFrameBytes === undefined) return true;
    return new TextEncoder().encode(JSON.stringify(frame)).byteLength <= this.maxFrameBytes;
  }

  private rawSend(frame: Outbound): void {
    if (!this.socket) return;
    try {
      this.socket.send(JSON.stringify(frame));
      this.lastSocketMessageSendKey = null;
      if (frame.type === "message" && frame.turn_id) {
        const key = this.runSendKey(frame.chat_id, frame.turn_id);
        const pending = this.pendingMessageSends.get(key);
        if (pending) {
          pending.state = "sent";
          this.socketPendingMessageSendKeys.add(key);
          this.lastSocketMessageSendKey = key;
        }
      }
    } catch {
      // Send failure will materialize as a close; queue the frame for retry.
      this.sendQueue.push(frame);
    }
  }
}
