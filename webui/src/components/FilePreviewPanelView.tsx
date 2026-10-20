import { useState } from "react";
import { useTranslation } from "react-i18next";
import { AlertCircle } from "lucide-react";

import { CodeBlock } from "@/components/CodeBlock";
import { MarkdownText } from "@/components/MarkdownText";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { ImageLightbox } from "@/components/ImageLightbox";
import { fileKindForPath, splitFilePath } from "@/components/FileReferenceChip";
import type { FilePreviewPayload } from "@/lib/types";

export type FilePreviewPanelState =
  | { status: "loading" }
  | { status: "error"; message?: string; routeMissing?: boolean }
  | { status: "ready"; payload: FilePreviewPayload };

export function FilePreviewPanelView({ path, state, imageOpen, onImageOpenChange, onImageError, onOpenFilePreview }: {
  path: string;
  state: FilePreviewPanelState;
  imageOpen: boolean;
  onImageOpenChange: (open: boolean) => void;
  onImageError: () => void;
  onOpenFilePreview?: (path: string) => void;
}) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<"preview" | "source">("preview");
  const previewKind = fileKindForPath(path);
  const markdown = state.status === "ready" && state.payload.kind !== "image"
    && state.payload.language === "markdown";
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
          {markdown ? (
            <div className="flex shrink-0 items-center justify-end px-4 py-2">
              <SegmentedControl value={mode} onChange={setMode} ariaLabel={t("filePreview.displayMode")}
                options={[{ value: "preview", label: t("filePreview.preview") }, { value: "source", label: t("filePreview.source") }]}
                itemClassName="px-3 [@media(pointer:coarse)]:min-h-9" />
            </div>
          ) : null}
          <div key={mode} data-file-preview-scroll tabIndex={0}
            className="min-h-0 flex-1 overflow-auto focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/60">
            {state.status === "loading" ? (
              <div role="status" aria-label={t("filePreview.loading", { defaultValue: "Loading preview..." })}
                className="h-full" aria-busy="true">
                <span className="sr-only">{t("filePreview.loading", { defaultValue: "Loading preview..." })}</span>
                <div aria-hidden className="h-full animate-pulse [animation-duration:900ms] motion-reduce:animate-none">
                  {previewKind === "image" ? <div className="flex h-full items-center justify-center p-4">
                    <div className="aspect-[8/5] w-full max-w-sm rounded-compact bg-muted/40" />
                  </div> : <>
                    {previewKind === "markdown" ? <div className="flex justify-end px-4 py-2">
                      <div className="inline-flex min-h-8 items-center gap-1 rounded-full bg-muted/40 p-1 text-ui-label">
                        {[t("filePreview.preview"), t("filePreview.source")].map((label) => <span key={label} className="invisible px-3 py-1 [@media(pointer:coarse)]:min-h-9">{label}</span>)}
                      </div>
                    </div> : null}
                    {previewKind === "markdown" && mode === "preview" ? <div className="markdown-content px-5 pb-6 pt-1 sm:px-6">
                      <h1 data-file-preview-heading-skeleton className="flex h-[1lh] items-center"><div className="h-[0.75em] w-2/3 rounded bg-muted/40" /></h1>
                      {["w-full", "w-5/6", "w-3/4"].map((width) => <div key={width} className="mt-4 flex h-[1lh] items-center">
                        <div className={`h-3 rounded bg-muted/40 ${width}`} />
                      </div>)}
                    </div> : <div className="px-4 py-3 font-mono text-code">
                      {["w-2/3", "w-full", "w-5/6", "w-3/4", "w-1/2", "w-3/5"].map((width) => <div key={width} className="flex h-[1lh] items-center">
                        <div className="w-[4.25em] shrink-0 pr-[1.15rem]"><div className="ml-auto h-3 w-2 rounded bg-muted/40" /></div>
                        <div className={`h-3 max-w-[calc(100%-4.25em)] rounded bg-muted/40 ${width}`} />
                      </div>)}
                    </div>}
                  </>}
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
                {markdown && mode === "preview" ? (
                  <MarkdownText documentPath={state.payload.path} onOpenFilePreview={onOpenFilePreview}
                    className="px-5 pb-6 pt-1 [overflow-wrap:anywhere] sm:px-6 [&>:first-child]:mt-0">
                    {state.payload.content}
                  </MarkdownText>
                ) : <CodeBlock
                  language={state.payload.language}
                  code={state.payload.content}
                  chrome="none"
                  highlight
                  showLineNumbers
                  wrapLongLines={false}
                  viewportHighlight
                  className="min-h-full"
                />}
              </div>
            )}
          </div>
    </section>
  );
}
