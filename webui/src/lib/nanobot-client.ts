import { uploadAttachments, uploadCapability, type AttachmentReference, type UploadCapability } from "../../../packages/client-events/attachments";
import { DeliveryReceipts } from "../../../packages/client-events/delivery";
import { decodeNotification } from "../../../packages/client-events/notifications";
import type {
  ConnectionStatus,
  InboundEvent,
  Outbound,
  OutboundCliAppMention,
  OutboundMcpPresetMention,
  OutboundMedia,
  SessionMention,
  SidebarStatePayload,
  GoalStateWsPayload,
  WorkspaceScopePayload,
} from "./types";
import { createHostWebSocket } from "./runtime";
import { ClientRunLedger } from "./client-run-ledger";
import type { CanonicalRunSnapshot, RunEffect, RunObservation } from "./client-run-ledger";

export type { CanonicalRunSnapshot } from "./client-run-ledger";

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
  if (kind === "ready") return { ...ev, upload: "[redacted]" };
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
type RunCompletionHandler = (chatId: string) => void;
type RuntimeModelHandler = (modelName: string | null, modelPreset?: string | null) => void;
type SessionUpdateScope = "metadata" | "thread" | string;
type SessionUpdateHandler = (
  chatId: string,
  scope?: SessionUpdateScope,
  workspaceScope?: WorkspaceScopePayload,
) => void;
type SidebarStateUpdateHandler = (state: SidebarStatePayload) => void;
type RunStatusHandler = (chatId: string, startedAt: number | null) => void;

