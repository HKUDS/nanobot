import { useState, type CSSProperties, type PointerEvent } from "react";
import { ExternalLink, RotateCw, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { isLoopbackHost } from "@/lib/network";
import { isNativeRuntime } from "@/lib/runtime";
import { parseWebLink, webPreviewRestriction } from "@/lib/web-preview";

interface WebPreviewPanelProps {
  url: string;
  desktopWidth?: number;
  onResizeStart?: (event: PointerEvent<HTMLButtonElement>) => void;
  onClose: () => void;
}

export function WebPreviewPanel({ url: value, desktopWidth = 544, onResizeStart, onClose }: WebPreviewPanelProps) {
  const { t } = useTranslation();
  const [revision, setRevision] = useState(0);
  const url = parseWebLink(value);
  const restriction = url ? webPreviewRestriction(url, new URL(window.location.href), isNativeRuntime(),
    "credentialless" in HTMLIFrameElement.prototype) : "invalid";
  const buttonClass = "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
  return (
    <aside aria-label={t("webPreview.title")} data-testid="web-preview-panel" data-file-preview-panel
      style={{ "--file-preview-width": `${desktopWidth}px`, "--file-preview-slot-width": `${desktopWidth}px` } as CSSProperties}
      className="absolute inset-y-0 right-0 z-30 flex w-full flex-col border-l border-border/70 bg-background pb-[env(safe-area-inset-bottom)] shadow-2xl md:relative md:z-auto md:w-[var(--file-preview-slot-width)] md:min-w-0 md:shrink-0 md:pb-0 md:shadow-none">
      {onResizeStart ? <button type="button" aria-label={t("webPreview.resize")}
        className="absolute inset-y-0 left-0 z-20 hidden w-2 cursor-col-resize touch-none hover:bg-border/50 md:block"
        onPointerDown={onResizeStart} /> : null}
      <div className="flex shrink-0 items-center gap-1 border-b border-border/60 px-3 py-2">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium" title={url?.origin}>{t("webPreview.original")}</p>
          <p className="truncate text-xs text-muted-foreground" title={url?.href}>{url?.href}</p>
        </div>
        {!restriction ? <button type="button" className={buttonClass} onClick={() => setRevision((n) => n + 1)} title={t("webPreview.refresh")} aria-label={t("webPreview.refresh")}>
          <RotateCw className="h-4 w-4" aria-hidden />
        </button> : null}
        {url ? <a className={buttonClass} href={url.href} target="_blank" rel="noreferrer noopener" title={t("webPreview.external")} aria-label={t("webPreview.external")}>
          <ExternalLink className="h-4 w-4" aria-hidden />
        </a> : null}
        <button type="button" className={buttonClass} onClick={onClose} title={t("webPreview.close")} aria-label={t("webPreview.close")}><X className="h-4 w-4" aria-hidden /></button>
      </div>
      <div className="shrink-0 space-y-1 border-b border-border/60 px-4 py-3 text-xs leading-relaxed text-muted-foreground">
        <p>{t("webPreview.isolated")}</p>
        <p>{t("webPreview.blockedHint")}</p>
        {url && isLoopbackHost(url.hostname) ? <p>{t("webPreview.loopback")}</p> : null}
      </div>
      {restriction ? <div role="status" className="flex min-h-0 flex-1 items-center justify-center overflow-auto p-6 text-center text-sm text-muted-foreground">
        {t(`webPreview.${restriction}`)}
      </div> : <iframe key={`${value}:${revision}`} title={t("webPreview.frame", { host: url!.host })}
        {...{ credentialless: "" }} sandbox="allow-scripts" referrerPolicy="no-referrer"
        allow="camera 'none'; microphone 'none'; geolocation 'none'; clipboard-read 'none'; clipboard-write 'none'; payment 'none'; fullscreen 'none'; display-capture 'none'; usb 'none'; serial 'none'; hid 'none'"
        src={url!.href} className="min-h-0 w-full flex-1 border-0 bg-white" />}
    </aside>
  );
}
