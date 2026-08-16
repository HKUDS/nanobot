import type { ToolProgressEvent } from "./protocol"

export function mergeToolEvent(
  previous: ToolProgressEvent | undefined,
  next: ToolProgressEvent,
): ToolProgressEvent {
  if (!previous) return next
  return {
    ...previous,
    ...next,
    arguments: next.arguments ?? previous.arguments,
    result: next.result ?? previous.result,
    error: next.error ?? previous.error,
  }
}

export function renderToolEvent(event: ToolProgressEvent): string {
  const phase = event.phase || "start"
  const marker = phase === "error" ? "×" : phase === "end" ? "✓" : "›"
  const name = (event.name || "tool").trim()
  const args = record(event.arguments)
  const result = record(event.result)
  const detail = phase === "error" ? compact(event.error) : toolDetail(name, args, result)
  return `  ${marker} ${toolLabel(name, phase, args)}${detail ? `  ${detail}` : ""}`
}

function toolLabel(
  name: string,
  phase: string,
  args: Record<string, unknown>,
): string {
  if (/^(?:exec|exec_command|shell|run_command)$/u.test(name)) {
    const command = compact(args.command ?? args.cmd)
    if (/(?:^|\s)(?:pytest|ruff|pyright|basedpyright|cargo\s+test|go\s+test|(?:bun|npm|pnpm|yarn)(?:\s+run)?\s+test)(?:\s|$)/iu.test(command)) {
      return "Testing"
    }
    return phase === "end" ? "Ran" : phase === "error" ? "Command failed" : "Running"
  }
  if (/^(?:read_file|read)$/u.test(name)) return "Read"
  if (/^(?:write_file|write)$/u.test(name)) return phase === "end" ? "Edited" : "Editing"
  if (/^(?:edit_file|apply_patch|edit)$/u.test(name)) return phase === "end" ? "Edited" : "Editing"
  if (name === "web_search") return "Search web"
  if (name === "web_fetch") return "Fetch"
  return name
}

function toolDetail(
  name: string,
  args: Record<string, unknown>,
  result: Record<string, unknown>,
): string {
  if (/^(?:exec|exec_command|shell|run_command)$/u.test(name)) {
    return compact(args.command ?? args.cmd ?? result.output)
  }
  if (/^(?:read_file|write_file|edit_file|apply_patch|read|write|edit)$/u.test(name)) {
    return compact(args.path ?? args.file_path ?? result.path)
  }
  if (name === "web_search") return compact(args.query ?? args.q)
  if (name === "web_fetch") return compact(args.url)
  if (/session/u.test(name)) return compact(args.session_key ?? args.chat_id ?? args.query)
  if (Object.keys(args).length) return compact(args)
  return Object.keys(result).length ? compact(result) : ""
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function compact(value: unknown): string {
  if (value == null || value === "") return ""
  const text = typeof value === "string" ? value : JSON.stringify(value)
  return text.length > 88 ? `${text.slice(0, 85)}…` : text
}
