import { useTranslation } from "react-i18next";
import { AlertCircle } from "lucide-react";

import { CodeBlock } from "@/components/CodeBlock";
import { ImageLightbox } from "@/components/ImageLightbox";
import { fileKindForPath, splitFilePath } from "@/components/FileReferenceChip";
import type { FilePreviewPayload } from "@/lib/types";

export type FilePreviewPanelState =
  | { status: "loading" }
  | { status: "error"; message?: string; routeMissing?: boolean }
  | { status: "ready"; payload: FilePreviewPayload };

export function FilePreviewPanelView({ path, state, imageOpen, onImageOpenChange, onImageError }: {
  path: string;
  state: FilePreviewPanelState;
  imageOpen: boolean;
  onImageOpenChange: (open: boolean) => void;
  onImageError: () => void;
}) {
  const { t } = useTranslation();
  const displayPath = state.status === "ready" ? state.payload.display_path : path;
  const { name } = splitFilePath(displayPath);
  const fileName = name || displayPath;
  const errorMessage = state.status === "error"
    ? (state.routeMissing
      ? t("filePreview.routeMissing", {
          defaultValue: "File preview needs the latest gateway. Restart nanobot gateway and try again.",
        })
      : state.message ?? t("filePreview.failed", { defaultValue: "Could not preview this file." }))
    : null;

  return (
    <section aria-label={t("filePreview.aria")} data-testid="file-preview-panel" className="flex min-h-0 flex-1 flex-col">
          <div data-file-preview-scroll tabIndex={0}
            className="min-h-0 flex-1 overflow-auto focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/60">
            {state.status === "loading" ? (
              <div role="status" aria-label={t("filePreview.loading", { defaultValue: "Loading preview..." })}
                className="flex h-full flex-col justify-center gap-3 p-6" aria-busy="true">
                <span className="sr-only">{t("filePreview.loading", { defaultValue: "Loading preview..." })}</span>
                <div aria-hidden className="mx-auto w-full max-w-sm space-y-3 animate-pulse [animation-duration:900ms] motion-reduce:animate-none">
                  {fileKindForPath(path) === "image" ? <div className="aspect-[8/5] rounded-compact bg-muted/40" />
                    : <>{["w-2/3", "w-full", "w-5/6", "w-3/4"].map((width) =>
                      <div key={width} className={`h-1.5 rounded-full bg-muted/40 ${width}`} />)}</>}
                </div>
              </div>
            ) : state.status === "error" ? (
              <div className="flex h-full items-center justify-center px-8 text-center text-sm text-muted-foreground">
                <div className="max-w-sm">
                  <AlertCircle
                    className="mx-auto mb-3 h-5 w-5 text-muted-foreground/70"
                    aria-hidden
                  />
                  <p>{errorMessage}</p>
                </div>
              </div>
            ) : state.payload.kind === "image" ? (
              <div className="flex min-h-full items-center justify-center p-4">
                <button type="button" aria-label={`${t("lightbox.open")}: ${fileName}`} onClick={() => onImageOpenChange(true)}
                  className="flex max-h-full max-w-full cursor-zoom-in items-center justify-center rounded-compact focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                  <img
                  src={state.payload.data_url}
                  alt={fileName}
                  className="max-h-full max-w-full object-contain"
                  onError={onImageError}
                  />
                </button>
                <ImageLightbox images={[{ url: state.payload.data_url, name: fileName }]} index={imageOpen ? 0 : null}
                  onIndexChange={() => {}} onOpenChange={onImageOpenChange} />
              </div>
            ) : (
              <div className="min-h-full">
                {state.payload.truncated ? (
                  <div className="mx-4 mt-3 rounded-md border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-200">
                    {t("filePreview.truncated", {
                      defaultValue: "Preview is truncated because this file is large.",
                    })}
                  </div>
                ) : null}
                <CodeBlock
                  language={state.payload.language}
                  code={state.payload.content}
                  chrome="none"
                  highlight
                  showLineNumbers
                  wrapLongLines={false}
                  viewportHighlight
                  className="min-h-full"
                />
              </div>
            )}
          </div>
    </section>
  );
}
