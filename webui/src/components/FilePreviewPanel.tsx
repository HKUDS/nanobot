import { useCallback, useEffect, useRef, useState } from "react";
import { FilePreviewPanelView, type FilePreviewPanelState } from "@/components/FilePreviewPanelView";
import { ApiError, fetchFilePreview } from "@/lib/api";
import type { FilePreviewPayload } from "@/lib/types";

interface FilePreviewPanelProps {
  sessionKey: string;
  path: string;
  token: string;
  loadPreview?: (path: string) => Promise<FilePreviewPayload>;
  initialPreview?: FilePreviewPayload;
}

export function FilePreviewPanel({
  sessionKey,
  path,
  token,
  loadPreview,
  initialPreview,
}: FilePreviewPanelProps) {
  const [state, setState] = useState<FilePreviewPanelState>(() => initialPreview
    ? { status: "ready", payload: initialPreview } : { status: "loading" });
  const [imageOpen, setImageOpen] = useState(false);
  // Cache aging must not restart an already open preview on unrelated rerenders.
  const initialPreviewRef = useRef(initialPreview);
  initialPreviewRef.current = initialPreview;
  // Credential renewal is not a new file selection. Read the current token only
  // when a session/path/loader change actually starts another request.
  const tokenRef = useRef(token);
  tokenRef.current = token;

  useEffect(() => {
    let cancelled = false;
    setImageOpen(false);
    const cached = initialPreviewRef.current;
    setState(previous => cached
      ? (previous.status === "ready" && previous.payload === cached ? previous : { status: "ready", payload: cached })
      : (previous.status === "loading" ? previous : { status: "loading" }));
    (loadPreview?.(path) ?? fetchFilePreview(tokenRef.current, sessionKey, path))
      .then((payload) => {
        if (!cancelled) setState(previous => previous.status === "ready" && previous.payload === payload
          ? previous : { status: "ready", payload });
      })
      .catch((error: unknown) => {
        if (!cancelled) setState({ status: "error",
          ...(error instanceof ApiError ? {
            message: error.message,
            routeMissing: error.status === 404 && /API route not found/i.test(error.message),
          } : {}),
        });
      });
    return () => {
      cancelled = true;
    };
  }, [path, sessionKey, loadPreview]);

  const reportImageError = useCallback(() => setState({ status: "error" }), []);
  return <FilePreviewPanelView path={path} state={state} imageOpen={imageOpen}
    onImageOpenChange={setImageOpen} onImageError={reportImageError} />;
}
