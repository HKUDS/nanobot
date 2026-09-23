import { createContext, useContext, useEffect, useState, type ComponentPropsWithoutRef } from "react";
import { Copy, ExternalLink, MoreHorizontal, PanelRight } from "lucide-react";
import { useTranslation } from "react-i18next";

import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { copyTextToClipboard } from "@/lib/clipboard";
import { parseWebLink } from "@/lib/web-preview";
import { cn } from "@/lib/utils";

export const WebPreviewContext = createContext<((url: string) => void) | undefined>(undefined);

export function WebLink({ href = "", children, layout = "inline", className, ...props }: ComponentPropsWithoutRef<"a"> & { layout?: "inline" | "row" }) {
  const { t } = useTranslation();
  const openPreview = useContext(WebPreviewContext);
  const [open, setOpen] = useState(false);
  const [feedback, setFeedback] = useState("");
  useEffect(() => {
    if (!feedback) return;
    const timer = window.setTimeout(() => setFeedback(""), 4000);
    return () => window.clearTimeout(timer);
  }, [feedback]);
  const url = parseWebLink(href);
  const anchor = <a {...props} className={cn(className, layout === "row" && "min-w-0 flex-1")} href={href} target="_blank" rel="noreferrer noopener">{children}</a>;
  if (!url) {
    // Keep the renderer's relative media/document and mail links unchanged.
    const relative = !/^[a-z][a-z\d+.-]*:/i.test(href)
      && !href.includes("\\") && !Array.from(href).some((char) => char.charCodeAt(0) < 32);
    return relative || /^(mailto:|tel:|#)/i.test(href) ? anchor : <>{children}</>;
  }
  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <span className={cn("max-w-full", layout === "row" ? "inline-flex w-full min-w-0 items-center" : "inline")} onContextMenu={(event) => {
        event.preventDefault(); event.stopPropagation(); setOpen(true);
      }} onKeyDown={(event) => {
        if ((event.shiftKey && event.key === "F10") || event.key === "ContextMenu") {
          event.preventDefault(); event.stopPropagation(); setOpen(true);
        }
      }}>
        {anchor}
        <DropdownMenuTrigger asChild>
          <button type="button" aria-label={t("webPreview.actions")} title={t("webPreview.actions")}
            className="ml-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md align-middle text-muted-foreground/70 hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <MoreHorizontal className="h-3.5 w-3.5" aria-hidden />
          </button>
        </DropdownMenuTrigger>
      </span>
      <DropdownMenuContent align="start">
        <DropdownMenuLabel className="max-w-64 truncate">{url.host}</DropdownMenuLabel>
        {openPreview ? <DropdownMenuItem onSelect={() => openPreview(url.href)}>
          <PanelRight className="h-4 w-4" aria-hidden />{t("webPreview.open")}
        </DropdownMenuItem> : null}
        <DropdownMenuItem asChild>
          <a href={url.href} target="_blank" rel="noreferrer noopener">
            <ExternalLink className="h-4 w-4" aria-hidden />{t("webPreview.external")}
          </a>
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={(event) => {
          // Keep the menu/focus alive until the clipboard fallback finishes.
          event.preventDefault();
          setFeedback("");
          void copyTextToClipboard(url.href).then((copied) => setFeedback(t(copied ? "webPreview.copied" : "webPreview.copyFailed")));
        }}><Copy className="h-4 w-4" aria-hidden />{t("webPreview.copy")}</DropdownMenuItem>
        {feedback ? <div role="status" className="px-2.5 py-1.5 text-xs text-muted-foreground">{feedback}</div> : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
