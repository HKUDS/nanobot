import {
  memo,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  Archive,
  ArchiveRestore,
  Folder,
  MoreHorizontal,
  Pencil,
  Pin,
  PinOff,
  Plus,
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
import {
  COLLAPSED_CHATS_VISIBLE_COUNT,
  displayTitle,
  groupSessions,
  isCollapsedProject,
  isFoldableChatsGroup,
  isFoldedChatsGroup,
  limitGroups,
  visibleSessionsForGroup,
  type ChatGroupLabels,
} from "@/lib/chat-groups";
import { cn } from "@/lib/utils";
import type { ChatSummary, SidebarDensity, SidebarSortMode } from "@/lib/types";

const INITIAL_VISIBLE_SESSIONS = 160;
const VISIBLE_SESSIONS_INCREMENT = 160;
const ACTION_MENU_CONTENT_CLASS = "w-[8.5rem] min-w-[8.5rem]";
const ACTION_MENU_ITEM_CLASS = "grid w-[7.75rem] grid-cols-[1rem_minmax(0,1fr)] items-center gap-2";

interface ChatListProps {
  sessions: ChatSummary[];
  activeKey: string | null;
  onSelect: (key: string) => void;
  onRequestDelete: (key: string, label: string) => void;
  onTogglePin: (key: string) => void;
  onRequestRename: (key: string, label: string) => void;
  onToggleArchive: (key: string) => void;
  onToggleGroup?: (groupId: string) => void;
  onRequestRenameProject?: (projectKey: string, label: string) => void;
  onNewChatInProject?: (projectPath: string, projectName: string) => void;
  pinnedKeys?: string[];
  archivedKeys?: string[];
  titleOverrides?: Record<string, string>;
  projectNameOverrides?: Record<string, string>;
  collapsedGroups?: Record<string, boolean>;
  runningChatIds?: string[];
  updatedChatIds?: string[];
  density?: SidebarDensity;
  showPreviews?: boolean;
  showTimestamps?: boolean;
  sort?: SidebarSortMode;
  showArchived?: boolean;
  defaultWorkspacePath?: string | null;
  actionMenuPortalContainer?: HTMLElement | null;
  loading?: boolean;
  emptyLabel?: string;
}

export const ChatList = memo(function ChatList({
  sessions,
  activeKey,
  onSelect,
  onRequestDelete,
  onTogglePin,
  onRequestRename,
  onToggleArchive,
  onToggleGroup,
  onRequestRenameProject,
  onNewChatInProject,
  pinnedKeys = [],
  archivedKeys = [],
  titleOverrides = {},
  projectNameOverrides = {},
  collapsedGroups = {},
  runningChatIds = [],
  updatedChatIds = [],
  density = "comfortable",
  showPreviews = false,
  showTimestamps = false,
  sort = "updated_desc",
  showArchived = false,
  defaultWorkspacePath,
  actionMenuPortalContainer,
  loading,
  emptyLabel,
}: ChatListProps) {
  const { t } = useTranslation();
  const [visibleLimit, setVisibleLimit] = useState(INITIAL_VISIBLE_SESSIONS);
  const labels = useMemo<ChatGroupLabels>(() => ({
    pinned: t("chat.groups.pinned"),
    all: t("chat.groups.all"),
    today: t("chat.groups.today"),
    yesterday: t("chat.groups.yesterday"),
    earlier: t("chat.groups.earlier"),
    archived: t("chat.groups.archived"),
    projects: t("chat.groups.projects"),
    fallbackTitle: t("chat.newChat"),
  }), [t]);
  const groups = useMemo(
    () => groupSessions(sessions, labels, {
      pinnedKeys,
      archivedKeys,
      titleOverrides,
      projectNameOverrides,
      showArchived,
      sort,
      defaultWorkspacePath,
    }),
    [
      archivedKeys,
      labels,
      pinnedKeys,
      sessions,
      showArchived,
      sort,
      titleOverrides,
      projectNameOverrides,
      defaultWorkspacePath,
    ],
  );
  const limitedGroups = useMemo(
    () => limitGroups(groups, visibleLimit, activeKey, collapsedGroups),
    [activeKey, collapsedGroups, groups, visibleLimit],
  );
  const totalSessionCount = useMemo(
    () => groups.reduce(
      (total, group) =>
        total + (isCollapsedProject(group, collapsedGroups) ? 0 : group.sessions.length),
      0,
    ),
    [collapsedGroups, groups],
  );
  const visibleSessionCount = useMemo(
    () => limitedGroups.reduce((total, group) => total + group.sessions.length, 0),
    [limitedGroups],
  );
  const hiddenSessionCount = Math.max(0, totalSessionCount - visibleSessionCount);

  useEffect(() => {
    setVisibleLimit(INITIAL_VISIBLE_SESSIONS);
  }, [showArchived, sort]);

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

  const pinned = new Set(pinnedKeys);
  const archived = new Set(archivedKeys);
  const running = new Set(runningChatIds);
  const updated = new Set(updatedChatIds);
  const compact = density === "compact";
  const firstProjectGroupIndex = limitedGroups.findIndex((group) => group.kind === "project");

  return (
    <div className="h-full min-h-0 min-w-0 overflow-x-hidden overflow-y-auto overscroll-contain scrollbar-thin scrollbar-track-transparent">
      <div className="min-w-0 space-y-3 px-2 py-1.5">
        {limitedGroups.map((group, index) => {
          const foldableChatsGroup = isFoldableChatsGroup(group);
          const foldedChatsGroup = isFoldedChatsGroup(group, collapsedGroups);
          const visibleSessions = visibleSessionsForGroup(
            group,
            activeKey,
            collapsedGroups,
          );
          const hiddenInGroup = Math.max(0, group.sessions.length - visibleSessions.length);
          const canToggleFold = group.sessions.length > COLLAPSED_CHATS_VISIBLE_COUNT;

          return (
            <section key={group.id} aria-label={group.label}>
              {index === firstProjectGroupIndex ? (
                <div className="px-2 pb-1 text-[12px] font-medium text-muted-foreground/65">
                  {labels.projects}
                </div>
              ) : null}
              {group.kind === "project" ? (
                <ProjectGroupHeader
                  label={group.label}
                  path={group.projectPath}
                  collapsed={Boolean(collapsedGroups[group.id])}
                  onToggle={() => onToggleGroup?.(group.id)}
                  onRequestRename={
                    group.projectKey && onRequestRenameProject
                      ? () => onRequestRenameProject(group.projectKey ?? "", group.label)
                      : undefined
                  }
                  onNewChat={
                    group.projectPath && onNewChatInProject
                      ? () => onNewChatInProject(group.projectPath ?? "", group.label)
                      : undefined
                  }
                  actionMenuPortalContainer={actionMenuPortalContainer}
                  updatedAt={showTimestamps ? group.updatedAt : null}
                />
              ) : (
                <ChatsGroupHeader label={group.label} />
              )}
              {group.kind === "project" && collapsedGroups[group.id] ? null : (
                <ul className="space-y-0.5">
                  {visibleSessions.map((s) => {
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
                    const projectMode = group.kind === "project";
                    const activityState = running.has(s.chatId)
                      ? "running"
                      : updated.has(s.chatId) && !active
                        ? "updated"
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
                              projectMode && "pl-7",
                            )}
                          >
                            {projectMode ? (
                              <span className="flex w-full min-w-0 items-baseline gap-2">
                                <span className="min-w-0 flex-1 truncate font-medium leading-5">
                                  {title}
                                </span>
                                {isPinned ? <PinnedChatIndicator label={labels.pinned} /> : null}
                                {timestamp ? (
                                  <span className="shrink-0 text-[11.5px] font-medium text-muted-foreground/58">
                                    {timestamp}
                                  </span>
                                ) : null}
                              </span>
                            ) : (
                              <span className="flex w-full min-w-0 items-center gap-1.5">
                                <span className="min-w-0 flex-1 truncate font-medium leading-5">
                                  {title}
                                </span>
                                {isPinned ? <PinnedChatIndicator label={labels.pinned} /> : null}
                              </span>
                            )}
                            {showPreview ? (
                              <span className="block w-full truncate text-[11.5px] leading-4 text-muted-foreground/72">
                                {preview}
                              </span>
                            ) : null}
                            {timestamp && !projectMode ? (
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
                              className={ACTION_MENU_CONTENT_CLASS}
                              portalContainer={actionMenuPortalContainer}
                              onCloseAutoFocus={(event) => event.preventDefault()}
                            >
                              <DropdownMenuItem
                                onSelect={() => onTogglePin(s.key)}
                                className={ACTION_MENU_ITEM_CLASS}
                              >
                                {isPinned ? (
                                  <PinOff className="h-4 w-4 shrink-0" />
                                ) : (
                                  <Pin className="h-4 w-4 shrink-0" />
                                )}
                                {isPinned ? t("chat.unpin") : t("chat.pin")}
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                onSelect={() => onRequestRename(s.key, title)}
                                className={ACTION_MENU_ITEM_CLASS}
                              >
                                <Pencil className="h-4 w-4 shrink-0" />
                                {t("chat.rename")}
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                onSelect={() => onToggleArchive(s.key)}
                                className={ACTION_MENU_ITEM_CLASS}
                              >
                                {isArchived ? (
                                  <ArchiveRestore className="h-4 w-4 shrink-0" />
                                ) : (
                                  <Archive className="h-4 w-4 shrink-0" />
                                )}
                                {isArchived ? t("chat.unarchive") : t("chat.archive")}
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                onSelect={() => {
                                  window.setTimeout(() => onRequestDelete(s.key, title), 0);
                                }}
                                className={cn(
                                  ACTION_MENU_ITEM_CLASS,
                                  "text-destructive focus:text-destructive",
                                )}
                              >
                                <Trash2 className="h-4 w-4 shrink-0" />
                                {t("chat.delete")}
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
              {foldableChatsGroup && canToggleFold ? (
                <ChatsFoldFooter
                  folded={foldedChatsGroup}
                  hiddenCount={hiddenInGroup}
                  onToggle={() => onToggleGroup?.(group.id)}
                />
              ) : null}
            </section>
          );
        })}
        {hiddenSessionCount > 0 ? (
          <div className="px-2 pb-2 pt-1">
            <button
              type="button"
              onClick={() =>
                setVisibleLimit((limit) =>
                  Math.min(totalSessionCount, limit + VISIBLE_SESSIONS_INCREMENT),
                )
              }
              className="h-8 w-full rounded-full text-[12px] font-medium text-muted-foreground/65 transition-colors hover:bg-sidebar-accent/65 hover:text-muted-foreground"
            >
              {t("chat.showMore", { count: hiddenSessionCount })}
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
});

function ProjectGroupHeader({
  label,
  path,
  collapsed,
  onToggle,
  onRequestRename,
  onNewChat,
  actionMenuPortalContainer,
  updatedAt,
}: {
  label: string;
  path?: string;
  collapsed: boolean;
  onToggle: () => void;
  onRequestRename?: () => void;
  onNewChat?: () => void;
  actionMenuPortalContainer?: HTMLElement | null;
  updatedAt?: string | null;
}) {
  const { t } = useTranslation();

  return (
    <div
      title={path}
      className="group flex min-w-0 items-center gap-1 px-1 pb-1 pt-1 text-[12px] font-medium text-muted-foreground/78"
    >
      <button
        type="button"
        aria-expanded={!collapsed}
        onClick={onToggle}
        className="flex min-w-0 flex-1 items-center gap-2 rounded-lg px-1.5 py-1 text-left transition-colors hover:bg-sidebar-accent/45 hover:text-sidebar-foreground"
      >
        <Folder className="h-3.5 w-3.5 shrink-0" aria-hidden />
        <span className="min-w-0 flex-1 truncate">{label}</span>
      </button>
      {updatedAt ? (
        <span className="shrink-0 text-[11px] text-muted-foreground/55">
          {relativeTime(updatedAt)}
        </span>
      ) : null}
      {onRequestRename ? (
        <DropdownMenu modal={false}>
          <DropdownMenuTrigger
            className={cn(
              "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground/70 opacity-40 transition-opacity",
              "hover:bg-sidebar-accent hover:text-sidebar-foreground group-hover:opacity-100 focus-visible:opacity-100",
            )}
            aria-label={t("chat.actions", { title: label })}
            onClick={(event) => event.stopPropagation()}
          >
            <MoreHorizontal className="h-3.5 w-3.5" />
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="end"
            className={ACTION_MENU_CONTENT_CLASS}
            portalContainer={actionMenuPortalContainer}
            onCloseAutoFocus={(event) => event.preventDefault()}
          >
            <DropdownMenuItem onSelect={onRequestRename} className={ACTION_MENU_ITEM_CLASS}>
              <Pencil className="h-4 w-4 shrink-0" />
              {t("chat.rename")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}
      {onNewChat ? (
        <button
          type="button"
          aria-label={t("chat.newInProject", { project: label })}
          title={t("chat.newInProject", { project: label })}
          onClick={(event) => {
            event.stopPropagation();
            onNewChat();
          }}
          className={cn(
            "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground/70 opacity-40 transition-opacity",
            "hover:bg-sidebar-accent hover:text-sidebar-foreground group-hover:opacity-100 focus-visible:opacity-100",
          )}
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
      ) : null}
    </div>
  );
}

function ChatsGroupHeader({ label }: { label: string }) {
  return (
    <div className="px-2 pb-1 text-[12px] font-medium text-muted-foreground/65">
      {label}
    </div>
  );
}

function PinnedChatIndicator({ label }: { label: string }) {
  return (
    <span
      aria-hidden="true"
      title={label}
      className="inline-flex shrink-0 items-center text-muted-foreground/65"
    >
      <Pin className="h-3.5 w-3.5" aria-hidden="true" />
    </span>
  );
}

function ChatsFoldFooter({
  folded,
  hiddenCount,
  onToggle,
}: {
  folded: boolean;
  hiddenCount: number;
  onToggle: () => void;
}) {
  const { t, i18n } = useTranslation();
  const collapsedFallback = i18n.resolvedLanguage?.startsWith("zh")
    ? `已折叠 ${hiddenCount} 个对话`
    : `${hiddenCount} hidden chats`;

  return (
    <div className="px-2 pb-1 pt-1">
      <button
        type="button"
        onClick={onToggle}
        className="h-7 w-full rounded-xl text-left text-[12px] font-medium text-muted-foreground/65 transition-colors hover:bg-sidebar-accent/50 hover:text-muted-foreground"
      >
        <span className="px-2">
          {folded
            ? t("chat.collapsed", {
                count: hiddenCount,
                defaultValue: collapsedFallback,
              })
            : t("chat.showLess")}
        </span>
      </button>
    </div>
  );
}

function SessionActivityIndicator({
  state,
}: {
  state: "running" | "updated" | null;
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

  if (state === "updated") {
    const label = t("chat.activity.updated");
    return (
      <span
        aria-label={label}
        title={label}
        className="grid h-4 w-4 shrink-0 place-items-center"
      >
        <span className="h-2 w-2 rounded-full bg-[#ff8a3d] shadow-[0_0_0_2px_rgba(255,138,61,0.16)]" />
      </span>
    );
  }

  return <span className="h-4 w-4 shrink-0" aria-hidden="true" />;
}