/** Structured errors surfaced to the UI.
 *
 * Most entries are transport-level or protocol-level faults. Runtime and
 * workspace failures are promoted here when they must remain visible outside
 * the message stream.
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
    }
  | {
      kind: "model_request_failed";
      chatId: string;
      turnId?: string;
      errorKind?: string;
      attempts?: number;
    };

type ErrorHandler = (error: StreamError) => void;

interface PendingRequest<T> {
  resolve: (value: T) => void;
  reject: (err: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

interface PendingWebUIRequest extends PendingRequest<unknown> {
  serializedFrame: string;
}

class WebUIMutationError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "WebUIMutationError";
  }
}

interface PendingChatRequest extends PendingRequest<string> {
  temporary: boolean;
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

function runObservation(event: InboundEvent): RunObservation | null {
  if (!("chat_id" in event) || !event.chat_id) return null;
  const turnId = "turn_id" in event && typeof event.turn_id === "string" ? event.turn_id : null;
  const base = { chatId: event.chat_id, turnId, systemCommand: isSystemCommandTurnId(turnId) };
  switch (event.event) {
    case "message_accepted":
    case "user_message": {
      const activeTurnId = event.active_turn_id ?? (event.starts_turn ? event.turn_id : undefined);
      return {
        ...base,
        kind: event.event === "message_accepted" ? "admission" : "input",
        ...(activeTurnId ? { owner: { turnId: activeTurnId, startedAt: event.started_at } } : {}),
      };
    }
    case "goal_status":
      return { ...base, kind: "status", activity: event.status, startedAt: event.started_at };
    case "turn_end":
      return { ...base, kind: "completed" };
    case "error":
      return { ...base, kind: "rejection" };
    case "message":
      return { ...base, kind: "message" };
    default:
      return { ...base, kind: "progress" };
  }
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
  private upload: UploadCapability | null = null;
  private receipts = new DeliveryReceipts();
  private statusHandlers = new Set<StatusHandler>();
  private runtimeModelHandlers = new Set<RuntimeModelHandler>();
  private sessionUpdateHandlers = new Set<SessionUpdateHandler>();
  private sidebarStateUpdateHandlers = new Set<SidebarStateUpdateHandler>();
  private runStatusHandlers = new Set<RunStatusHandler>();
  private runCompletionHandlers = new Set<RunCompletionHandler>();
  private errorHandlers = new Set<ErrorHandler>();
  // chat_id -> handlers listening on it
  private chatHandlers = new Map<string, Set<EventHandler>>();
  /** Inbound frames received while no subscriber is registered (e.g. user switched away). */
  private pendingInboundByChat = new Map<string, InboundEvent[]>();
  private static readonly PENDING_INBOUND_MAX = 2000;
  // chat_ids we've attached to since connect; re-attached after reconnects
  private knownChats = new Set<string>();
  /** Temporary chats are connection-owned and intentionally not reattached. */
  private temporaryChatIds = new Set<string>();
  private readonly runs = new ClientRunLedger();
  /** Last tracked application frame written, for conservative transport-error attribution. */
  private lastSocketMessageSend: { chatId: string; turnId: string } | null = null;
  /** Latest ``goal_state`` snapshot per ``chat_id`` (multi-session isolation). */
  private goalStateByChatId = new Map<string, GoalStateWsPayload>();
  private pendingNewChat: PendingChatRequest | null = null;
  private pendingTranscriptions = new Map<string, PendingRequest<string>>();
  private pendingSystemCommands = new Map<string, PendingRequest<void>>();
  private pendingWebUIRequests = new Map<string, PendingWebUIRequest>();
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

  onSidebarStateUpdate(handler: SidebarStateUpdateHandler): Unsubscribe {
    this.sidebarStateUpdateHandlers.add(handler);
    return () => {
      this.sidebarStateUpdateHandlers.delete(handler);
    };
  }

  onRunStatus(handler: RunStatusHandler): Unsubscribe {
    this.runStatusHandlers.add(handler);
    for (const { chatId, startedAt } of this.runs.activeClocks()) {
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
    return this.runs.view(chatId).startedAt;
  }

  /** Canonical lifecycle turn currently owning the run, retained after completion. */
  getRunTurnId(chatId: string): string | null {
    return this.runs.view(chatId).latestTurnId;
  }

  isRunCompleted(chatId: string, turnId: string): boolean {
    return this.runs.isCompleted({ chatId, turnId });
  }

  /** End the local optimistic run without confirming gateway cancellation. */
  finishRunLocally(chatId: string): void {
    this.applyRunEffects(this.runs.transition({ kind: "local-stop", chatId }));
  }

  updateMaxFrameBytes(maxFrameBytes?: number): void {
    this.maxFrameBytes = this.normalizeMaxFrameBytes(maxFrameBytes);
  }

  getRunGeneration(chatId: string): number {
    return this.runs.view(chatId).generation;
  }

  hasUnsettledRun(chatId: string): boolean {
    return this.runs.view(chatId).unsettled;
  }

  onRunCompletion(handler: RunCompletionHandler): Unsubscribe {
    this.runCompletionHandlers.add(handler);
    return () => this.runCompletionHandlers.delete(handler);
  }

  getUnsettledRunChatIds(): string[] {
    return this.runs.unresolvedChatIds().filter((chatId) => !this.temporaryChatIds.has(chatId));
  }

  private normalizeMaxFrameBytes(value: number | undefined): number | undefined {
    if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
      return undefined;
    }
    return Math.floor(value);
  }

  /** Pure preflight; it neither settles runs nor prunes queued frames. */
  canReconcileCanonicalCompletion(
    chatId: string,
    expectedRunGeneration: number,
    completedTurnIds: readonly string[],
    snapshot?: CanonicalRunSnapshot,
  ): boolean {
    return this.runs.canApplyCanonical({
      chatId, generation: expectedRunGeneration, completedTurnIds, snapshot,
    });
  }

  /** Preserve explicit completion fences even when a newer run prevents adoption. */
  reconcileCanonicalCompletion(
    chatId: string,
    expectedRunGeneration: number,
    completedTurnIds: readonly string[],
    snapshot?: CanonicalRunSnapshot,
  ): boolean {
    const result = this.runs.applyCanonical({
      chatId, generation: expectedRunGeneration, completedTurnIds, snapshot,
    });
    this.applyRunEffects(result.effects);
    return result.accepted;
  }

  fenceCanonicalCompletedTurns(chatId: string, completedTurnIds: readonly string[]): void {
    this.applyRunEffects(this.runs.transition({ kind: "fence", chatId, completedTurnIds }));
  }

  /** Last ``goal_state`` payload for *chatId*, if any frame has arrived this connection. */
  getGoalState(chatId: string): GoalStateWsPayload | undefined {
    return this.goalStateByChatId.get(chatId);
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
    return this.runs.soleSentTurn(this.lastSocketMessageSend, ev.chat_id);
  }

  private applyRunEffects(effects: readonly RunEffect[]): void {
    for (const effect of effects) {
      switch (effect.kind) {
        case "run-status":
          this.emitRunStatus(effect.chatId, effect.startedAt);
          break;
        case "completion":
          for (const handler of this.runCompletionHandlers) handler(effect.chatId);
          break;
        case "discard-send":
          this.sendQueue = this.sendQueue.filter((frame) => !(
            frame.type === "message"
            && frame.chat_id === effect.chatId
            && frame.turn_id === effect.turnId
          ));
          break;
        case "prune-inbound": {
          const pending = this.pendingInboundByChat.get(effect.chatId);
          if (!pending) break;
          const turnIds = new Set(effect.turnIds);
          const remaining = pending.filter((event) => (
            !("turn_id" in event)
            || typeof event.turn_id !== "string"
            || !turnIds.has(event.turn_id)
          ));
          if (remaining.length > 0) this.pendingInboundByChat.set(effect.chatId, remaining);
          else this.pendingInboundByChat.delete(effect.chatId);
          break;
        }
        default: {
          const exhaustive: never = effect;
          return exhaustive;
        }
      }
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
    this.upload = null;
    this.receipts.close();
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
    this.clearTemporaryChats();
    this.setStatus("closed");
  }

  discardTemporaryChat(chatId: string): void {
    if (!this.temporaryChatIds.has(chatId)) return;
    if (this.socket?.readyState === WS_OPEN) {
      this.rawSend({ type: "discard_temporary_chat", chat_id: chatId });
    }
    this.forgetTemporaryChat(chatId);
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
      this.pendingNewChat = { resolve, reject, timer, temporary: false };
      this.queueSend({
        type: "new_chat",
        ...(workspaceScope ? { workspace_scope: workspaceScope } : {}),
      });
    });
  }

  /** Ask the WebUI gateway to create a connection-owned non-persistent chat. */
  newTemporaryChat(timeoutMs: number = 5_000): Promise<string> {
    if (this.pendingNewChat) {
      return Promise.reject(new Error("newChat already in flight"));
    }
    return new Promise<string>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pendingNewChat = null;
        reject(new Error("newTemporaryChat timed out"));
      }, timeoutMs);
      this.pendingNewChat = { resolve, reject, timer, temporary: true };
      this.queueSend({ type: "new_temporary_chat" });
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

  /**
   * Send one WebUI mutation over the authenticated socket. Pending requests are
   * replayed with the same request_id after reconnect so the gateway can join or
   * replay the original operation. A client-side timeout still ends all retries.
   */
  requestMutation<T>(
    action: string,
    payload: Record<string, unknown> = {},
    timeoutMs: number = 20_000,
  ): Promise<T> {
    const socket = this.socket;
    if (!socket || socket.readyState !== WS_OPEN) {
      return Promise.reject(
        new WebUIMutationError(503, "WebUI connection is not open"),
      );
    }
    const requestId = crypto.randomUUID();
    const frame: Outbound = {
      type: "webui_request",
      request_id: requestId,
      action,
      payload,
    };
    if (!this.frameFitsTransport(frame)) {
      return Promise.reject(
        new WebUIMutationError(413, "WebUI mutation payload is too large"),
      );
    }

    return new Promise<T>((resolve, reject) => {
      let serializedFrame: string;
      try {
        serializedFrame = JSON.stringify(frame);
      } catch {
        reject(new WebUIMutationError(503, "Could not encode WebUI request"));
        return;
      }
      const timer = setTimeout(() => {
        this.pendingWebUIRequests.delete(requestId);
        reject(
          new WebUIMutationError(
            504,
            `WebUI request timed out after ${timeoutMs}ms`,
          ),
        );
      }, timeoutMs);
      this.pendingWebUIRequests.set(requestId, {
        resolve: (value) => resolve(value as T),
        reject,
        timer,
        serializedFrame,
      });
      try {
        socket.send(serializedFrame);
      } catch {
        clearTimeout(timer);
        this.pendingWebUIRequests.delete(requestId);
        reject(new WebUIMutationError(503, "Could not send WebUI request"));
      }
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
      this.pendingNewChat = { resolve, reject, timer, temporary: false };
      this.queueSend({
        type: "fork_chat",
        source_chat_id: sourceChatId,
        before_user_index: beforeUserIndex,
        ...(title?.trim() ? { title: title.trim() } : {}),
      });
    });
  }

  attach(chatId: string): void {
    if (this.temporaryChatIds.has(chatId)) return;
    this.knownChats.add(chatId);
    if (this.socket?.readyState === WS_OPEN) {
      this.queueSend({ type: "attach", chat_id: chatId });
    }
  }

  async sendAttachments(
    chatId: string, content: string, media: OutboundMedia[],
    options?: Parameters<NanobotClient["sendMessage"]>[3],
  ): Promise<void> {
    const socket = this.socket;
    const capability = this.upload;
    const turnId = options?.turnId ?? crypto.randomUUID();
    const stillConnected = () => this.socket === socket
      && socket?.readyState === WS_OPEN && this.upload === capability;
    try {
      const references = await uploadAttachments(media, capability,
        typeof window !== "undefined" ? window.location.href : this.currentUrl,
        stillConnected);
      if (!stillConnected()) throw new Error("Connection changed during attachment send");
      await this.receipts.wait(turnId, () => {
        if (!this.sendMessage(chatId, content, references, { ...options, turnId })) {
          throw new Error("Message exceeds the gateway's WebSocket frame limit; draft retained");
        }
      });
    } catch (error) {
      this.emitError({ kind: "turn_rejected", chatId, turnId, detail: "attachment_rejected",
        reason: error instanceof Error ? error.message : "Attachment send failed" });
      throw error;
    }
  }

  sendMessage(
    chatId: string,
    content: string,
    media?: AttachmentReference[],
    options?: {
      cliApps?: OutboundCliAppMention[];
      mcpPresets?: OutboundMcpPresetMention[];
      sessionMentions?: SessionMention[];
      quotedContext?: string;
      intent?: "create_automation";
      workspaceScope?: WorkspaceScopePayload | null;
      turnId?: string;
      /** False for side-channel or injected messages that do not own a lifecycle. */
      startsNewRun?: boolean;
    },
  ): boolean {
    const temporary = this.temporaryChatIds.has(chatId);
    if (!temporary) this.knownChats.add(chatId);
    const frame: Outbound = {
      type: "message",
      chat_id: chatId,
      content,
      ...(media && media.length > 0 ? { media } : {}),
      ...(options?.cliApps?.length ? { cli_apps: options.cliApps } : {}),
      ...(options?.mcpPresets?.length ? { mcp_presets: options.mcpPresets } : {}),
      ...(options?.sessionMentions?.length
        ? { session_mentions: options.sessionMentions }
        : {}),
      ...(options?.quotedContext?.trim() ? { quoted_context: options.quotedContext.trim() } : {}),
      ...(options?.intent === "create_automation" ? { intent: options.intent } : {}),
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
      return false;
    }
    if (options?.turnId && !isSystemCommandTurnId(options.turnId)) {
      this.applyRunEffects(this.runs.transition({
        kind: "submit",
        chatId,
        turnId: options.turnId,
        role: options.startsNewRun === false ? "supplement" : "candidate-owner",
      }));
    }
    this.queueSend(frame);
    return true;
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
    if (this.temporaryChatIds.has(chatId)) return;
    this.knownChats.add(chatId);
    this.queueSend({
      type: "set_workspace_scope",
      chat_id: chatId,
      workspace_scope: workspaceScope,
    });
  }

  setSidebarState(state: SidebarStatePayload): Promise<SidebarStatePayload> {
    return this.requestMutation<SidebarStatePayload>("sidebar.update", { state });
  }

  // -- internals ---------------------------------------------------------

  private setStatus(status: ConnectionStatus): void {
    if (this.status_ === status) return;
    this.status_ = status;
    for (const handler of this.statusHandlers) handler(status);
  }

  private handleOpen(): void {
    this.setStatus("open");
    this.reconnectAttempts = 0;
    // Re-attach every known chat_id so deliveries continue routing after a drop.
    for (const chatId of this.knownChats) {
      this.rawSend({ type: "attach", chat_id: chatId });
    }
    for (const pending of this.pendingWebUIRequests.values()) {
      this.rawSendSerialized(pending.serializedFrame);
    }
    // Flush anything queued during reconnect.
    const queued = this.sendQueue.splice(0);
    for (const frame of queued) this.rawSend(frame);
  }

  private handleMessage(ev: MessageEvent): void {
    let parsed: InboundEvent;
    try {
      parsed = JSON.parse(typeof ev.data === "string" ? ev.data : "") as InboundEvent;
      if (decodeNotification(parsed) === null) return;
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

    if (parsed.event === "webui_response") {
      const pending = this.pendingWebUIRequests.get(parsed.request_id);
      if (!pending) return;
      clearTimeout(pending.timer);
      this.pendingWebUIRequests.delete(parsed.request_id);
      if (parsed.ok) {
        pending.resolve(parsed.result);
      } else {
        const status = Number.isFinite(parsed.error?.status)
          ? parsed.error.status
          : 500;
        const message = parsed.error?.message || "WebUI mutation failed";
        pending.reject(new WebUIMutationError(status, message));
      }
      return;
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
      const fallbackTurnId = this.runs.soleUnsettledTurn(parsed.chat_id);
      if (fallbackTurnId) parsed = { ...parsed, turn_id: fallbackTurnId };
    }

    this.receipts.event(parsed);
    const turnId = "turn_id" in parsed && typeof parsed.turn_id === "string"
      ? parsed.turn_id
      : null;
    const correlatedChatId = "chat_id" in parsed ? parsed.chat_id : undefined;
    const observation = runObservation(parsed);
    if (observation) {
      const result = this.runs.observe(observation);
      this.applyRunEffects(result.effects);
      if (result.forward === "drop") return;
      if (
        result.forward === "without-owner"
        && (parsed.event === "message_accepted" || parsed.event === "user_message")
      ) {
        parsed = { ...parsed, active_turn_id: undefined, started_at: undefined, starts_turn: false };
      }
    }
    if (parsed.event === "message_accepted") {
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

    if (parsed.event === "error" && correlatedChatId && turnId) {
      if (parsed.detail !== "workspace_scope_rejected") {
        this.emitError({
          kind: "turn_rejected",
          detail: parsed.detail,
          reason: parsed.reason,
          chatId: correlatedChatId,
          turnId,
        });
      }
    }

    if (parsed.event === "ready") {
      this.upload = uploadCapability(parsed.upload);
      this.readyChatId = parsed.chat_id;
      this.knownChats.add(parsed.chat_id);
      return;
    }

    if (parsed.event === "attached") {
      if (parsed.temporary === true) {
        this.temporaryChatIds.add(parsed.chat_id);
      } else {
        this.knownChats.add(parsed.chat_id);
      }
      if (
        this.pendingNewChat
        && this.pendingNewChat.temporary === (parsed.temporary === true)
      ) {
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

    if (parsed.event === "sidebar_state_updated") {
      this.emitSidebarStateUpdate(parsed.state);
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

    if (correlatedChatId) {
      this.recordGoalStateSnapshot(correlatedChatId, parsed);
      this.dispatch(correlatedChatId, parsed);
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

  private emitSidebarStateUpdate(state: SidebarStatePayload): void {
    for (const handler of this.sidebarStateUpdateHandlers) {
      handler(state);
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
    // Temporary chats have no canonical history to recover evicted events from.
    // Like their pinned message snapshots, retain them until resubscribe, close
    // or disconnect. Disk-backed chats keep the bounded replay tail below.
    if (this.temporaryChatIds.has(chatId)) return;
    const over = q.length - NanobotClient.PENDING_INBOUND_MAX;
    if (over > 0) {
      q.splice(0, over);
    }
  }

  private handleClose(event?: { code?: number }): void {
    this.upload = null;
    this.receipts.close();
    this.socket = null;
    this.clearTemporaryChats();
    const willReconnect = !this.intentionallyClosed && this.shouldReconnect;
    if (this.pendingNewChat) {
      clearTimeout(this.pendingNewChat.timer);
      this.pendingNewChat.reject(new Error("socket closed"));
      this.pendingNewChat = null;
    }
    this.rejectAllTranscriptions("socket closed");
    if (!willReconnect) {
      for (const pending of this.pendingWebUIRequests.values()) {
        clearTimeout(pending.timer);
        pending.reject(
          new WebUIMutationError(503, "Socket closed before WebUI response"),
        );
      }
      this.pendingWebUIRequests.clear();
    }
    for (const pending of this.pendingSystemCommands.values()) {
      clearTimeout(pending.timer);
      pending.reject(new Error("socket closed"));
    }
    this.pendingSystemCommands.clear();
    // Surface structured reasons *before* reconnect logic so the UI can
    // display the error even while the client transparently reconnects.
    // Browsers populate ``CloseEvent.code`` with the wire-level close code;
    // 1009 = Message Too Big (server's max frame guard).
    if (event?.code === 1009) {
      const rejected = this.runs.soleSentTurn(this.lastSocketMessageSend);
      if (rejected) {
        this.applyRunEffects(this.runs.transition({ kind: "reject", ...rejected }));
        this.emitError({ kind: "message_too_big", ...rejected });
        this.dispatch(rejected.chatId, {
          event: "error",
          detail: "message_too_big",
          chat_id: rejected.chatId,
          turn_id: rejected.turnId,
        });
      } else {
        // A close frame cannot identify one message among multiplexed sends.
        this.emitError({ kind: "message_too_big" });
      }
    }
    this.applyRunEffects(this.runs.transition({ kind: "transport-lost" }));
    this.lastSocketMessageSend = null;
    if (!willReconnect) {
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

  private clearTemporaryChats(): void {
    for (const chatId of [...this.temporaryChatIds]) {
      this.forgetTemporaryChat(chatId);
    }
  }

  private forgetTemporaryChat(chatId: string): void {
    this.temporaryChatIds.delete(chatId);
    this.knownChats.delete(chatId);
    this.chatHandlers.delete(chatId);
    this.pendingInboundByChat.delete(chatId);
    const effects = this.runs.transition({ kind: "forget", chatId });
    this.goalStateByChatId.delete(chatId);
    this.sendQueue = this.sendQueue.filter((frame) => (
      !("chat_id" in frame) || frame.chat_id !== chatId
    ));
    if (this.lastSocketMessageSend?.chatId === chatId) this.lastSocketMessageSend = null;
    this.applyRunEffects(effects);
  }

  private frameFitsTransport(frame: Outbound): boolean {
    if (this.maxFrameBytes === undefined) return true;
    return new TextEncoder().encode(JSON.stringify(frame)).byteLength <= this.maxFrameBytes;
  }

  private rawSend(frame: Outbound): void {
    if (!this.socket) return;
    try {
      this.socket.send(JSON.stringify(frame));
      this.lastSocketMessageSend = null;
      if (frame.type === "message" && frame.turn_id) {
        const ref = { chatId: frame.chat_id, turnId: frame.turn_id };
        if (this.runs.hasPendingSend(ref)) {
          this.applyRunEffects(this.runs.transition({ kind: "written", ...ref }));
          this.lastSocketMessageSend = ref;
        }
      }
    } catch {
      // Send failure will materialize as a close; queue the frame for retry.
      this.sendQueue.push(frame);
    }
  }

  private rawSendSerialized(serializedFrame: string): void {
    if (!this.socket) return;
    try {
      this.socket.send(serializedFrame);
    } catch {
      // The pending request remains available for the next successful reconnect.
    }
  }
}
