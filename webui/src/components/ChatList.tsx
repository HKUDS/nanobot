import {
  Archive,
  ArchiveRestore,
  MoreHorizontal,
  Pencil,
  Pin,
  PinOff,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { deriveTitle, relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { ChatSummary, SidebarDensity, SidebarSortMode } from "@/lib/types";

interface ChatListProps {
  sessions: ChatSummary[];
  activeKey: string | null;
  onSelect: (key: string) => void;
  onRequestDelete: (key: string, label: string) => void;
  onTogglePin: (key: string) => void;
  onRequestRename: (key: string, label: string) => void;
  onToggleArchive: (key: string) => void;
  pinnedKeys?: string[];
  archivedKeys?: string[];
  titleOverrides?: Record<string, string>;
  runningChatIds?: string[];
  completedChatIds?: string[];
  density?: SidebarDensity;
  showPreviews?: boolean;
  showTimestamps?: boolean;
  sort?: SidebarSortMode;
  showArchived?: boolean;
  actionMenuPortalContainer?: HTMLElement | null;
  loading?: boolean;
  emptyLabel?: string;
}

export function ChatList({
  sessions,
  activeKey,
  onSelect,
  onRequestDelete,
  onTogglePin,
  onRequestRename,
  onToggleArchive,
  pinnedKeys = [],
  archivedKeys = [],
  titleOverrides = {},
  runningChatIds = [],
  completedChatIds = [],
  density = "comfortable",
  showPreviews = false,
  showTimestamps = false,
  sort = "updated_desc",
  showArchived = false,
  actionMenuPortalContainer,
  loading,
  emptyLabel,
}: ChatListProps) {
  const { t } = useTranslation();
  if (loading && sessions.length === 0) {
    return (
      <div className="px-3 py-6 text-[12px] text-muted-foreground">
        {t("chat.loading")}
      </div>
    );
  }

  if (sessions.length === 0) {
    return (
      <div className="px-3 py-6 text-[12px] leading-5 text-muted-foreground/80">
        {emptyLabel ?? t("chat.noSessions")}
      </div>
    );
  }

  const groups = groupSessions(sessions, {
    pinned: t("chat.groups.pinned"),
    all: t("chat.groups.all"),
    today: t("chat.groups.today"),
    yesterday: t("chat.groups.yesterday"),
    earlier: t("chat.groups.earlier"),
    archived: t("chat.groups.archived"),
    fallbackTitle: t("chat.newChat"),
  }, {
    pinnedKeys,
    archivedKeys,
    titleOverrides,
    showArchived,
    sort,
  });
  const pinned = new Set(pinnedKeys);
  const archived = new Set(archivedKeys);
  const running = new Set(runningChatIds);
  const completed = new Set(completedChatIds);
  const compact = density === "compact";

  return (
    <div className="h-full min-h-0 min-w-0 overflow-x-hidden overflow-y-auto overscroll-contain">
      <div className="min-w-0 space-y-3 px-2 py-1.5">
        {groups.map((group) => (
          <section key={group.label} aria-label={group.label}>
            <div className="px-2 pb-1 text-[12px] font-medium text-muted-foreground/65">
              {group.label}
            </div>
            <ul className="space-y-0.5">
              {group.sessions.map((s) => {
                const active = s.key === activeKey;
                const fallbackTitle = t("chat.fallbackTitle", {
                  id: s.chatId.slice(0, 6),
                });
                const generatedTitle = s.title?.trim() || "";
                const title = displayTitle(s, titleOverrides, t("chat.newChat"));
                const tooltipTitle =
                  titleOverrides[s.key]?.trim() ||
                  generatedTitle ||
                  deriveTitle(s.preview, fallbackTitle);
                const isPinned = pinned.has(s.key);
                const isArchived = archived.has(s.key);
                const preview = s.preview.trim();
                const showPreview = showPreviews && preview && preview !== title;
                const timestamp = showTimestamps
                  ? relativeTime(s.updatedAt ?? s.createdAt)
                  : "";
                const activityState = running.has(s.chatId)
                  ? "running"
                  : completed.has(s.chatId)
                    ? "complete"
                    : null;
                return (
                  <li key={s.key} className="min-w-0">
                    <div
                      className={cn(
                        "group flex min-w-0 max-w-full items-center gap-2 rounded-xl px-2 text-[13px] transition-colors",
                        compact ? "min-h-7" : "min-h-8",
                        active
                          ? "bg-sidebar-accent/70 text-sidebar-accent-foreground shadow-[inset_0_0_0_1px_hsl(var(--sidebar-border)/0.28)]"
                          : "text-sidebar-foreground/82 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground",
                      )}
                    >
                      <button
                        type="button"
                        onClick={() => onSelect(s.key)}
                        title={tooltipTitle}
                        className={cn(
                          "min-w-0 flex-1 overflow-hidden text-left",
                          compact ? "py-1" : "py-1.5",
                        )}
                      >
                        <span className="block w-full truncate font-medium leading-5">{title}</span>
                        {showPreview ? (
                          <span className="block w-full truncate text-[11.5px] leading-4 text-muted-foreground/72">
                            {preview}
                          </span>
                        ) : null}
                        {timestamp ? (
                          <span className="block w-full truncate text-[11px] leading-4 text-muted-foreground/58">
                            {timestamp}
                          </span>
                        ) : null}
                      </button>
                      <SessionActivityIndicator state={activityState} />
                      <DropdownMenu modal={false}>
                        <DropdownMenuTrigger
                          className={cn(
                            "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground/75 opacity-40 transition-opacity",
                            "hover:bg-sidebar-accent hover:text-sidebar-foreground group-hover:opacity-100",
                            "focus-visible:opacity-100",
                            active && "opacity-100",
                          )}
                          aria-label={t("chat.actions", { title })}
                        >
                          <MoreHorizontal className="h-3.5 w-3.5" />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent
                          align="end"
                          portalContainer={actionMenuPortalContainer}
                          onCloseAutoFocus={(event) => event.preventDefault()}
                        >
                          <DropdownMenuItem
                            onSelect={() => onTogglePin(s.key)}
                          >
                            {isPinned ? (
                              <PinOff className="mr-2 h-4 w-4" />
                            ) : (
                              <Pin className="mr-2 h-4 w-4" />
                            )}
                            {isPinned ? t("chat.unpin") : t("chat.pin")}
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onSelect={() => onRequestRename(s.key, title)}
                          >
                            <Pencil className="mr-2 h-4 w-4" />
                            {t("chat.rename")}
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onSelect={() => onToggleArchive(s.key)}
                          >
                            {isArchived ? (
                              <ArchiveRestore className="mr-2 h-4 w-4" />
                            ) : (
                              <Archive className="mr-2 h-4 w-4" />
                            )}
                            {isArchived ? t("chat.unarchive") : t("chat.archive")}
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onSelect={() => {
                              window.setTimeout(() => onRequestDelete(s.key, title), 0);
                            }}
                            className="text-destructive focus:text-destructive"
                          >
                            <Trash2 className="mr-2 h-4 w-4" />
                            {t("chat.delete")}
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}

function SessionActivityIndicator({
  state,
}: {
  state: "running" | "complete" | null;
}) {
  const { t } = useTranslation();

  if (state === "running") {
    const label = t("chat.activity.running");
    return (
      <span
        aria-label={label}
        title={label}
        className="grid h-4 w-4 shrink-0 place-items-center"
      >
        <span className="h-3 w-3 animate-spin rounded-full border border-blue-500/25 border-t-blue-500 [animation-duration:1.4s] motion-reduce:animate-none dark:border-blue-400/25 dark:border-t-blue-400" />
      </span>
    );
  }

  if (state === "complete") {
    const label = t("chat.activity.complete");
    return (
      <span
        aria-label={label}
        title={label}
        className="grid h-4 w-4 shrink-0 place-items-center"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-blue-500 shadow-[0_0_0_3px_rgba(59,130,246,0.14)] dark:bg-blue-400 dark:shadow-[0_0_0_3px_rgba(96,165,250,0.18)]" />
      </span>
    );
  }

  return <span className="h-4 w-4 shrink-0" aria-hidden="true" />;
}

function groupSessions(
  sessions: ChatSummary[],
  labels: {
    pinned: string;
    all: string;
    today: string;
    yesterday: string;
    earlier: string;
    archived: string;
    fallbackTitle: string;
  },
  options: {
    pinnedKeys: string[];
    archivedKeys: string[];
    titleOverrides: Record<string, string>;
    showArchived: boolean;
    sort: SidebarSortMode;
  },
): Array<{ label: string; sessions: ChatSummary[] }> {
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const startOfYesterday = startOfToday - 24 * 60 * 60 * 1000;
  const buckets = new Map<string, ChatSummary[]>();
  const pinned = new Set(options.pinnedKeys);
  const archived = new Set(options.archivedKeys);

  const pinnedSessions: ChatSummary[] = [];
  const archivedSessions: ChatSummary[] = [];
  const normalSessions: ChatSummary[] = [];

  for (const session of sessions) {
    if (archived.has(session.key)) {
      if (options.showArchived) archivedSessions.push(session);
      continue;
    }
    if (pinned.has(session.key)) {
      pinnedSessions.push(session);
      continue;
    }
    if (options.sort === "title_asc") {
      normalSessions.push(session);
      continue;
    }
    const timestamp = Date.parse(session.updatedAt ?? session.createdAt ?? "");
    const label = Number.isFinite(timestamp) && timestamp >= startOfToday
      ? labels.today
      : Number.isFinite(timestamp) && timestamp >= startOfYesterday
        ? labels.yesterday
        : labels.earlier;
    const bucket = buckets.get(label) ?? [];
    bucket.push(session);
    buckets.set(label, bucket);
  }

  const groups = [labels.today, labels.yesterday, labels.earlier]
    .map((label) => ({
      label,
      sessions: sortSessions(
        buckets.get(label) ?? [],
        options.sort,
        options.titleOverrides,
      ),
    }))
    .filter((group) => group.sessions.length > 0);
  if (options.sort === "title_asc" && normalSessions.length) {
    groups.push({
      label: labels.all,
      sessions: sortSessions(
        normalSessions,
        options.sort,
        options.titleOverrides,
      ),
    });
  }
  if (pinnedSessions.length) {
    groups.unshift({
      label: labels.pinned,
      sessions: sortSessions(
        pinnedSessions,
        options.sort,
        options.titleOverrides,
      ),
    });
  }
  if (archivedSessions.length) {
    groups.push({
      label: labels.archived,
      sessions: sortSessions(
        archivedSessions,
        options.sort,
        options.titleOverrides,
      ),
    });
  }
  return groups;
}

function sortSessions(
  sessions: ChatSummary[],
  sort: SidebarSortMode,
  titleOverrides: Record<string, string>,
): ChatSummary[] {
  const copy = [...sessions];
  copy.sort((a, b) => {
    if (sort === "title_asc") {
      const titleOrder = titleForSort(a, titleOverrides).localeCompare(
        titleForSort(b, titleOverrides),
        "en",
        { numeric: true, sensitivity: "base" },
      );
      if (titleOrder !== 0) return titleOrder;
      return sessionTime(b, "updatedAt") - sessionTime(a, "updatedAt");
    }
    const aTime = sessionTime(a, sort === "created_desc" ? "createdAt" : "updatedAt");
    const bTime = sessionTime(b, sort === "created_desc" ? "createdAt" : "updatedAt");
    return bTime - aTime;
  });
  return copy;
}

function titleForSort(
  session: ChatSummary,
  titleOverrides: Record<string, string>,
): string {
  return (
    titleOverrides[session.key]?.trim() ||
    session.title?.trim() ||
    deriveTitle(session.preview, "new chat")
  ).toLocaleLowerCase("en");
}

function displayTitle(
  session: ChatSummary,
  titleOverrides: Record<string, string>,
  fallbackTitle: string,
): string {
  return (
    titleOverrides[session.key]?.trim() ||
    session.title?.trim() ||
    deriveTitle(session.preview, fallbackTitle)
  );
}

function sessionTime(
  session: ChatSummary,
  field: "createdAt" | "updatedAt",
): number {
  const primary = Date.parse(session[field] ?? "");
  if (Number.isFinite(primary)) return primary;
  const fallback = Date.parse(session.updatedAt ?? session.createdAt ?? "");
  return Number.isFinite(fallback) ? fallback : 0;
}
