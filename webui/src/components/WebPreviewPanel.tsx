import { useState } from "react";
import { ExternalLink, Info, RotateCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { isLoopbackHost } from "@/lib/network";
import { isNativeRuntime } from "@/lib/runtime";
import { parseWebLink, webPreviewRestriction } from "@/lib/web-preview";

interface WebPreviewPanelProps {
  url: string;
}

export function WebPreviewPanel({ url: value }: WebPreviewPanelProps) {
  const { t } = useTranslation();
  const [revision, setRevision] = useState(0);
  const url = parseWebLink(value);
  const restriction = url ? webPreviewRestriction(url, new URL(window.location.href), isNativeRuntime(),
    "credentialless" in HTMLIFrameElement.prototype) : "invalid";
  const buttonClass = "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
  return (
    <section aria-label={t("webPreview.title")} data-testid="web-preview-panel" className="flex min-h-0 flex-1 flex-col">
      <div className="flex h-9 shrink-0 items-center gap-1 border-b border-border/40 px-2">
        <p className="min-w-0 flex-1 truncate px-1 text-xs text-muted-foreground" title={url?.href}>{url?.href}</p>
        <Popover>
          <PopoverTrigger asChild><button type="button" className={buttonClass} aria-label={t("previewTabs.websiteInfo")} title={t("previewTabs.websiteInfo")}><Info className="size-3.5" aria-hidden /></button></PopoverTrigger>
          <PopoverContent align="end" className="w-72 space-y-2 rounded-control p-3 text-xs leading-relaxed text-muted-foreground">
            <p>{t("webPreview.isolated")}</p>
            <p>{t("webPreview.blockedHint")}</p>
            {url && isLoopbackHost(url.hostname) ? <p>{t("webPreview.loopback")}</p> : null}
          </PopoverContent>
        </Popover>
        {!restriction ? <button type="button" className={buttonClass} onClick={() => setRevision((n) => n + 1)} title={t("webPreview.refresh")} aria-label={t("webPreview.refresh")}>
          <RotateCw className="h-4 w-4" aria-hidden />
        </button> : null}
        {url ? <a className={buttonClass} href={url.href} target="_blank" rel="noreferrer noopener" title={t("webPreview.external")} aria-label={t("webPreview.external")}>
          <ExternalLink className="h-4 w-4" aria-hidden />
        </a> : null}
      </div>
      {restriction ? <div role="status" className="flex min-h-0 flex-1 items-center justify-center overflow-auto p-6 text-center text-sm text-muted-foreground">
        {t(`webPreview.${restriction}`)}
      </div> : <iframe key={`${value}:${revision}`} title={t("webPreview.frame", { host: url!.host })}
        {...{ credentialless: "" }} sandbox="allow-scripts" referrerPolicy="no-referrer"
        allow="camera 'none'; microphone 'none'; geolocation 'none'; clipboard-read 'none'; clipboard-write 'none'; payment 'none'; fullscreen 'none'; display-capture 'none'; usb 'none'; serial 'none'; hid 'none'"
        src={url!.href} className="min-h-0 w-full flex-1 border-0 bg-white" />}
    </section>
  );
}
