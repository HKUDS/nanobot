/**
 * Off-main-thread image encoder.
 *
 * Accepts a ``File``, validates it via magic bytes (ignoring the extension to
 * defeat rename-based spoofs), and either passes through or *normalizes* the
 * bytes so the resulting base64 data URL stays ≤ ``TARGET_MAX_BYTES``. The
 * normalization path uses ``createImageBitmap`` + ``OffscreenCanvas`` so the
 * full decode/resize/re-encode cycle never blocks the UI thread.
 *
 * Output contract:
 *   ``{ok: true, dataUrl, mime, bytes, origBytes, normalized}`` on success, or
 *   ``{ok: false, reason}`` for every recoverable failure — magic-bytes
 *   mismatch, unsupported MIME, decode error, or a post-normalization payload
 *   that *still* exceeds the budget (extreme aspect ratios).
 */

/// <reference lib="webworker" />

// --- Types -------------------------------------------------------------------

export type EncodeInput = {
  id: string;
  file: File;
};

export type EncodeSuccess = {
  id: string;
  ok: true;
  dataUrl: string;
  mime: string;
  bytes: number;
  origBytes: number;
  /** True iff the Worker re-encoded the image to hit the size budget. */
  normalized: boolean;
};

export type EncodeFailure = {
  id: string;
  ok: false;
  reason:
    | "invalid_mime"
    | "magic_mismatch"
    | "too_large_after_normalize"
    | "decode_failed"
    | "io";
};

export type EncodeResponse = EncodeSuccess | EncodeFailure;

// --- Budgets -----------------------------------------------------------------

/** Upper bound for the final base64-decoded payload. Matches the server-side
 * safeguard (8 MB) minus safety margin; anything this function yields should
 * safely pass ``_MAX_IMAGE_BYTES`` on the server. */
export const TARGET_MAX_BYTES = 6 * 1024 * 1024;

/** Long-edge pixel cap when we resize a large image. 2048 keeps retina UIs
 * crisp while bounding decode cost and matching most LLM vision tiers'
 * internal downscale target. */
const NORMALIZE_MAX_EDGE = 2048;

/** JPEG/WebP quality during normalization. 0.85 is the sweet spot — visually
 * lossless for content photography, ~30% smaller than libjpeg default. */
const WEBP_QUALITY = 0.85;

/** PNG / GIF kept as PNG after normalization so crisp UI screenshots stay
 * lossless. JPEG / WebP re-encode as WebP for better compression. */
const NORMALIZE_LOSSY_MIMES = new Set(["image/jpeg", "image/webp"]);

const SUPPORTED_MIMES = new Set([
  "image/png",
  "image/jpeg",
  "image/webp",
  "image/gif",
]);

// --- Magic bytes -------------------------------------------------------------

/** Sniff the first 12 bytes; returns the canonical MIME or ``null``.
 *
 * Covers PNG, JPEG, WebP, GIF — the same whitelist honoured by the server.
 */
export function sniffImageMime(bytes: Uint8Array): string | null {
  if (bytes.length >= 8) {
    if (
      bytes[0] === 0x89 &&
      bytes[1] === 0x50 &&
      bytes[2] === 0x4e &&
      bytes[3] === 0x47 &&
      bytes[4] === 0x0d &&
      bytes[5] === 0x0a &&
      bytes[6] === 0x1a &&
      bytes[7] === 0x0a
    ) {
      return "image/png";
    }
  }
  if (bytes.length >= 3) {
    if (bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) {
      return "image/jpeg";
    }
  }
  if (bytes.length >= 6) {
    const g1 =
      bytes[0] === 0x47 && bytes[1] === 0x49 && bytes[2] === 0x46 &&
      bytes[3] === 0x38 && bytes[5] === 0x61;
    if (g1 && (bytes[4] === 0x37 || bytes[4] === 0x39)) {
      return "image/gif";
    }
  }
  if (bytes.length >= 12) {
    const riff =
      bytes[0] === 0x52 && bytes[1] === 0x49 && bytes[2] === 0x46 && bytes[3] === 0x46;
    const webp =
      bytes[8] === 0x57 && bytes[9] === 0x45 && bytes[10] === 0x42 && bytes[11] === 0x50;
    if (riff && webp) return "image/webp";
  }
  return null;
}

// --- Encoder -----------------------------------------------------------------

