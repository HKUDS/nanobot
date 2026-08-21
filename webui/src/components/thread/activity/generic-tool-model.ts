import type { TFunction } from "i18next";

import { compactActivityPath, redactActivityText } from "./activity-text";

export type GenericToolStatus = "running" | "done" | "error";
export type ToolFamily = "content-search" | "file-search" | "list" | "read" | "memory" | "generic";

export interface ToolField {
  key:
    | "query"
    | "pattern"
    | "glob"
    | "path"
    | "file_path"
    | "url"
    | "action"
    | "key"
    | "label"
    | "name"
    | "channel"
    | "chat_id"
    | "session_id"
    | "ui_summary";
  value: string;
}

export interface GenericToolTrace {
  name: string;
  family: ToolFamily;
  groupKey: string;
  fields: ToolField[];
  collectedSource: boolean;
}

export interface GenericToolRunItem {
  trace: GenericToolTrace;
  status: GenericToolStatus;
  error?: string;
}

export interface GenericToolPresentation {
  status: GenericToolStatus;
  label: string;
  detail: string;
  aside: string;
}

const CONTENT_SEARCH_TOOLS = new Set([
  "grep",
  "rg",
  "ripgrep",
  "search_code",
  "search_content",
  "search_files_content",
  "find_text",
]);
const FILE_SEARCH_TOOLS = new Set([
  "find",
  "find_file",
  "find_files",
  "glob",
  "search_files",
]);
const LIST_TOOLS = new Set(["list_dir", "list_directory", "list_files", "ls"]);
const READ_TOOLS = new Set(["read", "read_file", "read_text_file"]);
const MEMORY_TOOLS = new Set(["memory_search", "search_memory", "recall_memory"]);
const EXCLUDED_TOOL_PREFIXES = ["mcp_"];
const EXCLUDED_TOOLS = new Set([
  "apply_patch",
  "cli_anything_run",
  "edit_file",
  "exec",
  "exec_command",
  "execute_command",
  "run_cli_app",
  "run_command",
  "run_shell",
  "shell",
  "terminal",
  "web_fetch",
  "web_search",
  "x_search",
  "write_file",
]);

export function parseGenericToolTrace(line: string): GenericToolTrace | null {
  const call = parseCall(line);
  if (!call || isExcludedTool(call.name)) return null;
  const family = toolFamily(call.name);
  const fields = safeFields(call.args);
  const collectedSource = fields.some((field) => isCollectedSourcePath(field.value));
  return {
    name: call.name,
    family,
    groupKey: family === "generic"
      ? `${family}:${call.name}`
      : `${family}:${collectedSource ? "collected" : "workspace"}`,
    fields,
    collectedSource,
  };
}

export function canGroupGenericToolRuns(previous: GenericToolRunItem, next: GenericToolRunItem): boolean {
  return previous.trace.groupKey === next.trace.groupKey;
}

function compactGenericToolPath(value: string): string {
  const normalized = redactActivityText(value).replace(/\\/g, "/");
  if (isCollectedSourcePath(normalized)) {
    return truncateMiddle(normalized.split("/").pop() || "collected source", 64);
  }
  return compactActivityPath(normalized);
}

export function describeGenericToolRun(
  items: GenericToolRunItem[],
  t: TFunction,
): GenericToolPresentation {
  const status = aggregateStatus(items);
  const family = items[0]?.trace.family ?? "generic";
  const name = items[0]?.trace.name ?? "tool";
  const collected = items.length > 0 && items.every((item) => item.trace.collectedSource);
  return {
    status,
    label: activityLabel(family, status, collected, name, items, t),
    detail: activityDetail(items, family, name),
    aside: activityAside(items, family, t),
  };
}

function parseCall(line: string): { name: string; args: unknown } | null {
  const match = /^([a-zA-Z0-9_.-]+)\((.*)\)$/.exec(line.trim());
  if (!match) return null;
  const name = compactToolName(match[1]);
  let args: unknown;
  try {
    args = match[2].trim() ? JSON.parse(match[2]) : {};
  } catch {
    args = {};
  }
  return { name, args };
}

function compactToolName(name: string): string {
  return name.toLowerCase().split(".").pop() || name.toLowerCase();
}

function isExcludedTool(name: string): boolean {
  return EXCLUDED_TOOLS.has(name) || EXCLUDED_TOOL_PREFIXES.some((prefix) => name.startsWith(prefix));
}

