import { useCallback, useEffect, useRef, useState } from "react";

import { encodeImage, type EncodeFailure } from "@/lib/imageEncode";

/** Lifecycle stages of one attachment:
 *
 * - ``encoding``  — posted to the Worker / read from disk; chip shows a spinner
 * - ``ready``     — ``dataUrl`` available; safe to submit
 * - ``error``     — validation / decode failure; chip shows inline error
 */
export type AttachmentStatus = "encoding" | "ready" | "error";
export type AttachmentKind = "image" | "file";

export interface AttachedAttachment {
  id: string;
  kind: AttachmentKind;
  file: File;
  /** Optimistic ``blob:`` preview URL; revoked on ``remove`` / ``clear`` /
   * unmount. */
  previewUrl?: string;
  status: AttachmentStatus;
  /** Populated when ``status === "ready"``. */
  dataUrl?: string;
  /** Size of the final encoded payload (base64 bytes decoded). */
  encodedBytes?: number;
  /** Whether the Worker re-encoded the image to hit the size budget. */
  normalized?: boolean;
  /** Human-readable validation / encoding error when ``status === "error"``. */
  error?: AttachmentError;
}

export type AttachedImage = AttachedAttachment;

export interface RestoredReadyAttachment {
  dataUrl: string;
  name?: string;
  kind?: AttachmentKind;
}

export type RestoredReadyImage = RestoredReadyAttachment;

/** Machine-readable rejection reasons surfaced as inline chip errors.
 *
 * Callers localize these via the ``composer.imageRejected.*`` i18n table. */
export type AttachmentError =
  | "unsupported_type"   // server whitelist excludes this MIME
  | "too_many_attachments" // per-message cap (4) reached before enqueue
  | "magic_mismatch"     // extension lies about the real content
  | "decode_failed"      // Worker couldn't decode / re-encode
  | "too_large"          // even after normalization we exceed the budget
  | "io";                // file read failed at the browser layer

export const MAX_ATTACHMENTS_PER_MESSAGE = 4;
export const MAX_IMAGES_PER_MESSAGE = MAX_ATTACHMENTS_PER_MESSAGE;
const MAX_FILE_BYTES = 6 * 1024 * 1024;

/** MIME whitelist — mirrors the server's and the ``<input accept>`` attr. */
const ACCEPTED_IMAGE_MIMES: ReadonlySet<string> = new Set([
  "image/png",
  "image/jpeg",
  "image/webp",
  "image/gif",
]);

const DOCUMENT_MIME_BY_EXTENSION: ReadonlyMap<string, string> = new Map([
  [".pdf", "application/pdf"],
  [".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
  [".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
  [".pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"],
  [".txt", "text/plain"],
  [".md", "text/markdown"],
  [".csv", "text/csv"],
  [".json", "application/json"],
  [".xml", "application/xml"],
  [".html", "text/html"],
  [".htm", "text/html"],
  [".log", "text/plain"],
  [".yaml", "application/yaml"],
  [".yml", "application/yaml"],
  [".toml", "application/toml"],
  [".ini", "text/plain"],
  [".cfg", "text/plain"],
]);

const ACCEPTED_DOCUMENT_MIMES: ReadonlySet<string> = new Set(DOCUMENT_MIME_BY_EXTENSION.values());

export const ACCEPT_ATTR = [
  ...ACCEPTED_IMAGE_MIMES,
  ...ACCEPTED_DOCUMENT_MIMES,
  ...DOCUMENT_MIME_BY_EXTENSION.keys(),
].join(",");

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot < 0 ? "" : name.slice(dot).toLowerCase();
}

function mimeForFile(file: File): string {
  const byName = DOCUMENT_MIME_BY_EXTENSION.get(extensionOf(file.name));
  if (!file.type || file.type === "application/octet-stream") {
    return byName || "application/octet-stream";
  }
  return file.type;
}

export function acceptedAttachmentKind(file: File): AttachmentKind | null {
  if (ACCEPTED_IMAGE_MIMES.has(file.type)) return "image";
  const mime = mimeForFile(file);
  if (ACCEPTED_DOCUMENT_MIMES.has(mime) || DOCUMENT_MIME_BY_EXTENSION.has(extensionOf(file.name))) {
    return "file";
  }
  return null;
}

function dataUrlMime(dataUrl: string): string {
  const match = /^data:([^;,]+)[;,]/.exec(dataUrl);
  return match?.[1] || "image/png";
}

function kindFromDataUrl(dataUrl: string): AttachmentKind {
  return dataUrlMime(dataUrl).startsWith("image/") ? "image" : "file";
}

function dataUrlToFile(dataUrl: string, name?: string): File {
  const mime = dataUrlMime(dataUrl);
  const fallbackName = `image.${mime.split("/")[1] || "png"}`;
  try {
    const [, base64 = ""] = dataUrl.split(",", 2);
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
      bytes[i] = binary.charCodeAt(i);
    }
    return new File([bytes], name || fallbackName, { type: mime });
  } catch {
    return new File([], name || fallbackName, { type: mime });
  }
}

