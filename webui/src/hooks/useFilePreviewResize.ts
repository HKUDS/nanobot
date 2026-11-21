import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type RefObject } from "react";

const FILE_PREVIEW_MIN_WIDTH = 360;
const FILE_PREVIEW_MAX_WIDTH = 860;
const FILE_PREVIEW_MIN_MAIN_WIDTH = 420;

function clampFilePreviewWidth(width: number, maxWidth: number): number {
  return Math.min(Math.max(width, FILE_PREVIEW_MIN_WIDTH), maxWidth);
}

function maxFilePreviewWidth(containerWidth: number): number {
  return Math.min(
    containerWidth > 0 ? containerWidth : FILE_PREVIEW_MIN_WIDTH,
    Math.max(
      FILE_PREVIEW_MIN_WIDTH,
      Math.min(FILE_PREVIEW_MAX_WIDTH, containerWidth - FILE_PREVIEW_MIN_MAIN_WIDTH),
    ),
  );
}

/** Owns the transient drag, panel geometry and restoration of drag-time styles. */
export function useFilePreviewResize(
  shellRef: RefObject<HTMLElement>, previewOpen: boolean, storedWidth: number, setFilePreviewWidth: (width: number) => void,
) {
  const panelRef = useRef<HTMLElement>(null);
  const [filePreviewMaxWidth, setFilePreviewMaxWidth] = useState(FILE_PREVIEW_MAX_WIDTH);
  const filePreviewWidth = clampFilePreviewWidth(storedWidth, filePreviewMaxWidth);
  const filePreviewWidthRef = useRef(filePreviewWidth);
  const filePreviewResizeCleanupRef = useRef<(() => void) | null>(null);
  const cancelResize = useCallback(() => filePreviewResizeCleanupRef.current?.(), []);
  useEffect(() => cancelResize, [cancelResize]);

  useEffect(() => {
    filePreviewWidthRef.current = filePreviewWidth;
  }, [filePreviewWidth]);

  const handleFilePreviewResizeStart = useCallback((event: ReactPointerEvent<HTMLButtonElement>) => {
    filePreviewResizeCleanupRef.current?.();
    event.preventDefault();
    event.stopPropagation();
    const panel = panelRef.current;
    const shellRect = shellRef.current?.getBoundingClientRect();
    const rightEdge = shellRect?.right ?? window.innerWidth;
    const maxWidth = maxFilePreviewWidth(shellRect?.width ?? window.innerWidth);
    const originalBodyCursor = document.body.style.cursor;
    const originalBodyUserSelect = document.body.style.userSelect;
    const originalPanelTransition = panel?.style.transition ?? "";
    const frameElement = panel?.querySelector("iframe");
    const originalFramePointerEvents = frameElement?.style.pointerEvents ?? "";
    let nextWidth = filePreviewWidthRef.current;
    let frame: number | null = null;

    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    if (panel) panel.style.transition = "none";
    if (frameElement) frameElement.style.pointerEvents = "none";

    const applyWidth = (clientX: number) => {
      nextWidth = clampFilePreviewWidth(rightEdge - clientX, maxWidth);
      filePreviewWidthRef.current = nextWidth;
      if (frame !== null) return;
      frame = window.requestAnimationFrame(() => {
        frame = null;
        panel?.style.setProperty("--file-preview-width", `${nextWidth}px`);
        panel?.style.setProperty("--file-preview-slot-width", `${nextWidth}px`);
      });
    };
    const handlePointerMove = (moveEvent: PointerEvent) => {
      moveEvent.preventDefault();
      applyWidth(moveEvent.clientX);
    };
    const stopResize = (commit: boolean) => {
      if (frame !== null) {
        window.cancelAnimationFrame(frame);
        frame = null;
      }
      panel?.style.setProperty("--file-preview-width", `${nextWidth}px`);
      panel?.style.setProperty("--file-preview-slot-width", `${nextWidth}px`);
      if (panel) panel.style.transition = originalPanelTransition;
      if (frameElement) frameElement.style.pointerEvents = originalFramePointerEvents;
      if (commit) setFilePreviewWidth(nextWidth);
      document.body.style.cursor = originalBodyCursor;
      document.body.style.userSelect = originalBodyUserSelect;
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
      window.removeEventListener("pointercancel", handlePointerUp);
      filePreviewResizeCleanupRef.current = null;
    };
    const handlePointerUp = () => stopResize(true);
    filePreviewResizeCleanupRef.current = () => stopResize(false);

    applyWidth(event.clientX);
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
    window.addEventListener("pointercancel", handlePointerUp);
  }, [setFilePreviewWidth, shellRef]);

  useEffect(() => {
    if (!previewOpen) return;
    const clampToShell = () => {
      const shellWidth = shellRef.current?.getBoundingClientRect().width ?? window.innerWidth;
      const maxWidth = maxFilePreviewWidth(shellWidth);
      setFilePreviewMaxWidth(maxWidth);
    };
    clampToShell();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(clampToShell);
    if (shellRef.current) observer?.observe(shellRef.current);
    window.addEventListener("resize", clampToShell);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", clampToShell);
    };
  }, [previewOpen, shellRef]);

  return { width: filePreviewWidth, panelRef, startResize: handleFilePreviewResizeStart, cancelResize };
}
