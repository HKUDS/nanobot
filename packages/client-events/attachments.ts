/** Preview bodies upload over HTTP; borrowed paths never upload file bytes. */
export interface LocalAttachment {
  path: string;
  name: string;
  size: number;
  mime: string;
  kind: "image" | "video" | "file";
  url: string;
}
export function isLocalAttachment(value: unknown): value is LocalAttachment {
  if (!value || typeof value !== "object") return false;
  const row = value as Record<string, unknown>;
  return typeof row.path === "string" && row.path.length > 0 && row.path.length <= 4096
    && typeof row.name === "string" && typeof row.mime === "string"
    && typeof row.size === "number" && Number.isSafeInteger(row.size) && row.size > 0
    && typeof row.kind === "string" && ["image", "video", "file"].includes(row.kind)
    && typeof row.url === "string" && (row.url === "" || row.url.startsWith("/api/media/"));
}
export type DraftAttachment =
  | { data_url: string; name?: string; path?: never }
  | { path: string; name?: string; data_url?: never };
export type AttachmentReference =
  | { reference: string; name?: string; path?: never }
  | { path: string; name?: string; reference?: never };

/** Recognize only a standalone pasted path, never search prose/code for one. */
export function pastedFilePath(text: string): string | null {
  let value = text.trim();
  if (!value || /[\r\n\0]/.test(value)) return null;
  const quoted = (value.startsWith('"') && value.endsWith('"'))
    || (value.startsWith("'") && value.endsWith("'"));
  if (quoted) value = value.slice(1, -1);
  if (!value || /["'`<>|]/.test(value) || /^[a-z][a-z\d+.-]*:\/\//i.test(value)
    || /^[a-z]:[\\/]fakepath[\\/]/i.test(value)) return null;
  if (/^(?:[a-z]:[\\/]|\/|\\\\|\.{1,2}[\\/]|~[\\/])/i.test(value)) return value;
  // Bare relative names and relative directory paths; whitespace needs quotes.
  return (quoted || !/\s/.test(value)) && /(?:[\\/]|\.[\w-]+$)/u.test(value)
    ? value : null;
}
export interface UploadCapability { path: string; token: string }

// Allow the gateway's five-minute body budget plus request/response overhead.
const UPLOAD_REQUEST_TIMEOUT_MS = 315_000;

export function uploadCapability(value: unknown): UploadCapability | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  return row.path === "/api/attachments" && typeof row.token === "string" && row.token.length > 0
    ? { path: row.path, token: row.token } : null;
}

export async function uploadAttachments(
  drafts: readonly DraftAttachment[], capability: UploadCapability | null,
  baseUrl: string, stillConnected: () => boolean,
): Promise<AttachmentReference[]> {
  const references: AttachmentReference[] = [];
  for (const draft of drafts) {
    if (!stillConnected()) throw new Error("Connection changed during attachment upload");
    if (draft.path !== undefined) {
      references.push({ path: draft.path, ...(draft.name ? { name: draft.name } : {}) });
      continue;
    }
    if (!capability) throw new Error("Attachment upload connection is not ready");
    const url = new URL(capability.path, baseUrl.replace(/^ws:/, "http:").replace(/^wss:/, "https:"));
    if (!["http:", "https:"].includes(url.protocol)) throw new Error("HTTP upload is unavailable");
    // Never send capabilities across redirects or forward URL credentials.
    url.search = "";
    url.username = "";
    url.password = "";
    const match = /^data:([^;,]+);base64,([\s\S]*)$/.exec(draft.data_url);
    if (!match?.[1] || !match[2]) throw new Error("Invalid attachment preview");
    const raw = atob(match[2]);
    const bytes = Uint8Array.from(raw, (character) => character.charCodeAt(0));
    const response = await fetch(url, {
      method: "POST", redirect: "error", credentials: "same-origin",
      headers: {
        Authorization: `Bearer ${capability.token}`,
        "Content-Type": match[1],
        ...(draft.name ? { "X-Attachment-Name": encodeURIComponent(draft.name) } : {}),
      },
      body: new Blob([bytes], { type: match[1] }),
      signal: AbortSignal.timeout(UPLOAD_REQUEST_TIMEOUT_MS),
    });
    if (!response.ok) throw new Error(`Attachment upload failed (${response.status})`);
    const result: unknown = await response.json();
    if (!result || typeof result !== "object" || !("reference" in result)
      || typeof result.reference !== "string") throw new Error("Invalid upload response");
    references.push({ reference: result.reference, ...(draft.name ? { name: draft.name } : {}) });
  }
  if (!stillConnected()) throw new Error("Connection changed during attachment upload");
  return references;
}
