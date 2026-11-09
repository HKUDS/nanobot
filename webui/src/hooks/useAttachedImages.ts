import { useCallback, useEffect, useRef, useState } from "react";
import type { LocalAttachment } from "../../../packages/client-events/attachments";

import { encodeImage, type EncodeFailure } from "@/lib/imageEncode";
import type { WebUIIngressLimits } from "@/lib/types";

type AttachmentStatus = "encoding" | "ready" | "error";
export type AttachmentKind = "image" | "video" | "file";

interface AttachedAttachment {
  id: string;
  kind: AttachmentKind;
  file: Pick<File, "name" | "size" | "type">;
  local?: LocalAttachment;
  /** Preview URL; owned ``blob:`` URLs are revoked on removal, clearing or unmount. */
  previewUrl?: string;
  status: AttachmentStatus;
  /** Encoded payload; ready local attachments use ``local`` instead. */
  dataUrl?: string;
  /** Size of the final encoded payload (base64 bytes decoded). */
  encodedBytes?: number;
  /** Whether image bytes were re-encoded to meet the size budget. */
  normalized?: boolean;
  /** Machine-readable error code for callers to localize when ``status === "error"``. */
  error?: AttachmentError;
}

export type AttachedImage = AttachedAttachment;

export interface RestoredReadyAttachment {
  dataUrl?: string;
  local?: LocalAttachment;
  name?: string;
  kind?: AttachmentKind;
}

export type RestoredReadyImage = RestoredReadyAttachment;

/** Machine-readable rejection reasons surfaced as inline chip errors.
 *
 * Callers localize these via the ``composer.imageRejected.*`` i18n table. */
export type AttachmentError =
  | "too_many_attachments" // non-video per-message cap reached before enqueue
  | "too_many_videos"      // video slot is already occupied
  | "total_too_large"    // decoded attachments exceed the business-policy total
  | "decode_failed"      // Worker couldn't decode / re-encode
  | "too_large"          // even after normalization we exceed the budget
  | "io";                // file read failed at the browser layer

type AttachmentCountError = Extract<AttachmentError, "too_many_attachments" | "too_many_videos">;

export const MAX_ATTACHMENTS_PER_MESSAGE = 4;
export const MAX_ATTACHMENT_BYTES = 6 * 1024 * 1024;
export const MAX_TOTAL_ATTACHMENT_BYTES = 24 * 1024 * 1024;
export const MAX_VIDEO_BYTES = 20 * 1024 * 1024;
export const MAX_VIDEOS_PER_MESSAGE = 1;
const VIDEO_MIME_BY_EXTENSION = new Map([
  [".mp4", "video/mp4"], [".webm", "video/webm"], [".mov", "video/quicktime"],
]);

/** Formats handled by the image encoder rather than the generic file path. */
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

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot < 0 ? "" : name.slice(dot).toLowerCase();
}

function mimeForFile(file: File): string {
  if (file.size === 0) return "application/octet-stream";
  const byName = DOCUMENT_MIME_BY_EXTENSION.get(extensionOf(file.name))
    ?? VIDEO_MIME_BY_EXTENSION.get(extensionOf(file.name));
  if (byName) return byName;
  if (ACCEPTED_DOCUMENT_MIMES.has(file.type)
    || [...VIDEO_MIME_BY_EXTENSION.values()].includes(file.type)) return file.type;
  return "application/octet-stream";
}

function positiveLimit(value: number | null | undefined, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? Math.floor(value)
    : fallback;
}

export function attachmentKindForFile(file: File): AttachmentKind {
  if (file.size === 0) return "file";
  if (VIDEO_MIME_BY_EXTENSION.has(extensionOf(file.name))) return "video";
  if (DOCUMENT_MIME_BY_EXTENSION.has(extensionOf(file.name))) return "file";
  if ([...VIDEO_MIME_BY_EXTENSION.values()].includes(file.type)) return "video";
  return ACCEPTED_IMAGE_MIMES.has(file.type) ? "image" : "file";
}

function dataUrlMime(dataUrl: string): string {
  const match = /^data:([^;,]+)[;,]/.exec(dataUrl);
  return match?.[1] || "image/png";
}

