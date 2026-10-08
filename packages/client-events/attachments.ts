/** Local preview data is never included in a WebSocket message. */
export interface DraftAttachment { data_url: string; name?: string }
export interface AttachmentReference { reference: string; name?: string }
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
  if (!capability || !stillConnected()) throw new Error("Attachment upload connection is not ready");
  const url = new URL(capability.path, baseUrl.replace(/^ws:/, "http:").replace(/^wss:/, "https:"));
  if (!["http:", "https:"].includes(url.protocol)) throw new Error("HTTP upload is unavailable");
  // No handshake credentials in the URL, no redirects leaking the capability.
  url.search = "";
  url.username = "";
  url.password = "";
  const references: AttachmentReference[] = [];
  for (const draft of drafts) {
    if (!stillConnected()) throw new Error("Connection changed during attachment upload");
    const match = /^data:([^;,]+);base64,([\s\S]*)$/.exec(draft.data_url);
    if (!match?.[1] || !match[2]) throw new Error("Invalid attachment preview");
    const raw = atob(match[2]);
    const bytes = Uint8Array.from(raw, (character) => character.charCodeAt(0));
    const response = await fetch(url, {
      method: "POST", redirect: "error", credentials: "omit",
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