function bufferToBase64(buf: ArrayBuffer): string {
  // ``btoa`` can't take large strings — chunk through 32 KB windows.
  const bytes = new Uint8Array(buf);
  let binary = "";
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode.apply(
      null,
      bytes.subarray(i, i + CHUNK) as unknown as number[],
    );
  }
  return self.btoa(binary);
}

function computeScaledDims(
  srcW: number,
  srcH: number,
  maxEdge: number,
): { w: number; h: number } {
  const longest = Math.max(srcW, srcH);
  if (longest <= maxEdge) return { w: srcW, h: srcH };
  const scale = maxEdge / longest;
  return {
    w: Math.max(1, Math.round(srcW * scale)),
    h: Math.max(1, Math.round(srcH * scale)),
  };
}

async function normalize(
  file: File,
  sourceMime: string,
): Promise<{ dataUrl: string; mime: string; bytes: number } | { error: EncodeFailure["reason"] }> {
  // Re-encode paths: JPEG/WebP → WebP q=0.85; PNG/GIF → PNG (keep crisp).
  const targetMime = NORMALIZE_LOSSY_MIMES.has(sourceMime)
    ? "image/webp"
    : "image/png";
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    return { error: "decode_failed" };
  }
  const { w, h } = computeScaledDims(bitmap.width, bitmap.height, NORMALIZE_MAX_EDGE);
  try {
    const canvas = new OffscreenCanvas(w, h);
    const ctx = canvas.getContext("2d", { alpha: true });
    if (!ctx) {
      bitmap.close();
      return { error: "decode_failed" };
    }
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(bitmap, 0, 0, w, h);
    bitmap.close();
    const options: ImageEncodeOptions = { type: targetMime };
    if (targetMime === "image/webp") options.quality = WEBP_QUALITY;
    const blob = await canvas.convertToBlob(options);
    if (blob.size > TARGET_MAX_BYTES) {
      return { error: "too_large_after_normalize" };
    }
    const buf = await blob.arrayBuffer();
    const dataUrl = `data:${targetMime};base64,${bufferToBase64(buf)}`;
    return { dataUrl, mime: targetMime, bytes: blob.size };
  } catch {
    try {
      bitmap.close();
    } catch {
      // bitmap already closed
    }
    return { error: "decode_failed" };
  }
}

export async function encodeImageInWorker(
  input: EncodeInput,
): Promise<EncodeResponse> {
  const { id, file } = input;
  const origBytes = file.size;

  let buffer: ArrayBuffer;
  try {
    buffer = await file.arrayBuffer();
  } catch {
    return { id, ok: false, reason: "io" };
  }

  const head = new Uint8Array(buffer.slice(0, 12));
  const sniffed = sniffImageMime(head);
  if (!sniffed) return { id, ok: false, reason: "magic_mismatch" };
  if (!SUPPORTED_MIMES.has(sniffed)) {
    return { id, ok: false, reason: "invalid_mime" };
  }
  // Defend against MIME spoofing: the declared ``file.type`` can lie.
  if (file.type && SUPPORTED_MIMES.has(file.type) && file.type !== sniffed) {
    // Trust the magic bytes; proceed with the sniffed MIME.
  }

  if (origBytes <= TARGET_MAX_BYTES) {
    const dataUrl = `data:${sniffed};base64,${bufferToBase64(buffer)}`;
    return {
      id,
      ok: true,
      dataUrl,
      mime: sniffed,
      bytes: origBytes,
      origBytes,
      normalized: false,
    };
  }

  const result = await normalize(file, sniffed);
  if ("error" in result) {
    return { id, ok: false, reason: result.error };
  }
  return {
    id,
    ok: true,
    dataUrl: result.dataUrl,
    mime: result.mime,
    bytes: result.bytes,
    origBytes,
    normalized: true,
  };
}

// --- Worker boot -------------------------------------------------------------
// Only attach the message listener when running *inside* a Worker so the same
// module can be imported by tests (and by the thin ``imageEncode.ts`` wrapper
// in the main thread, which also calls ``encodeImageInWorker`` as a
// fall-through path when the Worker isn't available).

declare const self: DedicatedWorkerGlobalScope;

if (
  typeof self !== "undefined" &&
  typeof (self as unknown as { importScripts?: unknown }).importScripts ===
    "function"
) {
  self.addEventListener("message", async (event: MessageEvent<EncodeInput>) => {
    const response = await encodeImageInWorker(event.data);
    self.postMessage(response);
  });
}