function kindFromDataUrl(dataUrl: string): AttachmentKind {
  const mime = dataUrlMime(dataUrl);
  return mime.startsWith("image/") ? "image" : mime.startsWith("video/") ? "video" : "file";
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

async function encodeFile(file: File, maxFileBytes: number, mime = mimeForFile(file)): Promise<{
  ok: true;
  dataUrl: string;
  bytes: number;
} | {
  ok: false;
  reason: AttachmentError;
}> {
  if (file.size > maxFileBytes) return { ok: false, reason: "too_large" };
  try {
    const buffer = await file.arrayBuffer();
    return {
      ok: true,
      dataUrl: `data:${mime};base64,${bufferToBase64(buffer)}`,
      bytes: file.size,
    };
  } catch {
    return { ok: false, reason: "io" };
  }
}

function mapEncodeFailure(reason: Exclude<EncodeFailure["reason"], "invalid_mime" | "magic_mismatch">): AttachmentError {
  switch (reason) {
    case "too_large_after_normalize":
      return "too_large";
    case "io":
      return "io";
    case "decode_failed":
    default:
      return "decode_failed";
  }
}

async function encodeAttachment(file: File, kind: AttachmentKind, maxFileBytes: number): Promise<{
  ok: true;
  kind: AttachmentKind;
  dataUrl: string;
  bytes: number;
  normalized: boolean;
} | {
  ok: false;
  reason: AttachmentError;
}> {
  if (kind === "image") {
    const result = await encodeImage(file);
    if (result.ok) return { ...result, kind };
    if (result.reason !== "magic_mismatch" && result.reason !== "invalid_mime") {
      return { ok: false, reason: mapEncodeFailure(result.reason) };
    }
    // A non-image claiming an image MIME is still a file; keep its original bytes.
    kind = "file";
    const fallback = await encodeFile(file, maxFileBytes, "application/octet-stream");
    return fallback.ok ? { ...fallback, kind, normalized: false } : fallback;
  }
  const result = await encodeFile(file, kind === "video" ? MAX_VIDEO_BYTES : maxFileBytes);
  return result.ok ? { ...result, kind, normalized: false } : result;
}

export interface UseAttachedImagesApi {
  images: AttachedAttachment[];
  /** Enqueue new files. Returns the list of rejected files so the caller can
   * surface inline errors. Files rejected for limits are *not* added to
   * ``images`` — only recoverable read/encoding failures show
   * up as error chips. Restoring an existing draft preserves overflow so users
   * can remove files themselves; send validation still enforces ingress limits. */
  enqueue: (files: Iterable<File>, options?: { restoringDraft: boolean }) => {
    rejected: Array<{ file: File; reason: AttachmentError }>;
  };
  addLocal: (attachment: LocalAttachment, options?: { restoringDraft: boolean }) => AttachmentCountError | null;
  remove: (id: string) => { nextFocusId: string | null };
  /** Revoke owned blob previews and clear staged entries; submitted attachments
   * retain independent data URLs or local references. */
  clear: () => void;
  /** Restore ready encoded payloads or local references, preserving draft overflow
   * for the user to resolve before sending. */
  restoreReadyImages: (images: RestoredReadyAttachment[]) => void;
  /** ``true`` when at least one attachment is still encoding — Send should wait. */
  encoding: boolean;
  /** ``true`` when both the non-video and video attachment quotas are full. */
  full: boolean;
}

interface UseAttachedImagesOptions {
  ingressLimits?: WebUIIngressLimits | null;
}

export function useAttachedImages({
  ingressLimits = null,
}: UseAttachedImagesOptions = {}): UseAttachedImagesApi {
  const [images, setImages] = useState<AttachedAttachment[]>([]);
  const maxAttachments = positiveLimit(
    ingressLimits?.attachments.max_count,
    MAX_ATTACHMENTS_PER_MESSAGE,
  );
  const maxFileBytes = positiveLimit(
    ingressLimits?.attachments.max_file_bytes,
    MAX_ATTACHMENT_BYTES,
  );
  const maxTotalBytes = positiveLimit(
    ingressLimits?.attachments.max_total_bytes,
    MAX_TOTAL_ATTACHMENT_BYTES,
  );
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
    (files: Iterable<File>, { restoringDraft = false } = {}) => {
      const rejected: Array<{ file: File; reason: AttachmentError }> = [];
      const toAdd: Array<AttachedAttachment & { file: File }> = [];
      let slot = maxAttachments - imagesRef.current.filter((item) => item.kind !== "video").length;
      let videoSlot = MAX_VIDEOS_PER_MESSAGE - imagesRef.current.filter((item) => item.kind === "video").length;
      let projectedDecodedBytes = imagesRef.current.reduce(
        (total, image) => total + (image.local || image.kind === "video" ? 0 : (
          image.encodedBytes
          ?? (image.kind === "image" ? Math.min(image.file.size, maxFileBytes) : image.file.size)
        )),
        0,
      );

      for (const file of files) {
        const kind = attachmentKindForFile(file);
        if (!restoringDraft && kind !== "image" && file.size > (kind === "video" ? MAX_VIDEO_BYTES : maxFileBytes)) {
          rejected.push({ file, reason: "too_large" });
          continue;
        }
        if (!restoringDraft && (kind === "video" ? videoSlot : slot) <= 0) {
          rejected.push({ file, reason: kind === "video" ? "too_many_videos" : "too_many_attachments" });
          continue;
        }
        const nextDecodedBytes = kind === "video" ? 0 : kind === "image" ? Math.min(file.size, maxFileBytes) : file.size;
        if (!restoringDraft && projectedDecodedBytes + nextDecodedBytes > maxTotalBytes) {
          rejected.push({ file, reason: "total_too_large" });
          continue;
        }
        if (kind === "video") videoSlot -= 1;
        else slot -= 1;
        projectedDecodedBytes += nextDecodedBytes;
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
            encodeAttachment(entry.file, entry.kind, maxFileBytes).then(
              (result) => {
                if (result.ok) {
                  if (entry.kind === "image" && result.kind === "file" && entry.previewUrl) {
                    try {
                      URL.revokeObjectURL(entry.previewUrl);
                    } catch {
                      // Preview revocation is best-effort, as on removal.
                    }
                  }
                  setEntry(entry.id, {
                    kind: result.kind,
                    ...(result.kind === "file" ? { previewUrl: undefined } : {}),
                    status: "ready",
                    dataUrl: result.dataUrl,
                    encodedBytes: result.bytes,
                    normalized: result.normalized,
                  });
                } else {
                  setEntry(entry.id, { status: "error", error: result.reason });
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
    [maxAttachments, maxFileBytes, maxTotalBytes, setEntry],
  );

  const addLocal = useCallback((local: LocalAttachment, { restoringDraft = false } = {}): AttachmentCountError | null => {
    const current = imagesRef.current;
    const videos = current.filter((item) => item.kind === "video").length;
    if (!restoringDraft && (local.kind === "video" ? videos >= MAX_VIDEOS_PER_MESSAGE : current.length - videos >= maxAttachments)) {
      return local.kind === "video" ? "too_many_videos" : "too_many_attachments";
    }
    const next: AttachedAttachment[] = [...current, {
      id: uuid(), kind: local.kind, local, status: "ready", encodedBytes: local.size,
      file: { name: local.name, size: local.size, type: local.mime },
      ...(local.kind === "image" ? { previewUrl: local.url } : {}),
    }];
    imagesRef.current = next;
    setImages(next);
    return null;
  }, [maxAttachments]);

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
    const toRestore = restored.flatMap((img): AttachedAttachment[] => {
      if (img.local) {
        const local = img.local;
        return [{
          id: uuid(), kind: local.kind, local, status: "ready", encodedBytes: local.size,
          file: { name: local.name, size: local.size, type: local.mime },
          ...(local.kind === "image" ? { previewUrl: local.url } : {}),
        }];
      }
      if (!img.dataUrl) return [];
      const file = dataUrlToFile(img.dataUrl, img.name);
      const kind = img.kind ?? kindFromDataUrl(img.dataUrl);
      return [{
        id: uuid(), kind, file, status: "ready", dataUrl: img.dataUrl, encodedBytes: file.size,
        ...(kind === "image" ? { previewUrl: img.dataUrl } : {}),
      }];
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
  const videos = images.filter((image) => image.kind === "video").length;
  const full = images.length - videos >= maxAttachments && videos >= MAX_VIDEOS_PER_MESSAGE;

  return { images, enqueue, addLocal, remove, clear, restoreReadyImages, encoding, full };
}
