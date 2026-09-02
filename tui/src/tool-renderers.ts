import type { ToolProgressEvent } from "./protocol"

export interface ToolRenderOptions {
  workspace?: string
}

const PATH_DETAIL_LIMIT = 52

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

export function renderToolEvent(
  event: ToolProgressEvent,
  options: ToolRenderOptions = {},
): string {
  const phase = event.phase || "start"
  const marker = phase === "error" ? "×" : phase === "end" ? "✓" : "›"
  const name = (event.name || "tool").trim()
  const args = record(event.arguments)
  const result = record(event.result)
  const detail = phase === "error"
    ? compact(event.error)
    : toolDetail(name, args, result, options)
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
  if (/^(?:spawn|spawn_agent)$/u.test(name)) {
    return phase === "end" ? "Delegated" : phase === "error" ? "Delegation failed" : "Delegating"
  }
  if (name === "web_search") return "Search web"
  if (name === "web_fetch") return "Fetch"
  return name
}

function toolDetail(
  name: string,
  args: Record<string, unknown>,
  result: Record<string, unknown>,
  options: ToolRenderOptions,
): string {
  if (/^(?:exec|exec_command|shell|run_command)$/u.test(name)) {
    return compact(args.command ?? args.cmd ?? result.output)
  }
  if (/^(?:read_file|write_file|edit_file|apply_patch|read|write|edit)$/u.test(name)) {
    return compactPath(args.path ?? args.file_path ?? result.path, options.workspace)
  }
  if (/^(?:spawn|spawn_agent)$/u.test(name)) return compact(args.label ?? args.task, 56)
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

function compact(value: unknown, limit = 88): string {
  if (value == null || value === "") return ""
  const serialized = typeof value === "string" ? value : JSON.stringify(value)
  const text = (serialized || String(value)).replace(/\s+/gu, " ").trim()
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text
}

function compactPath(value: unknown, workspace?: string): string {
  if (value == null || value === "") return ""
  const normalized = String(value).replace(/\\/gu, "/").replace(/\/+$/u, "")
  const relative = workspaceRelativePath(normalized, workspace)
  if (relative.length <= PATH_DETAIL_LIMIT) return relative

  const parts = relative.split("/").filter(Boolean)
  let tail = parts.pop() || relative
  if (tail.length + 1 >= PATH_DETAIL_LIMIT) {
    return `…${tail.slice(-(PATH_DETAIL_LIMIT - 1))}`
  }
  while (parts.length) {
    const candidate = `${parts.at(-1)}/${tail}`
    if (`…/${candidate}`.length > PATH_DETAIL_LIMIT) break
    tail = candidate
    parts.pop()
  }
  return `…/${tail}`
}

function workspaceRelativePath(path: string, workspace?: string): string {
  if (!workspace) return path
  const base = workspace.replace(/\\/gu, "/").replace(/\/+$/u, "")
  const caseInsensitive = /^[a-z]:\//iu.test(path) || /^[a-z]:\//iu.test(base)
  const comparedPath = caseInsensitive ? path.toLowerCase() : path
  const comparedBase = caseInsensitive ? base.toLowerCase() : base
  if (comparedPath === comparedBase) return path.split("/").at(-1) || path
  if (comparedPath.startsWith(`${comparedBase}/`)) return path.slice(base.length + 1)
  return path
}
