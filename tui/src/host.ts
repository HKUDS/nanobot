export type HostAgentState = "idle" | "working" | "blocked" | "unknown"

export interface HostMetadata {
  model?: string
  branch?: string
  workspace?: string
  task?: string
  action?: string
}

export interface TuiHost {
  readonly hosted: boolean
  reportState(state: HostAgentState, message?: string): void
  reportSession(sessionId: string): void
  reportMetadata(metadata: HostMetadata): void
  release(): void
}

export function currentGitBranch(workspace: string): string {
  const path = workspace.trim()
  if (!path) return ""
  try {
    const branch = spawnText(["git", "-C", path, "branch", "--show-current"])
    if (branch) return branch
    const revision = spawnText(["git", "-C", path, "rev-parse", "--short", "HEAD"])
    return revision ? `@${revision}` : ""
  } catch {
    return ""
  }
}

type Environment = Record<string, string | undefined>
type CommandRunner = (command: readonly string[]) => Promise<void>

const AGENT = "nanobot"
const LIFECYCLE_SOURCE = "nanobot:tui"
const METADATA_SOURCE = "nanobot:tui:metadata"
const METADATA_KEYS = ["model", "branch", "workspace", "task", "action"] as const
const METADATA_FLUSH_MS = 32

class StandaloneHost implements TuiHost {
  readonly hosted = false
  reportState(): void {}
  reportSession(): void {}
  reportMetadata(): void {}
  release(): void {}
}

class HerdrHost implements TuiHost {
  readonly hosted = true
  private sequence = 0
  private released = false
  private lastState = ""
  private lastSession = ""
  private metadata: HostMetadata = {}
  private readonly pendingMetadata = new Set<typeof METADATA_KEYS[number]>()
  private metadataTimer: ReturnType<typeof setTimeout> | null = null
  private queue: Promise<void> = Promise.resolve()

  constructor(
    private readonly paneId: string,
    private readonly binary: string,
    private readonly run: CommandRunner,
  ) {}

  reportState(state: HostAgentState, message = ""): void {
    if (this.released) return
    const cleanMessage = normalize(message)
    const fingerprint = `${state}\0${cleanMessage}\0${this.lastSession}`
    if (fingerprint === this.lastState) return
    this.lastState = fingerprint
    // Preserve causal ordering when a semantic state transition follows a
    // pending metadata snapshot; repeated working heartbeats still stay free.
    this.flushMetadata()
    const args = [
      "pane", "report-agent", this.paneId,
      "--source", LIFECYCLE_SOURCE,
      "--agent", AGENT,
      "--state", state,
      "--seq", String(this.nextSequence()),
    ]
    if (cleanMessage) args.push("--message", cleanMessage)
    if (this.lastSession) args.push("--agent-session-id", this.lastSession)
    this.enqueue(args)
  }

  reportSession(sessionId: string): void {
    if (this.released) return
    const cleanSession = normalize(sessionId, 256)
    if (!cleanSession || cleanSession === this.lastSession) return
    this.lastSession = cleanSession
    this.lastState = ""
    this.flushMetadata()
    this.enqueue([
      "pane", "report-agent-session", this.paneId,
      "--source", LIFECYCLE_SOURCE,
      "--agent", AGENT,
      "--agent-session-id", cleanSession,
      "--seq", String(this.nextSequence()),
    ])
  }

  reportMetadata(next: HostMetadata): void {
    if (this.released) return
    for (const key of METADATA_KEYS) {
      if (!(key in next)) continue
      const value = normalize(next[key])
      if (value === normalize(this.metadata[key])) continue
      this.pendingMetadata.add(key)
    }
    if (!this.pendingMetadata.size) return
    this.metadata = { ...this.metadata, ...next }
    if (this.metadataTimer) return
    this.metadataTimer = setTimeout(() => this.flushMetadata(), METADATA_FLUSH_MS)
  }

  private flushMetadata(): void {
    if (this.metadataTimer) clearTimeout(this.metadataTimer)
    this.metadataTimer = null
    if (!this.pendingMetadata.size) return
    const args = [
      "pane", "report-metadata", this.paneId,
      "--source", METADATA_SOURCE,
      "--agent", AGENT,
      "--display-agent", AGENT,
      "--seq", String(this.nextSequence()),
    ]
    const task = normalize(this.metadata.task)
    args.push(task ? "--title" : "--clear-title")
    if (task) args.push(task)
    for (const key of this.pendingMetadata) {
      const value = normalize(this.metadata[key])
      args.push(value ? "--token" : "--clear-token", value ? `${key}=${value}` : key)
    }
    this.pendingMetadata.clear()
    this.enqueue(args)
  }

  release(): void {
    if (this.released) return
    this.flushMetadata()
    this.released = true
    const clear = [
      "pane", "report-metadata", this.paneId,
      "--source", METADATA_SOURCE,
      "--clear-title", "--clear-display-agent", "--clear-state-labels",
      "--seq", String(this.nextSequence()),
    ]
    for (const key of METADATA_KEYS) clear.push("--clear-token", key)
    this.enqueue(clear)
    this.enqueue([
      "pane", "release-agent", this.paneId,
      "--source", LIFECYCLE_SOURCE,
      "--agent", AGENT,
      "--seq", String(this.nextSequence()),
    ])
  }

  private nextSequence(): number {
    this.sequence += 1
    return this.sequence
  }

  private enqueue(args: string[]): void {
    const command = [this.binary, ...args]
    this.queue = this.queue.then(() => this.run(command)).catch(() => {})
  }
}

function normalize(value: string | undefined, limit = 80): string {
  return (value || "").replace(/[\u0000-\u001f\u007f]+/gu, " ").replace(/\s+/gu, " ").trim().slice(0, limit)
}

async function runCommand(command: readonly string[]): Promise<void> {
  const child = Bun.spawn([...command], { stdout: "ignore", stderr: "ignore" })
  await child.exited
}

function spawnText(command: readonly string[]): string {
  const result = Bun.spawnSync([...command], { stdout: "pipe", stderr: "ignore" })
  if (result.exitCode !== 0) return ""
  return new TextDecoder().decode(result.stdout).trim()
}

export function createTuiHost(
  environment: Environment = process.env,
  run: CommandRunner = runCommand,
): TuiHost {
  const paneId = environment.HERDR_PANE_ID?.trim() || ""
  if (environment.HERDR_ENV !== "1" || !paneId) return new StandaloneHost()
  return new HerdrHost(paneId, environment.HERDR_BIN_PATH?.trim() || "herdr", run)
}
