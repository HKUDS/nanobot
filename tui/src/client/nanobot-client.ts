import { uploadAttachments, uploadCapability, type AttachmentReference, type UploadCapability } from "../../../packages/client-events/attachments"
import { DeliveryReceipts } from "../../../packages/client-events/delivery"
import { isRecoveryState } from "../../../packages/client-events/notifications"

import {
  GatewayConnectionError,
  connectionEndpoint,
  sanitizeConnectionFailure,
} from "./connection"
import type {
  ClientOptions,
  ConnectionStatusInfo,
  GatewayHealthStatus,
  MessageOptions,
  OutboundEvent,
  RecoveryState,
  WorkspaceScopePayload,
} from "./types"
import { decodeInboundEvent, decodeWebUIResponse, isRecord } from "./validation"

export class NanobotClient {
  private upload: UploadCapability | null = null
  private uploadBase = ""
  private receipts = new DeliveryReceipts()
  private identityVerified = false
  private handshakeTimer: ReturnType<typeof setTimeout> | null = null
  private socket: WebSocket | null = null
  private chatId = ""
  private workspaceScope?: WorkspaceScopePayload
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private reconnectAttempt = 0
  private closedByClient = false
  private opening = false
  private connectedOnce = false
  private connectionAttempt = 0
  private retryStartedAt = 0
  private nextRetryAt = 0
  private lastFailure = ""
  private healthStatus: GatewayHealthStatus | undefined
  private failureEscalationTimer: ReturnType<typeof setTimeout> | null = null
  private readonly endpoint: string
  private readonly pendingMutations = new Map<string, {
    resolve: (value: unknown) => void
    reject: (error: Error) => void
    timer: ReturnType<typeof setTimeout>
  }>()

  constructor(private readonly options: ClientOptions) {
    this.endpoint = options.targetEndpoint || connectionEndpoint(options.url)
  }

  get activeChatId(): string {
    return this.chatId
  }

  connect(): void {
    this.closedByClient = false
    this.connectionAttempt = 0
    this.reconnectAttempt = 0
    this.retryStartedAt = Date.now()
    this.nextRetryAt = 0
    this.lastFailure = ""
    this.healthStatus = undefined
    void this.open()
  }

  private async open(): Promise<void> {
    if (this.socket || this.opening || this.closedByClient) return
    this.opening = true
    this.identityVerified = !this.options.expectedGatewayId
    this.nextRetryAt = 0
    this.connectionAttempt += 1
    this.reportConnectionProgress()
    let url = this.options.url
    try {
      if (this.options.resolveConnection) {
        const connection = await this.options.resolveConnection()
        if (this.closedByClient) return
        this.options.onConnection?.(connection)
        url = connection.wsUrl
      }
    } catch (error) {
      if (!this.closedByClient) {
        this.lastFailure = sanitizeConnectionFailure(error)
        if (error instanceof GatewayConnectionError && !error.retryable) {
          this.clearFailureEscalation()
          this.options.onStatus("error", this.lastFailure, this.connectionInfo())
          return
        }
        await this.checkHealthAndScheduleReconnect()
      }
      return
    } finally {
      this.opening = false
    }
    if (!url) {
      this.options.onStatus("error", "gateway URL is not configured", this.connectionInfo())
      return
    }
    let socket: WebSocket
    try {
      this.uploadBase = url
      this.upload = null
      socket = new WebSocket(url)
    } catch (error) {
      this.lastFailure = sanitizeConnectionFailure(error)
      await this.checkHealthAndScheduleReconnect()
      return
    }
    let opened = false
    this.socket = socket
    if (this.options.expectedGatewayId) {
      this.handshakeTimer = setTimeout(() => this.desktopFailure(), 8_000)
    }
    socket.addEventListener("open", () => {
      if (this.socket !== socket) return
      opened = true
      this.connectedOnce = true
      this.connectionAttempt = 0
      this.reconnectAttempt = 0
      this.retryStartedAt = 0
      this.nextRetryAt = 0
      this.lastFailure = ""
      this.healthStatus = "ready"
      this.clearFailureEscalation()
      this.options.onStatus("connected", undefined, this.connectionInfo())
    })
    socket.addEventListener("message", (message) => {
      if (this.socket === socket) this.handleMessage(String(message.data))
    })
    socket.addEventListener("error", () => {
      if (this.socket !== socket) return
      if (this.options.reconnect === false) { this.desktopFailure(); return }
      this.lastFailure = "connection failed"
      this.reportRetryState()
    })
    socket.addEventListener("close", (event) => {
      if (this.socket !== socket) return
      this.socket = null
      this.upload = null
      this.receipts.close()
      this.lastFailure = event.code
        ? `connection closed (${event.code}${event.reason ? `: ${event.reason}` : ""})`
        : "connection closed"
      this.rejectPendingMutations("gateway connection closed")
      if (this.closedByClient) {
        this.options.onStatus("closed")
        return
      }
      if (this.options.reconnect === false) { this.desktopFailure(); return }
      if (opened) {
        this.connectionAttempt = 0
        this.reconnectAttempt = 0
        this.retryStartedAt = Date.now()
      }
      if (!this.lastFailure) this.lastFailure = "connection closed"
      this.reportRetryState()
      void this.checkHealthAndScheduleReconnect()
    })
  }