function toolFamily(name: string): ToolFamily {
  if (CONTENT_SEARCH_TOOLS.has(name)) return "content-search";
  if (FILE_SEARCH_TOOLS.has(name)) return "file-search";
  if (LIST_TOOLS.has(name)) return "list";
  if (READ_TOOLS.has(name)) return "read";
  if (MEMORY_TOOLS.has(name)) return "memory";
  return "generic";
}

function safeFields(args: unknown): ToolField[] {
  if (!args || typeof args !== "object" || Array.isArray(args)) return [];
  const record = args as Record<string, unknown>;
  const fields: ToolField[] = [];
  for (const key of [
    "query",
    "pattern",
    "glob",
    "path",
    "file_path",
    "url",
    "action",
    "key",
    "label",
    "name",
    "channel",
    "chat_id",
    "session_id",
    "ui_summary",
  ] as const) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) {
      fields.push({ key, value: value.trim() });
    }
  }
  return fields;
}

function aggregateStatus(items: GenericToolRunItem[]): GenericToolStatus {
  if (items.some((item) => item.status === "error")) return "error";
  if (items.some((item) => item.status === "running")) return "running";
  return "done";
}

function activityLabel(
  family: ToolFamily,
  status: GenericToolStatus,
  collected: boolean,
  name: string,
  items: GenericToolRunItem[],
  t: TFunction,
): string {
  if (family === "content-search") {
    return statusCopy(
      status,
      collected ? t("message.agentActivity.reviewingSources") : t("message.agentActivity.searchingFiles"),
      collected ? t("message.agentActivity.reviewedSources") : t("message.agentActivity.searchedFiles"),
      collected ? t("message.agentActivity.reviewSourcesFailed") : t("message.agentActivity.searchFilesFailed"),
    );
  }
  if (family === "file-search") {
    return statusCopy(
      status,
      t("message.agentActivity.findingFiles"),
      t("message.agentActivity.foundFiles"),
      t("message.agentActivity.findFilesFailed"),
    );
  }
  if (family === "list") {
    return statusCopy(
      status,
      t("message.agentActivity.listingFiles"),
      t("message.agentActivity.listedFiles"),
      t("message.agentActivity.listFilesFailed"),
    );
  }
  if (family === "read") {
    return statusCopy(
      status,
      collected ? t("message.agentActivity.readingSource") : t("message.agentActivity.readingFile"),
      collected ? t("message.agentActivity.readSource") : t("message.agentActivity.readFile"),
      collected ? t("message.agentActivity.readSourceFailed") : t("message.agentActivity.readFileFailed"),
    );
  }
  if (family === "memory") {
    return statusCopy(
      status,
      t("message.agentActivity.searchingMemory"),
      t("message.agentActivity.searchedMemory"),
      t("message.agentActivity.searchMemoryFailed"),
    );
  }

  const action = fieldValue(items[0]?.trace, "action").toLowerCase();
  switch (name) {
    case "generate_image":
      return activityStatus(t, status, "generatingImage", "generatedImage", "generateImageFailed");
    case "spawn":
      return activityStatus(t, status, "delegatingTask", "delegatedTask", "delegateTaskFailed");
    case "message":
      return activityStatus(t, status, "sendingMessage", "sentMessage", "sendMessageFailed");
    case "my":
      return action === "set" || action === "modify"
        ? activityStatus(t, status, "updatingAgentSettings", "updatedAgentSettings", "updateAgentSettingsFailed")
        : activityStatus(t, status, "checkingAgentSettings", "checkedAgentSettings", "checkAgentSettingsFailed");
    case "cron":
      if (action === "add") return activityStatus(t, status, "schedulingAutomation", "scheduledAutomation", "scheduleAutomationFailed");
      if (action === "remove") return activityStatus(t, status, "removingAutomation", "removedAutomation", "removeAutomationFailed");
      return activityStatus(t, status, "checkingAutomations", "checkedAutomations", "checkAutomationsFailed");
    case "create_goal":
      return activityStatus(t, status, "startingLongTask", "startedLongTask", "startLongTaskFailed");
    case "update_goal":
      return activityStatus(t, status, "updatingLongTask", "updatedLongTask", "updateLongTaskFailed");
    case "write_stdin":
      return activityStatus(t, status, "continuingCommand", "continuedCommand", "continueCommandFailed");
    case "list_exec_sessions":
      return activityStatus(t, status, "checkingRunningCommands", "checkedRunningCommands", "checkRunningCommandsFailed");
    case "screenshot":
    case "capture_screenshot":
      return activityStatus(t, status, "capturingScreenshot", "capturedScreenshot", "captureScreenshotFailed");
    default: {
      const humanName = humanizeToolName(name);
      return statusCopy(
        status,
        t("message.agentActivity.runningTool", { name: humanName }),
        t("message.agentActivity.completedTool", { name: humanName }),
        t("message.agentActivity.completeToolFailed", { name: humanName }),
      );
    }
  }
}

