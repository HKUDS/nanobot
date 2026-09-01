import type { UIMessage } from "@/lib/types";

/** Match websocket/session scrub: keep header + Result body only; trim model tail. */
const SUBAGENT_UI_RESULT_MAX_CHARS = 800;

/** Strip Task assignment + Summarize tail from persisted subagent announce blobs. */
export function scrubSubagentAnnounceBody(
  content: string,
  maxResultChars: number = SUBAGENT_UI_RESULT_MAX_CHARS,
): string {
  const stripped = content.replace(/\r\n/g, "\n").trim();
  const lines = stripped.split("\n");
  let header = "";
  if (lines.length > 0 && lines[0].startsWith("[Subagent")) {
    header = lines[0].trim();
  }

  const lower = stripped.toLowerCase();
  let key = "\nresult:\n";
  let ri = lower.indexOf(key);
  if (ri === -1) {
    key = "\nresult:";
    ri = lower.indexOf(key);
  }
  if (ri === -1) {
    return header || stripped;
  }

  let after = stripped.slice(ri + key.length).replace(/^\s+/, "");
  const summMarker = "summarize this naturally";
  const si = after.toLowerCase().indexOf(summMarker);
  if (si !== -1) {
    after = after.slice(0, si).trimEnd();
  }

  let body = after.trim();
  if (maxResultChars > 0 && body.length > maxResultChars) {
    body = `${body.slice(0, maxResultChars - 1).trimEnd()}…`;
  }

  if (header && body) {
    return `${header}\n\n${body}`;
  }
  return header || body || stripped;
}

/** Apply scrub to assistant rows that look like subagent inject announcements. */
export function scrubSubagentUiMessages(messages: UIMessage[]): UIMessage[] {
  return messages.map((m) => {
    if (m.role !== "assistant" || typeof m.content !== "string") {
      return m;
    }
    if (!m.content.includes("[Subagent")) {
      return m;
    }
    const content = scrubSubagentAnnounceBody(m.content);
    return content === m.content ? m : { ...m, content };
  });
}