  close(): void {
    this.upload = null
    this.receipts.close()
    if (this.handshakeTimer) clearTimeout(this.handshakeTimer)
    this.handshakeTimer = null
    this.closedByClient = true
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.reconnectTimer = null
    this.clearFailureEscalation()
    const socket = this.socket
    this.socket = null
    socket?.close()
    this.rejectPendingMutations("gateway connection closed")
  }

  async sendAttachments(content: string, options: MessageOptions): Promise<string> {
    const socket = this.socket
    const chatId = this.chatId
    const upload = this.upload
    const references = await uploadAttachments(options.media ?? [], upload, this.uploadBase,
      () => this.socket === socket && socket?.readyState === WebSocket.OPEN && this.upload === upload && this.chatId === chatId)
    const turnId = crypto.randomUUID()
    await this.receipts.wait(turnId, () => this.send(content, options, references, turnId))
    return turnId
  }

  send(content: string, options: MessageOptions = {}, references?: AttachmentReference[], turnId = crypto.randomUUID()): string {
    if (!this.chatId) throw new Error("chat is not ready")
    if (options.media?.length && !references) throw new Error("Attachments require HTTP upload")
    this.write({
      type: "message",
      chat_id: this.chatId,
      content,
      turn_id: turnId,
      webui: true,
      ...(this.workspaceScope ? { workspace_scope: this.workspaceScope } : {}),
      ...(options.userShell ? { user_shell: true } : {}),
      ...(references?.length ? { media: references } : {}),
      ...(options.cliApps?.length ? { cli_apps: options.cliApps } : {}),
      ...(options.mcpPresets?.length ? { mcp_presets: options.mcpPresets } : {}),
      ...(options.sessionMentions?.length
        ? { session_mentions: options.sessionMentions }
        : {}),
    })
    return turnId
  }

  attach(chatId: string): void {
    if (!chatId) throw new Error("chat id is required")
    this.workspaceScope = undefined
    this.write({ type: "attach", chat_id: chatId })
  }

  newChat(scope?: WorkspaceScopePayload): void {
    this.workspaceScope = scope
    this.write({ type: "new_chat", ...(scope ? { workspace_scope: scope } : {}) })
  }

  forkChat(sourceChatId: string, beforeUserIndex: number, title?: string): void {
    this.write({
      type: "fork_chat",
      source_chat_id: sourceChatId,
      before_user_index: beforeUserIndex,
      ...(title?.trim() ? { title: title.trim() } : {}),
    })
  }

  setWorkspaceScope(scope: WorkspaceScopePayload): void {
    if (!this.chatId) throw new Error("chat is not ready")
    this.workspaceScope = scope
    this.write({ type: "set_workspace_scope", chat_id: this.chatId, workspace_scope: scope })
  }

  updateRecovery(
    action: "continue" | "dismiss",
    chatId: string,
    recoveryId: string,
  ): Promise<RecoveryState> {
    return this.requestMutation<unknown>(`recovery.${action}`, {
      chat_id: chatId,
      recovery_id: recoveryId,
    }).then((result) => {
      if (!isRecoveryState(result)) throw new Error("gateway returned an invalid recovery state")
      return result
    })
  }