function uuid(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return (crypto as Crypto).randomUUID();
  }
  return `img-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function bufferToBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode.apply(
      null,
      bytes.subarray(i, i + chunk) as unknown as number[],
    );
  }
  return btoa(binary);
}

async function encodeFile(file: File): Promise<{
  ok: true;
  dataUrl: string;
  bytes: number;
} | {
  ok: false;
  reason: AttachmentError;
}> {
  if (file.size > MAX_FILE_BYTES) return { ok: false, reason: "too_large" };
  try {
    const buffer = await file.arrayBuffer();
    return {
      ok: true,
      dataUrl: `data:${mimeForFile(file)};base64,${bufferToBase64(buffer)}`,
      bytes: file.size,
    };
  } catch {
    return { ok: false, reason: "io" };
  }
}

function mapEncodeFailure(reason: EncodeFailure["reason"]): AttachmentError {
  switch (reason) {
    case "invalid_mime":
    case "magic_mismatch":
      return "magic_mismatch";
    case "too_large_after_normalize":
      return "too_large";
    case "io":
      return "io";
    case "decode_failed":
    default:
      return "decode_failed";
  }
}

export interface UseAttachedImagesApi {
  images: AttachedAttachment[];
  /** Enqueue new files. Returns the list of rejected files so the caller can
   * surface inline errors. Files rejected client-side (wrong MIME, limit) are
   * *not* added to ``images`` — only recoverable read/encoding failures show
   * up as error chips. */
  enqueue: (files: Iterable<File>) => {
    rejected: Array<{ file: File; reason: AttachmentError }>;
  };
  remove: (id: string) => { nextFocusId: string | null };
  /** Revoke every staged blob URL and drop all attachments. Called after a
   * successful submit — the optimistic bubble holds onto an independent
   * ``data:`` URL so tearing down blob previews here is safe. */
  clear: () => void;
  /** Restore already-encoded attachments, e.g. a queued composer draft moving
   * back into the input. These entries are immediately sendable and use image
   * ``data:`` URLs as stable previews. */
  restoreReadyImages: (images: RestoredReadyAttachment[]) => void;
  /** ``true`` when at least one attachment is still encoding — Send should wait. */
  encoding: boolean;
  /** ``true`` when we've hit ``MAX_ATTACHMENTS_PER_MESSAGE``. */
  full: boolean;
}

/** Manage the lifecycle of attachments in the Composer.
 *
 * Responsibilities in one place:
 *   - validation (MIME whitelist, count cap)
 *   - blob URL creation + revocation
 *   - Worker orchestration
 *   - focus bookkeeping so keyboard delete doesn't strand the user
 */
export function useAttachedImages(): UseAttachedImagesApi {
  const [images, setImages] = useState<AttachedAttachment[]>([]);
  // Ref mirror so ``enqueue`` can see the authoritative length when invoked
  // multiple times in a single tick (rapid file selection, drag of many
  // files, paste storms). ``state`` is stale for that second + call.
  const imagesRef = useRef<AttachedAttachment[]>([]);
  imagesRef.current = images;

  const setEntry = useCallback((id: string, patch: Partial<AttachedAttachment>) => {
    setImages((prev) => {
      const next = prev.map((img) => (img.id === id ? { ...img, ...patch } : img));
      imagesRef.current = next;
      return next;
    });
  }, []);

  const enqueue = useCallback(
    (files: Iterable<File>) => {
      const rejected: Array<{ file: File; reason: AttachmentError }> = [];
      const toAdd: AttachedAttachment[] = [];
      let slot = MAX_ATTACHMENTS_PER_MESSAGE - imagesRef.current.length;

      for (const file of files) {
        const kind = acceptedAttachmentKind(file);
        if (!kind) {
          rejected.push({ file, reason: "unsupported_type" });
          continue;
        }
        if (slot <= 0) {
          rejected.push({ file, reason: "too_many_attachments" });
          continue;
        }
        slot -= 1;
        toAdd.push({
          id: uuid(),
          kind,
          file,
          ...(kind === "image" ? { previewUrl: URL.createObjectURL(file) } : {}),
          status: "encoding",
        });
      }

      if (toAdd.length > 0) {
        const next = [...imagesRef.current, ...toAdd];
        imagesRef.current = next;
        setImages(next);
        // Fire the Worker after the commit so chips render first (good INP).
        for (const entry of toAdd) {
          queueMicrotask(() => {
            const work = entry.kind === "image" ? encodeImage(entry.file) : encodeFile(entry.file);
            work.then(
              (result) => {
                if (result.ok) {
                  setEntry(entry.id, {
                    status: "ready",
                    dataUrl: result.dataUrl,
                    encodedBytes: result.bytes,
                    normalized: "normalized" in result ? result.normalized : false,
                  });
                } else {
                  setEntry(entry.id, {
                    status: "error",
                    error: entry.kind === "image"
                      ? mapEncodeFailure(result.reason as EncodeFailure["reason"])
                      : result.reason as AttachmentError,
                  });
                }
              },
              () => {
                setEntry(entry.id, {
                  status: "error",
                  error: "decode_failed",
                });
              },
            );
          });
        }
      }
      return { rejected };
    },
    [setEntry],
  );

  const remove = useCallback((id: string) => {
    let nextFocusId: string | null = null;
    setImages((prev) => {
      const idx = prev.findIndex((img) => img.id === id);
      if (idx === -1) return prev;
      const target = prev[idx];
      if (target.previewUrl) {
        try {
          URL.revokeObjectURL(target.previewUrl);
        } catch {
          // No-op: previewUrl revocation is best-effort.
        }
      }
      const next = [...prev.slice(0, idx), ...prev.slice(idx + 1)];
      imagesRef.current = next;
      // Prefer moving focus to the chip at the same index, else previous.
      const candidate = next[idx] ?? next[idx - 1];
      nextFocusId = candidate?.id ?? null;
      return next;
    });
    return { nextFocusId };
  }, []);

  const clear = useCallback(() => {
    setImages((prev) => {
      for (const img of prev) {
        if (img.previewUrl) {
          try {
            URL.revokeObjectURL(img.previewUrl);
          } catch {
            // revoke is best-effort
          }
        }
      }
      imagesRef.current = [];
      return [];
    });
  }, []);

  const restoreReadyImages = useCallback((restored: RestoredReadyAttachment[]) => {
    const toRestore = restored
      .filter((img) => acceptedAttachmentKind(dataUrlToFile(img.dataUrl, img.name)))
      .slice(0, MAX_ATTACHMENTS_PER_MESSAGE)
      .map((img): AttachedAttachment => {
        const file = dataUrlToFile(img.dataUrl, img.name);
        const kind = img.kind ?? kindFromDataUrl(img.dataUrl);
        return {
          id: uuid(),
          kind,
          file,
          ...(kind === "image" ? { previewUrl: img.dataUrl } : {}),
          status: "ready",
          dataUrl: img.dataUrl,
          encodedBytes: file.size,
        };
      });
    setImages((prev) => {
      for (const img of prev) {
        if (img.previewUrl) {
          try {
            URL.revokeObjectURL(img.previewUrl);
          } catch {
            // revoke is best-effort
          }
        }
      }
      imagesRef.current = toRestore;
      return toRestore;
    });
  }, []);

  // Final safety net: revoke any outstanding blob URLs on unmount. Safe
  // under StrictMode double-invoke because revoked blob URLs are only
  // referenced from in-hook chip state, which is rebuilt on remount.
  useEffect(() => {
    return () => {
      for (const img of imagesRef.current) {
        if (img.previewUrl) {
          try {
            URL.revokeObjectURL(img.previewUrl);
          } catch {
            // best-effort cleanup on unmount
          }
        }
      }
    };
  }, []);

  const encoding = images.some((img) => img.status === "encoding");
  const full = images.length >= MAX_ATTACHMENTS_PER_MESSAGE;

  return { images, enqueue, remove, clear, restoreReadyImages, encoding, full };
}
