import { safeActivityDetail } from "./activity-text";
import { formatCompactWebUrl, parseSafeActivityHttpUrl } from "./web-url";

export type McpActivityStatus = "running" | "done" | "error";

export interface McpActivityDescription {
  action: string;
  target?: string;
}

export function describeMcpActivity(
  toolName: string,
  args: unknown,
  status: McpActivityStatus,
): McpActivityDescription {
  const name = toolName.toLowerCase();

  if (matches(name, "navigate", "goto", "open_url", "visit")) {
    return describe(status, "Opening", "Opened", "Could not open", value(args, ["url"]));
  }
  if (matches(name, "click", "tap")) {
    return describe(status, "Clicking", "Clicked", "Could not click", elementTarget(args));
  }
  if (matches(name, "type", "fill", "enter_text", "insert_text")) {
    const target = value(args, ["element", "selector", "ref", "name"]);
    return describe(status, "Entering text", "Entered text", "Could not enter text", target && `in ${target}`);
  }
  if (matches(name, "press_key", "keypress")) {
    return describe(status, "Pressing", "Pressed", "Could not press", value(args, ["key"]));
  }
  if (matches(name, "hover")) {
    return describe(status, "Hovering over", "Hovered over", "Could not hover over", elementTarget(args));
  }
  if (matches(name, "select", "select_option")) {
    return describe(status, "Selecting", "Selected", "Could not select", elementTarget(args));
  }
  if (matches(name, "snapshot", "inspect", "get_page_content", "page_content")) {
    return describe(status, "Inspecting page", "Inspected page", "Could not inspect page");
  }
  if (matches(name, "screenshot", "capture_screenshot")) {
    return describe(status, "Capturing screenshot", "Captured screenshot", "Could not capture screenshot");
  }
  if (matches(name, "wait", "wait_for")) {
    return describe(status, "Waiting for page", "Waited for page", "Page did not become ready");
  }
  if (matches(name, "search", "web_search")) {
    return describe(status, "Searching", "Searched", "Could not search", value(args, ["query", "q"]));
  }

  const action = humanizeToolName(toolName);
  if (status === "running") return { action: `Running ${action}` };
  if (status === "error") return { action: `${action} failed` };
  return { action: `${action} completed` };
}

function describe(
  status: McpActivityStatus,
  running: string,
  done: string,
  failed: string,
  target?: string,
): McpActivityDescription {
  return {
    action: status === "running" ? running : status === "error" ? failed : done,
    target: target ? compactUrl(target) : undefined,
  };
}

function matches(name: string, ...actions: string[]): boolean {
  return actions.some((action) => name === action || name.endsWith(`_${action}`));
}

function elementTarget(args: unknown): string | undefined {
  return value(args, ["element", "selector", "ref", "name", "text"]);
}

function value(args: unknown, keys: string[]): string | undefined {
  if (!args || typeof args !== "object" || Array.isArray(args)) return undefined;
  const record = args as Record<string, unknown>;
  for (const key of keys) {
    const candidate = record[key];
    if (typeof candidate === "string" && candidate.trim()) return candidate.trim();
    if (typeof candidate === "number" || typeof candidate === "boolean") return String(candidate);
  }
  return undefined;
}

function compactUrl(value: string): string {
  const url = parseSafeActivityHttpUrl(value);
  if (url) return formatCompactWebUrl(url);
  if (/^https?:\/\//i.test(value.trim())) return "Private address";
  return safeActivityDetail(value, 80);
}

function humanizeToolName(value: string): string {
  const words = value
    .replace(/^(?:browser|page|playwright)[_.-]+/i, "")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_.-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
  return words ? `${words[0].toUpperCase()}${words.slice(1)}` : "Tool call";
}
