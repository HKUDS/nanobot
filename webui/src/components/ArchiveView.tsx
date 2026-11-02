import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArchiveRestore,
  ChevronLeft,
  ListChecks,
  MoreHorizontal,
  Search,
  Square,
  SquareCheckBig,
  SquareMinus,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { ArchiveConfirm } from "@/components/ArchiveConfirm";
import type { SidebarDeleteDecision, SidebarDeleteItem } from "@/components/ChatList";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SearchInput } from "@/components/ui/input";
import { HoverHint } from "@/components/ui/tooltip";
import { displayTitle } from "@/lib/chat-groups";
import { sessionHandleColor } from "@/lib/session-handle";
import type { ChatSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface ArchiveViewProps {
  sessions: ChatSummary[];
  titleOverrides: Record<string, string>;
  loading: boolean;
  loadError: boolean;
  onRetry: () => void;
  onOpen: (key: string) => void;
  onUnarchive: (keys: string[]) => void;
  onRequestDeleteMany: (items: SidebarDeleteItem[], onDecision?: SidebarDeleteDecision) => void;
  onBack: () => void;
  hostChromeInset?: boolean;
}

export function ArchiveView({
  sessions,
  titleOverrides,
  loading,
  loadError,
  onRetry,
  onOpen,
  onUnarchive,
  onRequestDeleteMany,
  onBack,
  hostChromeInset = false,
}: ArchiveViewProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(() => new Set());
  const [pendingUnarchive, setPendingUnarchive] = useState<string[] | null>(null);
  const [deletePending, setDeletePending] = useState(false);
  const deletePendingRef = useRef(false);
  const selectionButtonRef = useRef<HTMLButtonElement>(null);
  const searchRegionRef = useRef<HTMLDivElement>(null);
  const focusSearchAfterMenuRef = useRef(false);

  const entries = useMemo(() => sessions.map((session) => ({
    session,
    title: displayTitle(session, titleOverrides, t("chat.newChat")),
  })), [sessions, t, titleOverrides]);
  const visibleEntries = useMemo(() => {
    const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    return entries.filter(({ session, title }) => {
      const text = `${title} ${session.handle ? `@${session.handle.name}` : ""}`.toLowerCase();
      return terms.every((term) => text.includes(term));
    });
  }, [entries, query]);
  const visibleKeys = useMemo(() => new Set(visibleEntries.map(({ session }) => session.key)), [visibleEntries]);
  const selectedEntries = visibleEntries.filter(({ session }) => selectedKeys.has(session.key));
  const selectedVisibleCount = selectedEntries.length;
  const allVisibleSelected = visibleEntries.length > 0 && selectedVisibleCount === visibleEntries.length;
  const someVisibleSelected = selectedVisibleCount > 0 && !allVisibleSelected;
  const pendingUnarchiveKeys = pendingUnarchive?.filter((key) => visibleKeys.has(key)) ?? [];

  useEffect(() => {
    if (loading) return;
    setSelectedKeys((current) => {
      const next = new Set(Array.from(current).filter((key) => visibleKeys.has(key)));
      return next.size === current.size ? current : next;
    });
    setPendingUnarchive((current) => {
      if (!current) return null;
      const next = current.filter((key) => visibleKeys.has(key));
      return next.length === 0 ? null : next.length === current.length ? current : next;
    });
  }, [loading, visibleKeys]);

  const closeSelection = () => {
    setSelectionMode(false);
    setSelectedKeys(new Set());
  };

  const toggleSelection = (key: string) => {
    if (deletePendingRef.current) return;
    setSelectedKeys((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const toggleAllVisible = () => {
    if (deletePendingRef.current || visibleEntries.length === 0) return;
    setSelectedKeys((current) => {
      const next = new Set(current);
      const allSelected = visibleEntries.every(({ session }) => current.has(session.key));
      for (const { session } of visibleEntries) {
        if (allSelected) next.delete(session.key);
        else next.add(session.key);
      }
      return next;
    });
  };

  const requestDelete = (items: SidebarDeleteItem[], fromSelection: boolean) => {
    if (deletePendingRef.current || items.length === 0) return;
    deletePendingRef.current = true;
    setDeletePending(true);
    onRequestDeleteMany(items, (confirmed) => {
      deletePendingRef.current = false;
      setDeletePending(false);
      if (confirmed && fromSelection) closeSelection();
    });
  };

  const selectionCount = selectedEntries.length;
  const searchLabel = t("archiveView.search", { defaultValue: "Search archived topics" });
  const selectAllLabel = t("archiveView.selectAll", { defaultValue: "Select all results" });
  const SelectAllIcon = allVisibleSelected ? SquareCheckBig : someVisibleSelected ? SquareMinus : Square;

  return (
    <div
      data-archive-view
      role="region"
      aria-label={t("chat.groups.archived")}
      onKeyDown={(event) => {
        if (event.key !== "Escape" || !selectionMode || deletePending || pendingUnarchive) return;
        event.preventDefault();
        closeSelection();
        if (sessions.length === 0) searchRegionRef.current?.focus();
        else selectionButtonRef.current?.focus();
      }}
      className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-settings-canvas"
    >
      <div className="min-h-0 min-w-0 flex-1 overflow-y-auto overscroll-contain [scrollbar-gutter:stable]">
        <div
          className={cn(
            "settings-grid settings-feature-page mx-auto w-full py-6 sm:py-8 lg:py-12",
            hostChromeInset && "pt-[4.25rem] sm:pt-[4.25rem] lg:pt-[4.75rem]",
          )}
        >
          <header className="mb-7">
            <Button type="button" variant="ghost" size="sm" onClick={onBack} className="touch-target mb-4 h-auto min-h-9 max-w-full gap-1 whitespace-normal py-1.5 text-left">
              <ChevronLeft className="h-4 w-4 shrink-0" aria-hidden />
              {t("settings.backToChat")}
            </Button>
            <h1 className="text-[24px] font-normal leading-tight tracking-normal text-foreground sm:text-[28px]">
              {t("chat.groups.archived")}
            </h1>
          </header>

          <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center">
            <div
              ref={searchRegionRef}
              role="search"
              aria-label={t("sidebar.searchAria")}
              tabIndex={-1}
              className="relative min-w-0 flex-1 rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Search className="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
              <SearchInput
                type="search"
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setSelectedKeys(new Set());
                }}
                placeholder={searchLabel}
                aria-label={searchLabel}
                className="h-10 ps-9 text-[13px] focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              />
            </div>
            <Button
              ref={selectionButtonRef}
              type="button"
              variant="ghost"
              size="sm"
              disabled={deletePending || (!selectionMode && sessions.length === 0)}
              onClick={() => {
                if (selectionMode) {
                  closeSelection();
                  if (sessions.length === 0) searchRegionRef.current?.focus();
                } else setSelectionMode(true);
              }}
              className="touch-target h-auto min-h-9 max-w-full gap-1.5 self-start whitespace-normal px-3 py-1.5 sm:self-auto"
            >
              <ListChecks className="h-4 w-4 shrink-0" aria-hidden />
              {selectionMode
                ? t("archiveView.cancelSelection", { defaultValue: "Cancel selection" })
                : t("chat.select")}
            </Button>
          </div>

          {selectionMode ? (
            <div
              data-archive-selection-toolbar
              aria-busy={deletePending}
              className={cn(
                "sticky z-10 mt-3 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 border-b border-border/60 bg-settings-canvas py-2",
                hostChromeInset ? "top-11" : "top-0",
              )}
            >
              <button
                type="button"
                role="checkbox"
                aria-checked={allVisibleSelected ? true : someVisibleSelected ? "mixed" : false}
                disabled={visibleEntries.length === 0 || deletePending}
                onClick={toggleAllVisible}
                className="touch-target inline-flex min-h-8 min-w-0 items-center gap-2 rounded-control px-2 text-left text-[13px] text-foreground settings-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-40"
              >
                <SelectAllIcon className="h-4 w-4 shrink-0" aria-hidden />
                <span>{selectAllLabel}</span>
              </button>
              <span aria-live="polite" className="min-w-0 flex-1 px-1 text-[12.5px] font-medium text-muted-foreground">
                {t("chat.selectedCount", { count: selectionCount })}
              </span>
              <HoverHint content={t("chat.unarchive")}>
                <button
                  type="button"
                  aria-label={t("chat.unarchive")}
                  aria-disabled={deletePending || undefined}
                  disabled={selectionCount === 0}
                  onClick={() => {
                    if (deletePendingRef.current || selectionCount === 0) return;
                    setPendingUnarchive(selectedEntries.map(({ session }) => session.key));
                  }}
                  className="touch-target inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-foreground transition-colors settings-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-40 aria-disabled:opacity-40"
                >
                  <ArchiveRestore className="h-4 w-4" aria-hidden />
                </button>
              </HoverHint>
              <HoverHint content={t("chat.delete")}>
                <button
                  type="button"
                  aria-label={t("chat.delete")}
                  aria-disabled={deletePending || undefined}
                  disabled={selectionCount === 0}
                  onClick={() => requestDelete(
                    selectedEntries.map(({ session, title }) => ({ key: session.key, label: title })),
                    true,
                  )}
                  className="touch-target inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-destructive transition-colors media-hover:hover:bg-destructive/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-40 aria-disabled:opacity-40"
                >
                  <Trash2 className="h-4 w-4" aria-hidden />
                </button>
              </HoverHint>
            </div>
          ) : null}

          <div aria-busy={loading} className="mt-3">
            {loadError ? (
              <div role="alert" className="flex flex-wrap items-center gap-2 px-3 py-2 text-[13px] text-destructive">
                <span>{t("archiveView.loadError", { defaultValue: "Couldn't load all topics." })}</span>
                <Button type="button" variant="ghost" size="sm" disabled={loading} onClick={onRetry}>
                  {t("common.retry")}
                </Button>
              </div>
            ) : null}
            {loading && sessions.length === 0 ? (
              <div role="status" className="px-3 py-7 text-[13px] text-muted-foreground">
                {t("chat.loading")}
              </div>
            ) : sessions.length === 0 ? (
              loadError ? null : <p className="px-3 py-7 text-[13px] leading-5 text-muted-foreground">
                {t("archiveView.empty", { defaultValue: "No archived topics." })}
              </p>
            ) : visibleEntries.length === 0 ? (
              <p className="px-3 py-7 text-[13px] leading-5 text-muted-foreground">
                {t("archiveView.noResults", { defaultValue: "No matching archived topics." })}
              </p>
            ) : (
              <ul className="space-y-0.5">
                {visibleEntries.map(({ session, title }) => {
                  const selected = selectedKeys.has(session.key);
                  const SelectionIcon = selected ? SquareCheckBig : Square;
                  return (
                    <li key={session.key} data-archive-row={session.key} className="min-w-0">
                      <div className={cn(
                        "group flex min-h-11 min-w-0 items-center gap-1 rounded-control px-2 text-ui transition-colors settings-hover",
                        selectionMode && selected && "bg-sidebar-accent/55 text-foreground",
                      )}>
                        <button
                          type="button"
                          disabled={deletePending}
                          aria-pressed={selectionMode ? selected : undefined}
                          onClick={() => {
                            if (selectionMode) toggleSelection(session.key);
                            else onOpen(session.key);
                          }}
                          className="flex min-h-11 min-w-0 flex-1 items-center gap-2 overflow-hidden rounded-control py-1.5 text-left text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring disabled:opacity-50"
                        >
                          {selectionMode ? (
                            <SelectionIcon className={cn("h-4 w-4 shrink-0", selected ? "text-primary" : "text-muted-foreground")} aria-hidden />
                          ) : null}
                          {session.handle ? (
                            <span className="flex max-w-[35%] shrink-0 overflow-hidden whitespace-nowrap font-mono text-[11px] font-medium leading-5 text-muted-foreground" title={`@${session.handle.name}`}>
                              <span className="truncate border-b-2" style={{ borderBottomColor: sessionHandleColor(session.handle.id) }}>
                                @{session.handle.name}
                              </span>
                            </span>
                          ) : null}
                          <span className="min-w-0 flex-1 truncate font-normal leading-5" title={title}>{title}</span>
                        </button>
                        {!selectionMode ? (
                          <DropdownMenu modal={false}>
                            <DropdownMenuTrigger asChild>
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                aria-label={t("chat.actions", { title })}
                                className="sidebar-action-trigger touch-target h-9 w-9 shrink-0 text-muted-foreground opacity-0 transition-opacity media-hover:group-hover:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100"
                              >
                                <MoreHorizontal className="h-4 w-4" aria-hidden />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent
                              align="end"
                              className="w-max min-w-[11rem] max-w-[calc(100vw-2rem)]"
                              onCloseAutoFocus={(event) => {
                                if (!focusSearchAfterMenuRef.current) return;
                                event.preventDefault();
                                focusSearchAfterMenuRef.current = false;
                                searchRegionRef.current?.focus();
                              }}
                            >
                              <DropdownMenuItem disabled={deletePending} onSelect={() => {
                                focusSearchAfterMenuRef.current = true;
                                onUnarchive([session.key]);
                              }}>
                                <ArchiveRestore className="h-4 w-4 shrink-0" aria-hidden />
                                <span className="min-w-0 break-words">{t("chat.unarchive")}</span>
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                tone="destructive"
                                disabled={deletePending}
                                onSelect={() => window.setTimeout(() => requestDelete([{ key: session.key, label: title }], false), 0)}
                              >
                                <Trash2 className="h-4 w-4 shrink-0" aria-hidden />
                                <span className="min-w-0 break-words">{t("chat.delete")}</span>
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        ) : null}
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
      </div>
      {pendingUnarchive && (pendingUnarchiveKeys.length > 0 || loading) ? (
        <ArchiveConfirm
          count={loading ? pendingUnarchive.length : pendingUnarchiveKeys.length}
          archive={false}
          onCancel={() => setPendingUnarchive(null)}
          onConfirm={() => {
            setPendingUnarchive(null);
            if (pendingUnarchiveKeys.length === 0
              || (loading && pendingUnarchiveKeys.length !== pendingUnarchive.length)) return;
            onUnarchive(pendingUnarchiveKeys);
            closeSelection();
            window.requestAnimationFrame(() => searchRegionRef.current?.focus());
          }}
        />
      ) : null}
    </div>
  );
}
