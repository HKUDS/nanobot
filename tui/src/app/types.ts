import type { ThemeMode } from "@opentui/core"

import type {
  GatewayConnection,
  MessageOptions,
  RecoveryState,
  WorkspaceScopePayload,
} from "../client"

export interface AppOptions {
  resolveConnection?: () => Promise<GatewayConnection>
  desktopGatewayId?: string
  wsUrl?: string
  bootstrapUrl?: string
  bootstrapSecret?: string
  healthUrl?: string
  apiUrl: string
  apiToken: string
  chatId?: string
  model: string
  modelPreset: string
  workspace: string
  version: string
  access: string
  theme: "auto" | ThemeMode
  onDetach?: (chatId?: string) => void
  onExit?: (chatId: string) => void
}

export interface ChatClient {
  readonly activeChatId: string
  connect(): void
  close(): void
  send(content: string, options?: MessageOptions): string
  attach(chatId: string): void
  newChat(scope?: WorkspaceScopePayload): void
  forkChat?(sourceChatId: string, beforeUserIndex: number, title?: string): void
  setWorkspaceScope(scope: WorkspaceScopePayload): void
  updateRecovery(
    action: "continue" | "dismiss",
    chatId: string,
    recoveryId: string,
  ): Promise<RecoveryState>
}
