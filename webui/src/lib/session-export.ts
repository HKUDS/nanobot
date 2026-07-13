import { fmtDateTime } from "@/lib/format";
import type { ChatSummary, ToolProgressEvent, UIFileEdit, UIMessage } from "@/lib/types";

interface BuildSessionMarkdownOptions {
  session: Pick<ChatSummary, "key" | "createdAt" | "updatedAt">;
  title: string;
  messages: UIMessage[];
  locale?: string;
}

const ROLE_LABELS: Record<string, string> = {
  user: "User",
  assistant: "Assistant",
  tool: "Tool",
  system: "System",
};

function normalizeBlankLines(value: string): string {
  return value.replace(/\r\n/g, "\n").trim();
}

function safeJsonSummary(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value.trim();
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function toolEventSummary(event: ToolProgressEvent): string {
  const name = event.name?.trim() || "tool";
  const phase = event.phase?.trim() || "event";
  const suffix = event.error
    ? `: ${safeJsonSummary(event.error)}`
    : "";
  return `- ${name} (${phase})${suffix}`;
}

function fileEditSummary(edit: UIFileEdit): string {
  const operation = edit.operation === "delete" ? "deleted" : "edited";
  const status = edit.status === "error" ? " failed" : "";
  const binary = edit.binary ? ", binary" : "";
  const delta = edit.operation === "delete"
    ? ""
    : `, +${edit.added}/-${edit.deleted}`;
  const error = edit.error ? `: ${edit.error}` : "";
  return `- ${operation}${status} ${edit.path}${delta}${binary}${error}`;
}

function activityLines(message: UIMessage): string[] {
  const lines: string[] = [];
  for (const trace of message.traces ?? []) {
    const text = trace.trim();
    if (text) lines.push(`- ${text}`);
  }
  const content = message.content.trim();
  if (content && !lines.some((line) => line.slice(2) === content)) {
    lines.push(`- ${content}`);
  }
  for (const event of message.toolEvents ?? []) {
    lines.push(toolEventSummary(event));
  }
  for (const edit of message.fileEdits ?? []) {
    lines.push(fileEditSummary(edit));
  }
  if (message.media?.length) {
    for (const media of message.media) {
      lines.push(`- ${media.kind}: ${media.name || media.url || "attachment"}`);
    }
  }
  return lines;
}

function renderActivity(message: UIMessage, locale?: string): string {
  const lines = activityLines(message);
  if (!lines.length) return "";
  const timestamp = fmtDateTime(message.createdAt, locale);
  const label = timestamp ? `Activity - ${timestamp}` : "Activity";
  return [
    "<details>",
    `<summary>${label}</summary>`,
    "",
    ...lines,
    "",
    "</details>",
  ].join("\n");
}

function renderMessage(message: UIMessage, locale?: string): string {
  if (message.kind === "trace") return renderActivity(message, locale);
  const role = ROLE_LABELS[message.role] ?? message.role;
  const timestamp = fmtDateTime(message.createdAt, locale);
  const heading = timestamp ? `## ${role} - ${timestamp}` : `## ${role}`;
  const content = normalizeBlankLines(message.content);
  const parts = [heading];
  if (message.reasoning?.trim()) {
    parts.push(
      "",
      "<details>",
      "<summary>Reasoning</summary>",
      "",
      normalizeBlankLines(message.reasoning),
      "",
      "</details>",
    );
  }
  if (content) parts.push("", content);
  if (message.media?.length) {
    parts.push(
      "",
      ...message.media.map((media) => `- ${media.kind}: ${media.name || media.url || "attachment"}`),
    );
  }
  return parts.join("\n");
}

export function buildSessionMarkdown({
  session,
  title,
  messages,
  locale,
}: BuildSessionMarkdownOptions): string {
  const cleanedTitle = title.trim() || "Nanobot session";
  const metadata = [
    `# ${cleanedTitle}`,
    "",
    `- Session: \`${session.key}\``,
  ];
  const createdAt = fmtDateTime(session.createdAt, locale);
  const updatedAt = fmtDateTime(session.updatedAt, locale);
  if (createdAt) metadata.push(`- Created: ${createdAt}`);
  if (updatedAt) metadata.push(`- Last active: ${updatedAt}`);

  const body = messages
    .map((message) => renderMessage(message, locale))
    .filter(Boolean);

  if (!body.length) {
    body.push("_No transcript messages were available._");
  }
  return [...metadata, "", ...body, ""].join("\n\n");
}

export function sessionMarkdownFilename(title: string, key: string): string {
  const base = (title.trim() || key)
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fff]+/gi, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
  return `${base || "nanobot-session"}.md`;
}

export function downloadMarkdownFile(filename: string, markdown: string): void {
  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