function activityDetail(items: GenericToolRunItem[], family: ToolFamily, name: string): string {
  if (items.length !== 1) return "";
  const trace = items[0].trace;
  if (family === "content-search") {
    return quote(fieldValue(trace, "query") || fieldValue(trace, "pattern"));
  }
  if (family === "file-search") {
    return compactDetail(
      fieldValue(trace, "glob")
      || fieldValue(trace, "query")
      || fieldValue(trace, "pattern")
      || fieldValue(trace, "path"),
    );
  }
  if (family === "list" || family === "read") {
    return compactDetail(fieldValue(trace, "path") || fieldValue(trace, "file_path"));
  }
  if (family === "memory") return quote(fieldValue(trace, "query"));

  switch (name) {
    case "spawn":
      return safeText(fieldValue(trace, "label"));
    case "message":
      return safeText(fieldValue(trace, "channel"));
    case "my":
      return safeText(fieldValue(trace, "key"));
    case "cron":
      return safeText(fieldValue(trace, "name"));
    case "create_goal":
      return safeText(fieldValue(trace, "ui_summary"));
    case "update_goal":
      return safeText(fieldValue(trace, "action"));
    case "write_stdin":
      return compactIdentifier(fieldValue(trace, "session_id"));
    case "screenshot":
    case "capture_screenshot":
      return "";
    default:
      return "";
  }
}

function activityAside(items: GenericToolRunItem[], family: ToolFamily, t: TFunction): string {
  const pathCount = uniqueValues(items, ["path", "file_path"]).length;
  if (pathCount > 1) return t("message.agentActivity.files", { count: pathCount });
  if (items.length <= 1) return "";
  if (family === "content-search" || family === "file-search" || family === "memory") {
    return t("message.agentActivity.searches", { count: items.length });
  }
  return t("message.agentActivity.actions", { count: items.length });
}

function fieldValue(trace: GenericToolTrace | undefined, key: ToolField["key"]): string {
  return trace?.fields.find((field) => field.key === key)?.value ?? "";
}

function uniqueValues(items: GenericToolRunItem[], keys: ToolField["key"][]): string[] {
  const values = items.flatMap((item) => item.trace.fields)
    .filter((field) => keys.includes(field.key))
    .map((field) => field.value);
  return [...new Set(values)];
}

function statusCopy(status: GenericToolStatus, running: string, done: string, failed: string): string {
  return status === "running" ? running : status === "error" ? failed : done;
}

function activityStatus(
  t: TFunction,
  status: GenericToolStatus,
  running: string,
  done: string,
  failed: string,
): string {
  return statusCopy(
    status,
    t(`message.agentActivity.${running}`),
    t(`message.agentActivity.${done}`),
    t(`message.agentActivity.${failed}`),
  );
}

function compactDetail(value: string): string {
  return value ? truncateMiddle(compactGenericToolPath(value), 88) : "";
}

function safeText(value: string): string {
  return value ? truncateMiddle(redactActivityText(value).replace(/\s+/g, " ").trim(), 88) : "";
}

function quote(value: string): string {
  const safe = safeText(value);
  return safe ? `“${safe}”` : "";
}

function compactIdentifier(value: string): string {
  const safe = safeText(value);
  if (safe.length <= 16) return safe;
  return `${safe.slice(0, 7)}…${safe.slice(-5)}`;
}

function humanizeToolName(name: string): string {
  const words = name
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[._-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
  return words ? `${words[0].toUpperCase()}${words.slice(1)}` : "tool action";
}

function isCollectedSourcePath(value: string): boolean {
  const normalized = value.replace(/\\/g, "/");
  return normalized.includes("/.nanobot/tool-results/") || normalized.includes("/nanobot/tool-results/");
}

function truncateMiddle(value: string, maxLength: number): string {
  if (value.length <= maxLength) return value;
  const head = Math.ceil((maxLength - 1) * 0.62);
  const tail = Math.floor((maxLength - 1) * 0.38);
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
}
