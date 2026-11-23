import { commandLocale } from "../../../packages/client-events/command-result"

/** POSIX message locale precedence; Windows may expose only the system locale. */
export function terminalLocale(): string {
  const raw = process.env.LC_ALL || process.env.LC_MESSAGES || process.env.LANG || Intl.DateTimeFormat().resolvedOptions().locale
  return commandLocale(raw)
}
