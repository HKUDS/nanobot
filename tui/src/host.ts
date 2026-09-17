export interface TuiHost {
  reportTitle(title: string): void
  release(): void
}

type Environment = Record<string, string | undefined>
type CommandRunner = (command: readonly string[]) => Promise<void>

const METADATA_SOURCE = "nanobot:tui:metadata"

export function configureOpenTuiEnvironment(
  environment: Environment = process.env,
  platform = process.platform,
): void {
  if (platform !== "win32") return

  // OpenTUI probes OSC 66 support on the main screen before its renderer is
  // active. Some Windows terminal hosts do not restore the cursor around that
  // probe, so shutdown resumes in terminal history instead of below the TUI.
  // Keep an explicit user choice, but use the safe default on Windows.
  environment.OPENTUI_FORCE_EXPLICIT_WIDTH ??= "false"
}

class StandaloneHost implements TuiHost {
  reportTitle(): void {}
  release(): void {}
}

class HerdrHost implements TuiHost {
  private sequence = 0
  private released = false
  private lastTitle = ""
  private queue: Promise<void> = Promise.resolve()

  constructor(
    private readonly paneId: string,
    private readonly binary: string,
    private readonly run: CommandRunner,
  ) {}

  reportTitle(title: string): void {
    if (this.released) return
    const cleanTitle = normalize(title)
    if (cleanTitle === this.lastTitle) return
    this.lastTitle = cleanTitle
    const args = [
      "pane", "report-metadata", this.paneId,
      "--source", METADATA_SOURCE,
      "--seq", String(this.nextSequence()),
      cleanTitle ? "--title" : "--clear-title",
    ]
    if (cleanTitle) args.push(cleanTitle)
    this.enqueue(args)
  }

  release(): void {
    if (this.released) return
    this.reportTitle("")
    this.released = true
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

function normalize(value: string, limit = 80): string {
  return value.replace(/[\u0000-\u001f\u007f]+/gu, " ").replace(/\s+/gu, " ").trim().slice(0, limit)
}

async function runCommand(command: readonly string[]): Promise<void> {
  const child = Bun.spawn([...command], { stdout: "ignore", stderr: "ignore" })
  await child.exited
}

export function createTuiHost(
  environment: Environment = process.env,
  run: CommandRunner = runCommand,
): TuiHost {
  const paneId = environment.HERDR_PANE_ID?.trim() || ""
  if (environment.HERDR_ENV !== "1" || !paneId) return new StandaloneHost()
  return new HerdrHost(paneId, environment.HERDR_BIN_PATH?.trim() || "herdr", run)
}
