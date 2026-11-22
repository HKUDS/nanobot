import { commandLocale, renderCommandResult } from "../../../packages/client-events/command-result"

/** POSIX message locale precedence; Windows may expose only the system locale. */
export function terminalLocale(): string {
  const raw = process.env.LC_ALL || process.env.LC_MESSAGES || process.env.LANG || Intl.DateTimeFormat().resolvedOptions().locale
  return commandLocale(raw)
}

export function terminalMessageText(event: { text: string; command_result?: unknown }): string {
  return event.command_result === undefined ? event.text : renderCommandResult(event.command_result, terminalLocale()) ?? event.text
}
