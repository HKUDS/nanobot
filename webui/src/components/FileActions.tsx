import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Copy, Ellipsis, PanelRight } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { copyTextToClipboard } from "@/lib/clipboard";
import type { FileReferenceMetadata } from "@/lib/types";

interface FileActionsContextValue {
  resolveMetadata: (path: string) => Promise<FileReferenceMetadata>;
  openPreview: (path: string) => void;
}

const FileActionsContext = createContext<FileActionsContextValue | undefined>(undefined);

export const FileActionsProvider = FileActionsContext.Provider;

/** Shared by reply references, activity rows, and the preview header. */
export function FileActions({
  path, children, onPreview, metadata,
}: {
  path: string;
  children?: ReactNode;
  onPreview?: (path: string) => void;
  metadata?: FileReferenceMetadata;
}) {
  const context = useContext(FileActionsContext);
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [resolved, setResolved] = useState<FileReferenceMetadata | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [copyStatus, setCopyStatus] = useState<"copied" | "failed" | null>(null);
  const resolveMetadata = context?.resolveMetadata;

  useEffect(() => {
    let cancelled = false;
    setResolved(metadata ?? null);
    setLoadFailed(false);
    setCopyStatus(null);
    if (open && !metadata && resolveMetadata) {
      void resolveMetadata(path).then((value) => {
        if (typeof value.path !== "string" || !(value.relative_path === null || typeof value.relative_path === "string")) {
          throw new Error("File metadata is unavailable on this gateway");
        }
        if (!cancelled) setResolved(value);
      }).catch(() => { if (!cancelled) setLoadFailed(true); });
    }
    return () => { cancelled = true; };
  }, [open, path, metadata, resolveMetadata]);

  const enabled = Boolean(context || onPreview || metadata);

  const copy = async (value: string) => {
    const success = await copyTextToClipboard(value);
    setCopyStatus(success ? "copied" : "failed");
  };
  const preview = onPreview ? context?.openPreview ?? onPreview : undefined;

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <span
        className="not-prose inline-flex max-w-full items-baseline gap-0.5 align-baseline"
        onContextMenu={(event) => {
          if (!enabled) return;
          event.preventDefault();
          event.stopPropagation();
          setOpen(true);
        }}
        onKeyDown={(event) => {
          if (!enabled) return;
          if (event.key === "ContextMenu" || (event.key === "F10" && event.shiftKey)) {
            event.preventDefault();
            event.stopPropagation();
            setOpen(true);
          }
        }}
      >
        {children}
        {enabled ? <DropdownMenuTrigger asChild>
          <button
            type="button"
            aria-label={t("fileActions.menu", { name: path.split(/[\\/]/).pop() || path })}
            title={t("fileActions.title")}
            onClick={(event) => event.stopPropagation()}
            className="inline-flex h-6 w-6 shrink-0 items-center justify-center self-center rounded-md text-muted-foreground/65 transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Ellipsis className="h-3.5 w-3.5" aria-hidden />
          </button>
        </DropdownMenuTrigger> : null}
        {enabled ? <DropdownMenuContent align="end" collisionPadding={12} onClick={(event) => event.stopPropagation()}>
          {preview ? <>
            <DropdownMenuItem onSelect={() => preview(path)}>
              <PanelRight className="mr-2 h-4 w-4" aria-hidden />
              {t("fileActions.preview")}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
          </> : null}
          <DropdownMenuItem disabled={!resolved} onSelect={(event) => {
            event.preventDefault();
            if (resolved) void copy(resolved.path);
          }}>
            <Copy className="mr-2 h-4 w-4" aria-hidden />
            {t("fileActions.copyAbsolute")}
          </DropdownMenuItem>
          <DropdownMenuItem disabled={!resolved?.relative_path} onSelect={(event) => {
            event.preventDefault();
            if (resolved?.relative_path) void copy(resolved.relative_path);
          }}>
            <Copy className="mr-2 h-4 w-4" aria-hidden />
            {t("fileActions.copyRelative")}
          </DropdownMenuItem>
          {!resolved ? <DropdownMenuItem onSelect={(event) => {
            event.preventDefault();
            void copy(path);
          }}>{t("fileActions.copyReference")}</DropdownMenuItem> : null}
          <div role="status" className="max-w-64 px-2.5 py-1.5 text-xs text-muted-foreground">
            {copyStatus ? t(`fileActions.${copyStatus}`)
              : loadFailed ? t("fileActions.unavailable")
                : !resolved && resolveMetadata ? t("fileActions.loading")
                  : t("fileActions.gatewayPath")}
          </div>
        </DropdownMenuContent> : null}
      </span>
    </DropdownMenu>
  );
}
