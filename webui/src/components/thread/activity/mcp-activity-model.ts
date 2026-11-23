import type { TFunction } from "i18next";

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
  t: TFunction,
): McpActivityDescription {
  const name = toolName.toLowerCase();

  if (matches(name, "navigate", "goto", "open_url", "visit")) {
    return describe(status, t, "opening", "opened", "openFailed", value(args, ["url"]));
  }
  if (matches(name, "click", "tap")) {
    return describe(status, t, "clicking", "clicked", "clickFailed", elementTarget(args));
  }
  if (matches(name, "type", "fill", "enter_text", "insert_text")) {
    const target = value(args, ["element", "selector", "ref", "name"]);
    return describe(status, t, "enteringText", "enteredText", "enterTextFailed", target && t("message.agentActivity.inTarget", { target }));
  }
  if (matches(name, "press_key", "keypress")) {
    return describe(status, t, "pressing", "pressed", "pressFailed", value(args, ["key"]));
  }
  if (matches(name, "hover")) {
    return describe(status, t, "hovering", "hovered", "hoverFailed", elementTarget(args));
  }
  if (matches(name, "select", "select_option")) {
    return describe(status, t, "selecting", "selected", "selectFailed", elementTarget(args));
  }
  if (matches(name, "snapshot", "inspect", "get_page_content", "page_content")) {
    return describe(status, t, "inspectingPage", "inspectedPage", "inspectPageFailed");
  }
  if (matches(name, "screenshot", "capture_screenshot")) {
    return describe(status, t, "capturingScreenshot", "capturedScreenshot", "captureScreenshotFailed");
  }
  if (matches(name, "wait", "wait_for")) {
    return describe(status, t, "waitingForPage", "waitedForPage", "pageNotReady");
  }
  if (matches(name, "search", "web_search")) {
    return describe(status, t, "searchingPlain", "searchedPlain", "searchFailedPlain", value(args, ["query", "q"]));
  }

  const action = humanizeToolName(toolName, t);
  if (status === "running") return { action: t("message.agentActivity.runningTool", { name: action }) };
  if (status === "error") return { action: t("message.agentActivity.toolFailed", { name: action }) };
  return { action: t("message.agentActivity.toolCompleted", { name: action }) };
}

function describe(
  status: McpActivityStatus,
  t: TFunction,
  running: string,
  done: string,
  failed: string,
  target?: string,
): McpActivityDescription {
  return {
    action: t(`message.agentActivity.${status === "running" ? running : status === "error" ? failed : done}`),
    target: target ? compactUrl(target, t) : undefined,
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

function compactUrl(value: string, t: TFunction): string {
  const url = parseSafeActivityHttpUrl(value);
  if (url) return formatCompactWebUrl(url);
  if (/^https?:\/\//i.test(value.trim())) return t("message.agentActivity.privateAddress");
  return safeActivityDetail(value, 80);
}

function humanizeToolName(value: string, t: TFunction): string {
  const words = value
    .replace(/^(?:browser|page|playwright)[_.-]+/i, "")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_.-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
  return words ? `${words[0].toUpperCase()}${words.slice(1)}` : t("message.agentActivity.toolCall");
}