  private requestMutation<T>(
    action: string,
    payload: Record<string, unknown> = {},
    timeoutMs = 20_000,
  ): Promise<T> {
    if (this.options.expectedGatewayId && !this.identityVerified) {
      return Promise.reject(new Error("Desktop identity not verified"))
    }
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      return Promise.reject(new Error("gateway connection is not open"))
    }
    const requestId = crypto.randomUUID()
    const frame = JSON.stringify({
      type: "webui_request",
      request_id: requestId,
      action,
      payload,
    } satisfies OutboundEvent)
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pendingMutations.delete(requestId)
        reject(new Error(`gateway request timed out after ${timeoutMs}ms`))
      }, timeoutMs)
      this.pendingMutations.set(requestId, {
        resolve: (value) => resolve(value as T),
        reject,
        timer,
      })
      try {
        this.socket?.send(frame)
      } catch {
        clearTimeout(timer)
        this.pendingMutations.delete(requestId)
        reject(new Error("could not send gateway request"))
      }
    })
  }

  private rejectPendingMutations(message: string): void {
    for (const pending of this.pendingMutations.values()) {
      clearTimeout(pending.timer)
      pending.reject(new Error(message))
    }
    this.pendingMutations.clear()
  }

  private handleMessage(raw: string): void {
    let value: unknown
    try {
      value = JSON.parse(raw) as unknown
    } catch {
      if (!this.identityVerified && this.options.expectedGatewayId) { this.desktopFailure(); return }
      this.options.onStatus("error", "gateway sent invalid JSON")
      return
    }
    const response = decodeWebUIResponse(value)
    if (!this.identityVerified) {
      // Matching metadata is insufficient: an invalid ready frame must not
      // unlock mutations or cancel the bounded compatibility handshake.
      if (!isRecord(value) || decodeInboundEvent(value)?.event !== "ready" || !isRecord(value.terminal)
        || value.terminal.protocolVersion !== 1 || value.terminal.gatewayId !== this.options.expectedGatewayId) {
        this.desktopFailure()
        return
      }
      this.identityVerified = true
      if (this.handshakeTimer) clearTimeout(this.handshakeTimer)
      this.handshakeTimer = null
    }
    if (response === null) {
      this.options.onStatus("error", "gateway sent an invalid event")
      return
    }
    if (response) {
      const pending = this.pendingMutations.get(response.request_id)
      if (!pending) return
      clearTimeout(pending.timer)
      this.pendingMutations.delete(response.request_id)
      if (response.ok) pending.resolve(response.result)
      else pending.reject(new Error(response.error?.message || "gateway request failed"))
      return
    }
    const event = decodeInboundEvent(value)
    if (event === undefined) return
    if (event === null) {
      this.options.onStatus("error", "gateway sent an invalid event")
      return
    }

    this.receipts.event(event)
    if (event.event === "ready") {
      this.upload = uploadCapability(isRecord(value) ? value.upload : null)
      const requestedChatId = this.chatId || this.options.chatId
      if (requestedChatId) {
        this.chatId = requestedChatId
        this.write({ type: "attach", chat_id: this.chatId })
      } else {
        this.newChat(this.options.initialWorkspaceScope)
      }
    } else if (event.event === "attached") {
      this.chatId = event.chat_id
    } else if (event.event === "session_updated" && event.workspace_scope) {
      this.workspaceScope = event.workspace_scope
    }
    this.options.onEvent(event)
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer || this.closedByClient) return
    if (!this.retryStartedAt) this.retryStartedAt = Date.now()
    const base = this.options.reconnectDelayMs ?? 500
    const maxDelay = this.connectedOnce
      ? 8_000
      : this.options.startupRetryMaxDelayMs ?? 8_000
    const delay = Math.min(maxDelay, base * 2 ** Math.min(this.reconnectAttempt++, 4))
    this.nextRetryAt = Date.now() + delay
    this.reportRetryState()
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      void this.open()
    }, delay)
  }

  private async checkHealthAndScheduleReconnect(): Promise<void> {
    if (this.options.reconnect === false) { this.desktopFailure(); return }
    if (this.options.checkHealth) {
      try {
        this.healthStatus = await this.options.checkHealth()
      } catch {
        this.healthStatus = "unreachable"
      }
    }
    if (!this.closedByClient) this.scheduleReconnect()
  }

  private connectionInfo(): ConnectionStatusInfo {
    return {
      endpoint: this.endpoint,
      attempt: Math.max(1, this.connectionAttempt),
      elapsedMs: this.retryStartedAt ? Math.max(0, Date.now() - this.retryStartedAt) : 0,
      ...(this.nextRetryAt
        ? { retryInMs: Math.max(0, this.nextRetryAt - Date.now()) }
        : {}),
      ...(this.healthStatus ? { health: this.healthStatus } : {}),
    }
  }

  private desktopFailure(): void {
    this.close()
    this.options.onStatus("error", "Desktop disconnected or is incompatible; reconnect from the terminal", this.connectionInfo())
  }

  private reportConnectionProgress(): void {
    if (this.connectedOnce) {
      this.options.onStatus("reconnecting", this.lastFailure || undefined, this.connectionInfo())
      return
    }
    const phase = this.options.resolveConnection ? "starting" : "connecting"
    this.options.onStatus(phase, undefined, this.connectionInfo())
  }

  private reportRetryState(): void {
    const info = this.connectionInfo()
    if (this.connectedOnce) {
      this.options.onStatus("reconnecting", this.lastFailure, info)
      return
    }
    const failureDelay = this.options.startupFailureDelayMs ?? 3_000
    if (info.elapsedMs >= failureDelay) {
      this.clearFailureEscalation()
      this.options.onStatus("unavailable", this.lastFailure, info)
      return
    }
    this.reportConnectionProgress()
    if (this.failureEscalationTimer) return
    this.failureEscalationTimer = setTimeout(() => {
      this.failureEscalationTimer = null
      if (this.closedByClient || this.connectedOnce || !this.lastFailure) return
      this.options.onStatus("unavailable", this.lastFailure, this.connectionInfo())
    }, Math.max(0, failureDelay - info.elapsedMs))
  }

  private clearFailureEscalation(): void {
    if (this.failureEscalationTimer) clearTimeout(this.failureEscalationTimer)
    this.failureEscalationTimer = null
  }

  private write(event: OutboundEvent): void {
    if (this.options.expectedGatewayId && !this.identityVerified) throw new Error("Desktop identity not verified")
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      throw new Error("gateway connection is not open")
    }
    this.socket.send(JSON.stringify(event))
  }
}
