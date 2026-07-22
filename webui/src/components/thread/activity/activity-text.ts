export function redactActivityText(value: string): string {
  return value
    .replace(/(https?:\/\/)[^/@\s]+@/gi, "$1<redacted>@")
    .replace(/\b(Bearer)\s+[A-Za-z0-9._~+/=-]+/gi, "$1 <redacted>")
    .replace(
      /(^|[\s;])((?:[A-Z0-9_]*)(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|PASS|AUTH)(?:[A-Z0-9_]*))=(?:"[^"]*"|'[^']*'|[^\s]+)/gim,
      "$1$2=<redacted>",
    )
    .replace(
      /(--(?:api-?key|access-?token|token|secret|password)(?:=|\s+))(?:"[^"]*"|'[^']*'|[^\s]+)/gi,
      "$1<redacted>",
    )
    .replace(/([?&](?:api_?key|access_?token|token|secret|password)=)[^&\s]+/gi, "$1<redacted>")
    .replace(
      /(["']?authorization["']?\s*[:=]\s*["']?)[^"'\r\n,;}]+/gi,
      "$1<redacted>",
    )
    .replace(
      /(["']?(?:api[_-]?key|access[_-]?token|token|secret|password)["']?\s*[:=]\s*)["']?[^"'\s,&;}]+["']?/gi,
      "$1<redacted>",
    )
    .replace(/\b(?:sk(?:-proj)?|xox[baprs]?|xapp)[-_][A-Za-z0-9._-]{8,}\b/gi, "<redacted>")
    .replace(/\bgh[pousr]_[A-Za-z0-9]{12,}\b/g, "<redacted>")
    .replace(/\bAKIA[A-Z0-9]{16}\b/g, "<redacted>")
    .replace(/\b\d{6,12}:[A-Za-z0-9_-]{20,}\b/g, "<redacted>");
}

export function redactShellCommand(command: string): string {
  return redactActivityText(command).replaceAll("<redacted>", "••••");
}

export function compactActivityPath(value: string): string {
  return value
    .replace(/\/Users\/[^/\s"']+/g, "~")
    .replace(/\/home\/[^/\s"']+/g, "~")
    .replace(/\/private\/tmp\/[^\s"']+/g, "/tmp/…")
    .replace(/\/var\/folders\/[^\s"']+/g, "/var/folders/…");
}

export function safeActivityDetail(value: string, maxLength = 96): string {
  return truncateMiddle(
    compactActivityPath(redactActivityText(value))
      .replace(/\/\.nanobot\/tool-results\/[^\s"']+/g, "/.nanobot/tool-results/…")
      .replace(/\s+/g, " ")
      .replace(/^["']|["']$/g, "")
      .trim(),
    maxLength,
  );
}

export function summarizeShellCommand(command: string): string {
  const lines = redactShellCommand(command.replace(/\r\n/g, "\n"))
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  const firstLine = compactActivityPath(lines[0] || "command");
  const firstPreview = truncateMiddle(firstLine, 92);
  return lines.length <= 1
    ? firstPreview
    : `${firstPreview} · script, ${lines.length} lines`;
}

function truncateMiddle(value: string, maxLength: number): string {
  if (value.length <= maxLength) return value;
  const head = Math.ceil((maxLength - 1) * 0.62);
  const tail = Math.floor((maxLength - 1) * 0.38);
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
}
