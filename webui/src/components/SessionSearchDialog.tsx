import { type KeyboardEvent, useDeferredValue, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { ArchiveRestore, Check, Search } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  AutomationProtectedBadge,
  MutedHandleBadge,
  SessionStatusDot,
} from "@/components/session/SessionVisuals";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { deriveTitle, visibleSessionPreview } from "@/lib/format";
import { findLoadedMessagePreview } from "@/lib/loaded-message-search";
import {
  formatCompactRelativeTime,
  resolveProjectIdentity,
  type SessionAttentionState,
} from "@/lib/session-intelligence";
import type { ThreadMessageCache } from "@/lib/thread-message-cache";
import { cn } from "@/lib/utils";
import type { ChatSummary } from "@/lib/types";

type SearchStatusFilter = "all" | "active" | "open" | "done";

interface SessionSearchDialogProps {
  open: boolean;
  sessions: ChatSummary[];
  activeKey: string | null;
  loading: boolean;
  titleOverrides?: Record<string, string>;
  projectNameOverrides?: Record<string, string>;
  archivedKeys?: readonly string[];
  runningChatIds?: readonly string[];
  updatedChatIds?: readonly string[];
  recoveryChatIds?: readonly string[];
  automationCountsByKey?: ReadonlyMap<string, number>;
  defaultWorkspacePath?: string | null;
  messageCache?: ThreadMessageCache;
  onOpenChange: (open: boolean) => void;
  onSelect: (key: string) => void;
  onToggleArchive?: (key: string) => void;
}

interface SessionSearchResult {
  session: ChatSummary;
  title: string;
  preview?: string;
  attention: SessionAttentionState;
  archived: boolean;
  projectName: string;
  projectDotColor: string;
  projectId: string;
  automationCount: number;
  updatedMs: number;
}

const EMPTY_TITLE_OVERRIDES: Record<string, string> = {};
const EMPTY_STRING_LIST: readonly string[] = [];
const EMPTY_AUTOMATIONS: ReadonlyMap<string, number> = new Map();
const noSubscription = () => () => {};
const noRevision = () => 0;

