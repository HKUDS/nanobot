import { useEffect, useId, useRef, useState, type CSSProperties, type PointerEvent, type ReactNode } from "react";
import { Globe2, PanelRightClose, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { FileReferenceIcon, fileKindForPath, splitFilePath } from "@/components/FileReferenceChip";
import { FileActions } from "@/components/FileActions";
import { SidebarSelectionHighlight, SIDEBAR_SELECTION_ITEM_CLASS } from "@/components/SidebarSelectionHighlight";
import type { PreviewTab } from "@/hooks/useFilePreviewState";
import { cn } from "@/lib/utils";

function tabName(tab: PreviewTab) {
  return tab.kind === "web" ? new URL(tab.value).host : splitFilePath(tab.value).name;
}

/** One stable sidebar shell: switching targets never replays its opening animation. */
export function PreviewPane({ tabs, activeId, width, isClosing, onSelect, onCloseTab, onClose, onResizeStart, children }: {
  tabs: PreviewTab[];
  activeId: string;
  width: number;
  isClosing: boolean;
  onSelect: (id: string) => void;
  onCloseTab: (id: string) => void;
  onClose: () => void;
  onResizeStart: (event: PointerEvent<HTMLButtonElement>) => void;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  const id = useId();
  const [entered, setEntered] = useState(false);
  const buttons = useRef(new Map<string, HTMLButtonElement>());
  const tabList = useRef<HTMLDivElement>(null);
  const pendingFocus = useRef<string | null>(null);
  useEffect(() => {
    const frame = requestAnimationFrame(() => setEntered(true));
    return () => cancelAnimationFrame(frame);
  }, []);
  useEffect(() => {
    const revealActiveTab = () => buttons.current.get(activeId)?.parentElement?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
    revealActiveTab();
    if (pendingFocus.current) {
      buttons.current.get(pendingFocus.current)?.focus();
      pendingFocus.current = null;
    }
    if (!tabList.current || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(revealActiveTab);
    observer.observe(tabList.current);
    return () => observer.disconnect();
  }, [activeId, tabs]);
  const closeTab = (tab: PreviewTab, index: number) => {
    const remaining = tabs.filter((item) => item.id !== tab.id);
    pendingFocus.current = tab.id === activeId
      ? remaining[Math.min(index, remaining.length - 1)]?.id ?? null : activeId;
    onCloseTab(tab.id);
  };
  const iconButton = "inline-flex size-8 shrink-0 items-center justify-center rounded-control text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
  return <aside aria-label={t("previewTabs.title")} data-testid="preview-pane" data-file-preview-panel
    style={{
      "--file-preview-width": `${width}px`,
      "--file-preview-slot-width": !entered || isClosing ? "0px" : `${width}px`,
      "--file-preview-mobile-width": !entered || isClosing ? "0px" : "100%",
    } as CSSProperties}
    className={cn("file-preview-pane absolute inset-y-0 right-0 z-30 w-[var(--file-preview-mobile-width)] overflow-hidden transition-[width] duration-300 ease-out motion-reduce:transition-none", isClosing && "pointer-events-none")}
  >
    <div className={cn("file-preview-content absolute inset-y-0 right-0 flex w-[100cqw] flex-col border-l border-border/60 bg-background pb-[env(safe-area-inset-bottom)] transition-opacity duration-200 motion-reduce:transition-none", !entered || isClosing ? "opacity-0" : "opacity-100")}>
      <button type="button" aria-label={t("filePreview.resize")} onPointerDown={onResizeStart}
        className="file-preview-resize group absolute inset-y-0 left-0 z-20 hidden w-2 cursor-col-resize touch-none justify-start focus-visible:outline-none">
        <span aria-hidden className="h-full w-px bg-foreground/25 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" />
      </button>
      <div className="flex h-10 shrink-0 items-center gap-1 border-b border-border/40 px-2">
        <div ref={tabList} role="tablist" aria-label={t("previewTabs.title")} className="min-w-0 flex-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          <SidebarSelectionHighlight activeId={activeId} scope="preview-tabs" targetSelector="[data-preview-tab-active]"
            className="relative isolate flex w-max min-w-full items-center gap-1"
            highlightClassName="rounded-compact">
          {tabs.map((tab, index) => {
            const selected = tab.id === activeId;
            const name = tabName(tab);
            const item = <div key={tab.id} role="presentation" data-preview-tab-active={selected ? "" : undefined}
              className={cn(SIDEBAR_SELECTION_ITEM_CLASS, "group flex h-8 max-w-56 shrink-0 items-center rounded-compact", selected ? "text-foreground" : "text-muted-foreground hover:bg-muted/50 hover:text-foreground")}>
              <button type="button" role="tab" id={`${id}-tab-${index}`} aria-selected={selected} aria-controls={`${id}-panel`}
                tabIndex={selected ? 0 : -1} title={tab.value}
                ref={(node) => { if (node) buttons.current.set(tab.id, node); else buttons.current.delete(tab.id); }}
                onClick={() => onSelect(tab.id)}
                onKeyDown={(event) => {
                  let next: number;
                  if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
                  else if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
                  else if (event.key === "Home") next = 0;
                  else if (event.key === "End") next = tabs.length - 1;
                  else if (event.key === "Delete") { event.preventDefault(); closeTab(tab, index); return; }
                  else return;
                  event.preventDefault();
                  onSelect(tabs[next].id);
                  buttons.current.get(tabs[next].id)?.focus();
                }}
                className="flex h-8 min-w-0 items-center gap-1.5 rounded-compact pl-2.5 pr-1.5 text-[12.5px] font-medium leading-5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring">
                <span aria-hidden className="flex size-3.5 shrink-0 items-center justify-center text-muted-foreground">
                  {tab.kind === "web" ? <Globe2 className="size-3.5" />
                    : <FileReferenceIcon kind={fileKindForPath(tab.value)} className="size-3.5" />}
                </span>
                <span className="truncate">{name}</span>
              </button>
              <button type="button" tabIndex={selected ? 0 : -1} aria-label={t("previewTabs.closeTab", { name })} title={t("previewTabs.closeTab", { name })}
                onClick={() => closeTab(tab, index)}
                className={cn("mr-1 inline-flex size-6 shrink-0 items-center justify-center rounded-compact text-muted-foreground transition-colors hover:bg-foreground/10 hover:text-foreground focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", !selected && "sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100")}>
                <X className="size-3" aria-hidden />
              </button>
            </div>;
            return tab.kind === "file" ? <FileActions key={tab.id} path={tab.value} className="shrink-0">{item}</FileActions> : item;
          })}
          </SidebarSelectionHighlight>
        </div>
        {tabs.length > 1 ? <button type="button" className={iconButton} onClick={onClose} aria-label={t("previewTabs.closeAll")} title={t("previewTabs.closeAll")}>
          <PanelRightClose className="size-4" aria-hidden />
        </button> : null}
      </div>
      <div role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-tab-${tabs.findIndex((tab) => tab.id === activeId)}`} tabIndex={0}
        className="flex min-h-0 flex-1 flex-col focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring">
        {children}
      </div>
    </div>
  </aside>;
}
