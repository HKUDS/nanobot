import { useCallback, useRef, useState } from "react";

/** Extract image ``File``s from a paste / drop event.
 *
 * Deliberate behaviour:
 *   - Only items whose ``kind === "file"`` and ``type`` starts with
 *     ``image/`` are returned; ``<img>`` tags inside HTML fragments are
 *     ignored (defending against remote URL fetch + XSS surfaces).
 *   - Plain text pasted alongside images is *not* consumed by this helper,
 *     so the caller can still let the textarea receive it naturally.
 */
export function extractImageFilesFromPaste(
  event: ClipboardEvent | React.ClipboardEvent,
): File[] {
  const clipboard = (event as ClipboardEvent).clipboardData
    ?? (event as React.ClipboardEvent).clipboardData;
  if (!clipboard) return [];
  const files: File[] = [];
  for (const item of Array.from(clipboard.items)) {
    if (item.kind !== "file") continue;
    if (!item.type.startsWith("image/")) continue;
    const file = item.getAsFile();
    if (file) files.push(file);
  }
  return files;
}

/** Extract dropped image files, mirroring ``extractImageFilesFromPaste``. */
export function extractImageFilesFromDrop(
  event: DragEvent | React.DragEvent,
): File[] {
  const dt = (event as DragEvent).dataTransfer
    ?? (event as React.DragEvent).dataTransfer;
  if (!dt) return [];
  const files: File[] = [];
  for (const item of Array.from(dt.files)) {
    if (item.type.startsWith("image/")) files.push(item);
  }
  return files;
}

export interface UseClipboardAndDropApi {
  /** Whether a drag is currently hovering the drop zone (toggle dragover UI). */
  isDragging: boolean;
  onPaste: (
    event: React.ClipboardEvent,
  ) => void;
  onDragEnter: (event: React.DragEvent) => void;
  onDragOver: (event: React.DragEvent) => void;
  onDragLeave: (event: React.DragEvent) => void;
  onDrop: (event: React.DragEvent) => void;
}

/** Wire paste + drag-and-drop to a callback.
 *
 * The hook owns ``isDragging`` state and the refcount that keeps it accurate
 * across nested ``dragenter`` / ``dragleave`` events (a known DOM gotcha: the
 * text cursor inside a textarea fires ``dragleave`` on entry, flicking the
 * highlight off otherwise). */
export function useClipboardAndDrop(
  onImageFiles: (files: File[]) => void,
): UseClipboardAndDropApi {
  const [isDragging, setIsDragging] = useState(false);
  const dragDepth = useRef(0);

  const onPaste = useCallback(
    (event: React.ClipboardEvent) => {
      const files = extractImageFilesFromPaste(event);
      if (files.length === 0) return;
      // Consume only when an image is actually present; plain-text paste still
      // reaches the textarea unmolested.
      event.preventDefault();
      onImageFiles(files);
    },
    [onImageFiles],
  );

  const onDragEnter = useCallback((event: React.DragEvent) => {
    if (!Array.from(event.dataTransfer.types ?? []).includes("Files")) return;
    event.preventDefault();
    dragDepth.current += 1;
    setIsDragging(true);
  }, []);

  const onDragOver = useCallback((event: React.DragEvent) => {
    if (!Array.from(event.dataTransfer.types ?? []).includes("Files")) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  }, []);

  const onDragLeave = useCallback((event: React.DragEvent) => {
    if (!Array.from(event.dataTransfer.types ?? []).includes("Files")) return;
    event.preventDefault();
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setIsDragging(false);
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      dragDepth.current = 0;
      setIsDragging(false);
      const files = extractImageFilesFromDrop(event);
      if (files.length === 0) return;
      event.preventDefault();
      onImageFiles(files);
    },
    [onImageFiles],
  );

  return { isDragging, onPaste, onDragEnter, onDragOver, onDragLeave, onDrop };
}
