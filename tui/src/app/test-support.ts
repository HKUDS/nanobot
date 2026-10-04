import { MockTreeSitterClient, type TestRendererSetup } from "@opentui/core/testing"

import type { MessageOptions, RecoveryState, WorkspaceScopePayload } from "../client"
import { NanobotTui, type AppOptions } from "./app"

export const options: AppOptions = {
  wsUrl: "ws://localhost.invalid/ws",
  apiUrl: "",
  apiToken: "",
  model: "test/model",
  modelPreset: "default",
  workspace: "/tmp/nanobot-workspace",
  version: "test",
  access: "workspace access",
  theme: "auto",
}

interface HiddenScrollBar {
  visible: boolean
  slider: { visible: boolean }
  startArrow: { visible: boolean }
  endArrow: { visible: boolean }
}

export interface HiddenScrollBox {
  verticalScrollBar: HiddenScrollBar
  horizontalScrollBar: HiddenScrollBar
}

export function occurrences(frame: string, value: string): number {
  return frame.split(value).length - 1
}

export function contrastRatio(foreground: string, background: string): number {
  const luminance = (color: string) => {
    const channel = (offset: number) => {
      const value = Number.parseInt(color.slice(offset, offset + 2), 16) / 255
      return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
    }
    return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5)
  }
  const [lighter, darker] = [luminance(foreground), luminance(background)].sort((a, b) => b - a)
  return ((lighter ?? 0) + 0.05) / ((darker ?? 0) + 0.05)
}

export async function waitUntil(predicate: () => boolean, timeout = 1_000): Promise<void> {
  const deadline = Date.now() + timeout
  while (!predicate() && Date.now() < deadline) await Bun.sleep(5)
  if (!predicate()) throw new Error(`condition was not met within ${timeout}ms`)
}

export function client(
  sent: string[] = [],
  attached: string[] = [],
  newChats: string[] = [],
  sentOptions: MessageOptions[] = [],
  forks: Array<{ source: string; before: number; title?: string }> = [],
  scopes: WorkspaceScopePayload[] = [],
) {
  return {
    activeChatId: "chat",
    connect() {},
    close() {},
    send(content: string, messageOptions: MessageOptions = {}) {
      sent.push(content)
      sentOptions.push(messageOptions)
      return "turn"
    },
    attach(chatId: string) {
      attached.push(chatId)
    },
    newChat(_scope?: WorkspaceScopePayload) {
      newChats.push("new")
    },
    forkChat(source: string, before: number, title?: string) {
      forks.push({ source, before, ...(title ? { title } : {}) })
    },
    setWorkspaceScope(scope: WorkspaceScopePayload) {
      scopes.push(scope)
    },
    updateRecovery(
      _action: "continue" | "dismiss",
      _chatId: string,
      recoveryId: string,
    ): Promise<RecoveryState> {
      return Promise.resolve({ status: "recovered" as const, recovery_id: recoveryId })
    },
  }
}

export const mount = (setup: TestRendererSetup, sent: string[] = []) => NanobotTui.mount(
  setup.renderer,
  options,
  client(sent),
  new MockTreeSitterClient({ autoResolveTimeout: 0 }),
)