export function SessionSearchDialog({
  open,
  sessions,
  activeKey,
  loading,
  titleOverrides = EMPTY_TITLE_OVERRIDES,
  projectNameOverrides = EMPTY_TITLE_OVERRIDES,
  archivedKeys = EMPTY_STRING_LIST,
  runningChatIds = EMPTY_STRING_LIST,
  updatedChatIds = EMPTY_STRING_LIST,
  recoveryChatIds = EMPTY_STRING_LIST,
  automationCountsByKey = EMPTY_AUTOMATIONS,
  defaultWorkspacePath = null,
  messageCache,
  onOpenChange,
  onSelect,
  onToggleArchive,
}: SessionSearchDialogProps) {
  const { t, i18n } = useTranslation();
  const isZh = Boolean(i18n.resolvedLanguage?.startsWith("zh"));
  const inputRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<SearchStatusFilter>("all");
  const [projectFilter, setProjectFilter] = useState<string | null>(null);
  const [highlightedIndex, setHighlightedIndex] = useState(0);

  const messageRevision = useSyncExternalStore(
    open && messageCache ? messageCache.subscribe : noSubscription,
    messageCache?.getRevision ?? noRevision,
  );
  const normalizedQuery = query.trim().toLowerCase();
  const searchQuery = useDeferredValue(normalizedQuery);
  const searchRevision = useDeferredValue(messageRevision);
  const searchPending = searchQuery !== normalizedQuery || searchRevision !== messageRevision;

  const archivedSet = useMemo(() => new Set(archivedKeys), [archivedKeys]);
  const runningSet = useMemo(() => new Set(runningChatIds), [runningChatIds]);
  const updatedSet = useMemo(() => new Set(updatedChatIds), [updatedChatIds]);
  const recoverySet = useMemo(() => new Set(recoveryChatIds), [recoveryChatIds]);

  const enrichedSessions = useMemo(() => {
    const generalLabel = isZh ? "通用对话" : t("chat.groups.all", { defaultValue: "General" });
    return sessions.map((session) => {
      const title = titleOverrides[session.key]?.trim()
        || session.title?.trim()
        || deriveTitle(session.preview, t("chat.newChat"));
      const project = resolveProjectIdentity(
        session,
        projectNameOverrides,
        defaultWorkspacePath,
        generalLabel,
      );
      const attention: SessionAttentionState = recoverySet.has(session.chatId)
        ? "recovery"
        : runningSet.has(session.chatId)
          ? "running"
          : updatedSet.has(session.chatId) && session.key !== activeKey
            ? "updated"
            : "idle";
      const updatedMs = Date.parse(session.updatedAt ?? session.createdAt ?? "") || 0;
      const text = [
        title,
        visibleSessionPreview(session.preview),
        project.name,
        project.path ?? undefined,
        session.handle ? `@${session.handle.name}` : undefined,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return {
        session,
        title,
        project,
        attention,
        archived: archivedSet.has(session.key),
        automationCount: automationCountsByKey.get(session.key) ?? 0,
        updatedMs,
        text,
      };
    });
  }, [
    activeKey,
    archivedSet,
    automationCountsByKey,
    defaultWorkspacePath,
    isZh,
    projectNameOverrides,
    recoverySet,
    runningSet,
    sessions,
    t,
    titleOverrides,
    updatedSet,
  ]);

  const projectOptions = useMemo(() => {
    const seen = new Map<string, { id: string; name: string; dotColor: string }>();
    for (const entry of enrichedSessions) {
      if (!seen.has(entry.project.id)) {
        seen.set(entry.project.id, {
          id: entry.project.id,
          name: entry.project.name,
          dotColor: entry.project.dotColor,
        });
      }
    }
    return Array.from(seen.values());
  }, [enrichedSessions]);

  const sessionResults = useMemo<SessionSearchResult[]>(() => {
    if (!open) return [];
    const terms = searchQuery ? searchQuery.split(/\s+/).filter(Boolean) : [];
    const results: SessionSearchResult[] = [];
    for (const entry of enrichedSessions) {
      if (statusFilter === "active" && entry.attention === "idle") continue;
      if (statusFilter === "open" && entry.archived) continue;
      if (statusFilter === "done" && !entry.archived) continue;
      if (projectFilter && entry.project.id !== projectFilter) continue;

      let matchPreview: string | undefined;
      if (terms.length > 0) {
        const directMatch = terms.every((term) => entry.text.includes(term));
        if (!directMatch) {
          matchPreview = messageCache
            ? findLoadedMessagePreview(
                messageCache.readLoadedMessages(entry.session.chatId),
                searchQuery,
              )
            : undefined;
          if (matchPreview === undefined) continue;
        }
      }

      results.push({
        session: entry.session,
        title: entry.title,
        preview: matchPreview,
        attention: entry.attention,
        archived: entry.archived,
        projectName: entry.project.name,
        projectDotColor: entry.project.dotColor,
        projectId: entry.project.id,
        automationCount: entry.automationCount,
        updatedMs: entry.updatedMs,
      });
    }
    return results;
  }, [
    enrichedSessions,
    messageCache,
    open,
    projectFilter,
    searchQuery,
    searchRevision,
    statusFilter,
  ]);

  const itemCount = sessionResults.length;
  const rowHeight = 68;
  const windowStart = Math.max(0, Math.min(itemCount - 1, Math.floor(scrollTop / rowHeight) - 4));
  const windowEnd = Math.min(itemCount, windowStart + 24);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setStatusFilter("all");
    setProjectFilter(null);
    setHighlightedIndex(0);
    window.setTimeout(() => inputRef.current?.focus(), 0);
  }, [open]);

  useEffect(() => {
    setHighlightedIndex(0);
    setScrollTop(0);
    if (scrollRef.current) scrollRef.current.scrollTop = 0;
  }, [normalizedQuery, statusFilter, projectFilter]);

  useEffect(() => {
    setHighlightedIndex((index) =>
      itemCount === 0 ? 0 : Math.min(index, itemCount - 1),
    );
  }, [itemCount]);

  useEffect(() => {
    itemRefs.current = itemRefs.current.slice(0, itemCount);
  }, [itemCount]);

  useEffect(() => {
    if (!open) return;
    const scroller = scrollRef.current;
    if (scroller) {
      const top = highlightedIndex * rowHeight;
      if (top < scroller.scrollTop || top + rowHeight > scroller.scrollTop + scroller.clientHeight) {
        scroller.scrollTop = top;
        setScrollTop(top);
      }
    }
    itemRefs.current[highlightedIndex]?.scrollIntoView({
      block: "nearest",
      inline: "nearest",
    });
  }, [highlightedIndex, open]);

  const handleSelect = (key: string) => {
    if (searchPending) return;
    onOpenChange(false);
    onSelect(key);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setHighlightedIndex((index) =>
        itemCount === 0 ? 0 : (index + 1) % itemCount,
      );
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlightedIndex((index) =>
        itemCount === 0 ? 0 : (index - 1 + itemCount) % itemCount,
      );
      return;
    }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "e" && onToggleArchive) {
      const highlighted = sessionResults[highlightedIndex];
      if (highlighted && highlighted.session.projectLocked !== false) {
        event.preventDefault();
        onToggleArchive(highlighted.session.key);
      }
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      if (searchPending) return;
      const highlighted = sessionResults[highlightedIndex];
      if (!highlighted) return;
      handleSelect(highlighted.session.key);
    }
  };

  const emptyLabel = normalizedQuery || statusFilter !== "all" || projectFilter
    ? t("sidebar.noSearchResults")
    : t("chat.noSessions");

  const statusTabs: Array<{ id: SearchStatusFilter; label: string }> = [
    { id: "all", label: isZh ? "全部" : "All" },
    { id: "active", label: isZh ? "活跃中" : "Active" },
    { id: "open", label: isZh ? "在办" : "Open" },
    { id: "done", label: isZh ? "已结单" : "Done" },
  ];

  const placeholderText = isZh
    ? "搜索会话标题、项目名、@handle 或消息..."
    : "Search sessions, projects, @handle, or messages...";

  if (!open) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className={cn(
          "session-search-dialog flex max-h-[min(40rem,100%)] w-[calc(100vw-2rem)] max-w-[44rem] flex-col gap-0 overflow-hidden p-0",
        )}
      >
        <DialogTitle className="sr-only">{t("sidebar.searchAria")}</DialogTitle>
        <DialogDescription className="sr-only">
          {placeholderText}
        </DialogDescription>

        {/* Search Input */}
        <div className="session-search-input flex h-[58px] shrink-0 items-center gap-3 border-b border-border/75 px-[18px]">
          <Search
            className="h-[18px] w-[18px] shrink-0 text-muted-foreground"
            aria-hidden
          />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholderText}
            aria-label={t("sidebar.searchAria")}
            className="h-full min-w-0 flex-1 bg-transparent text-[16px] font-normal leading-none text-foreground outline-none placeholder:text-muted-foreground"
          />
          <kbd className="hidden shrink-0 rounded-md border border-border/70 bg-muted/60 px-1.5 py-0.5 font-sans text-[11px] text-muted-foreground sm:inline">
            ESC
          </kbd>
        </div>

        {/* Status & Project Filter Bar — Zen minimal underline / monochrome tabs */}
        <div
          role="tablist"
          aria-label={isZh ? "筛选会话" : "Filter sessions"}
          className="flex shrink-0 flex-wrap items-center gap-3.5 border-b border-border/45 px-[18px] py-2 text-[12px]"
        >
          {statusTabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={statusFilter === tab.id}
              onClick={() => setStatusFilter(tab.id)}
              className={cn(
                "transition-colors",
                statusFilter === tab.id
                  ? "font-medium text-foreground"
                  : "text-muted-foreground/65 hover:text-foreground",
              )}
            >
              {tab.label}
            </button>
          ))}
          {projectOptions.length > 1 ? (
            <>
              <span aria-hidden className="h-3 w-px bg-border/70" />
              {projectOptions.slice(0, 5).map((proj) => {
                const selected = projectFilter === proj.id;
                return (
                  <button
                    key={proj.id}
                    type="button"
                    role="tab"
                    aria-selected={selected}
                    onClick={() => setProjectFilter(selected ? null : proj.id)}
                    className={cn(
                      "max-w-[8rem] truncate transition-colors",
                      selected
                        ? "font-medium text-foreground"
                        : "text-muted-foreground/60 hover:text-foreground",
                    )}
                  >
                    {proj.name}
                  </button>
                );
              })}
            </>
          ) : null}
        </div>

        {/* Virtualized Results */}
        <div
          ref={scrollRef}
          onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
          data-testid="session-search-scroll"
          aria-busy={searchPending}
          className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-2.5 scrollbar-thin scrollbar-track-transparent"
        >
          <section>
            <div className="session-search-label flex items-center justify-between px-2.5 pb-1.5 pt-1 text-[11.5px] font-medium text-muted-foreground">
              <span>
                {normalizedQuery || statusFilter !== "all" || projectFilter
                  ? t("sidebar.searchResults")
                  : t("sidebar.recent")}
              </span>
              <span className="tabular-nums">{sessionResults.length}</span>
            </div>

            {loading && sessions.length === 0 ? (
              <div className="px-3 py-7 text-[13px] text-muted-foreground">
                {t("chat.loading")}
              </div>
            ) : sessionResults.length === 0 ? (
              <div className="px-3 py-7 text-[13px] text-muted-foreground">
                {emptyLabel}
              </div>
            ) : (
              <ul>
                <li aria-hidden style={{ height: windowStart * rowHeight }} />
                {sessionResults.slice(windowStart, windowEnd).map((result, offset) => {
                  const index = windowStart + offset;
                  const { session, title } = result;
                  const preview = result.preview ?? visibleSessionPreview(session.preview);
                  const showPreview =
                    preview.length > 0
                    && preview.toLowerCase() !== title.trim().toLowerCase();
                  const highlighted = index === highlightedIndex;
                  const active = session.key === activeKey;
                  const canArchive = Boolean(onToggleArchive && session.projectLocked !== false);

                  return (
                    <li key={session.key} style={{ height: rowHeight }}>
                      <div
                        onMouseEnter={() => setHighlightedIndex(index)}
                        className={cn(
                          "group flex h-full w-full min-w-0 items-center gap-3 rounded-xl px-3 py-2 transition-colors",
                          highlighted
                            ? "bg-muted text-foreground"
                            : "text-foreground hover:bg-muted/70",
                        )}
                      >
                        <SessionStatusDot state={result.attention} />
                        <button
                          ref={(node) => {
                            itemRefs.current[index] = node;
                          }}
                          type="button"
                          disabled={searchPending}
                          onClick={() => handleSelect(session.key)}
                          aria-current={active ? "page" : undefined}
                          className="min-w-0 flex-1 text-left focus-visible:outline-none"
                        >
                          <div className="flex min-w-0 items-center gap-2">
                            <span className={cn("min-w-0 truncate text-[13.5px] font-medium leading-5", result.archived && "text-muted-foreground/75")}>
                              {title}
                            </span>
                            <span className="max-w-[7rem] shrink-0 truncate text-[11.5px] text-muted-foreground/60">
                              {result.projectName}
                            </span>
                            <MutedHandleBadge handle={session.handle} className="hidden sm:inline" />
                            <AutomationProtectedBadge count={result.automationCount} compact />
                            {result.archived ? (
                              <span className="shrink-0 text-[11px] text-muted-foreground/60">
                                · {isZh ? "已结单" : "Done"}
                              </span>
                            ) : null}
                          </div>
                          {showPreview ? (
                            <span className="mt-0.5 block truncate text-[12px] leading-4 text-muted-foreground">
                              {preview}
                            </span>
                          ) : null}
                        </button>

                        <div className="flex shrink-0 items-center gap-1.5">
                          {active ? (
                            <span className="rounded-full bg-muted-foreground/12 px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
                              {t("common.current", { defaultValue: "Current" })}
                            </span>
                          ) : (
                            <span className="text-[11.5px] tabular-nums text-muted-foreground">
                              {formatCompactRelativeTime(result.updatedMs, i18n.resolvedLanguage)}
                            </span>
                          )}
                          {canArchive && onToggleArchive ? (
                            <button
                              type="button"
                              aria-label={result.archived ? (isZh ? "恢复到在办" : "Restore") : (isZh ? "结单归档" : "Mark done")}
                              onClick={(event) => {
                                event.stopPropagation();
                                onToggleArchive(session.key);
                              }}
                              className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground opacity-0 transition-opacity hover:bg-background hover:text-foreground group-hover:opacity-100 focus-visible:opacity-100"
                            >
                              {result.archived ? (
                                <ArchiveRestore className="h-3.5 w-3.5" aria-hidden />
                              ) : (
                                <Check className="h-3.5 w-3.5" aria-hidden />
                              )}
                            </button>
                          ) : null}
                        </div>
                      </div>
                    </li>
                  );
                })}
                <li aria-hidden style={{ height: (itemCount - windowEnd) * rowHeight }} />
              </ul>
            )}
          </section>
        </div>

        {/* Keyboard Hints Footer */}
        <div className="hidden shrink-0 items-center justify-between border-t border-border/55 bg-muted/20 px-4 py-2 text-[11px] text-muted-foreground sm:flex">
          <div className="flex items-center gap-3">
            <span>↑↓ {isZh ? "移动" : "Navigate"}</span>
            <span>↵ {isZh ? "打开" : "Open"}</span>
            {onToggleArchive ? (
              <span>
                {typeof navigator !== "undefined" && /mac|iphone|ipad|ipod/i.test(navigator.platform || "") ? "⌘E" : "Ctrl+E"}{" "}
                {isZh ? "结单 / 恢复" : "Done / Restore"}
              </span>
            ) : null}
          </div>
          <span>ESC {isZh ? "关闭" : "Close"}</span>
        </div>
      </DialogContent>
    </Dialog>
  );
}
