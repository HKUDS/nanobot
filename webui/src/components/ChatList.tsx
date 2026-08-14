import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  Archive,
  ArchiveRestore,
  ChevronDown,
  Folder,
  ListChecks,
  MessageCircleDashed,
  MoreHorizontal,
  MoveRight,
  PanelsTopLeft,
  Pencil,
  Pin,
  PinOff,
  Plus,
  Square,
  SquareCheckBig,
  SquareMinus,
  Trash2,
  Ungroup,
  Unplug,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { MAX_WORKBENCH_PANES } from "@/components/workbench/workbench-model";
import { SIDEBAR_SELECTION_ITEM_CLASS } from "@/components/SidebarSelectionHighlight";
import { deriveTitle, relativeTime, visibleSessionPreview } from "@/lib/format";
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
import { deriveTemporaryChatTitle } from "@/lib/temporary-chat";
import { clearDraggedSession, writeDraggedSession } from "@/lib/session-drag";
import { cn } from "@/lib/utils";
import type { ChatSummary, SidebarDensity, SidebarSortMode } from "@/lib/types";

const INITIAL_VISIBLE_SESSIONS = 160;
const VISIBLE_SESSIONS_INCREMENT = 160;
const ACTION_MENU_CONTENT_CLASS = "w-[11rem] min-w-[11rem] whitespace-nowrap";
const COLLAPSED_PANE_GROUPS_STORAGE_KEY = "nanobot-webui.collapsed-pane-groups.v1";

function readCollapsedPaneGroups(): Set<string> {
  try {
    const value = JSON.parse(window.localStorage.getItem(
      COLLAPSED_PANE_GROUPS_STORAGE_KEY,
    ) ?? "[]") as unknown;
    return new Set(Array.isArray(value)
      ? value.filter((key): key is string => typeof key === "string")
      : []);
  } catch {
    return new Set();
  }
}

function writeCollapsedPaneGroups(groups: ReadonlySet<string>): void {
  try {
    window.localStorage.setItem(
      COLLAPSED_PANE_GROUPS_STORAGE_KEY,
      JSON.stringify(Array.from(groups)),
    );
  } catch {
    // Local UI preferences should not block the sidebar.
  }
}

interface PaneGroupTarget {
  key: string;
  title: string;
  paneCount: number;
  atCapacity: boolean;
}

export interface SidebarPaneGroup {
  tabKey: string;
  title: string;
  activePaneKey: string;
  visible?: boolean;
  panes: Array<{
    key: string;
    chatId: string;
    title: string;
  }>;
}

export interface SidebarDeleteItem {
  key: string;
  label: string;
}

interface ChatListProps {
  sessions: ChatSummary[];
  temporarySessions?: ChatSummary[];
  activeKey: string | null;
  onSelect: (key: string) => void;
  onCloseTemporaryChat?: (key: string) => void;
  onRequestDelete: (key: string, label: string) => void;
  onRequestDeleteMany?: (items: SidebarDeleteItem[]) => void;
  onTogglePin: (key: string) => void;
  onRequestRename: (key: string, label: string) => void;
  onRequestRenameTab?: (key: string, label: string) => void;
  onToggleArchive: (key: string) => void;
  paneGroups?: Record<string, SidebarPaneGroup>;
  onSelectPane?: (tabKey: string, paneKey: string) => void;
  onCreateTab?: (paneKey: string) => void;
  onDetachPane?: (tabKey: string, paneKey: string) => void;
  onDissolveTab?: (tabKey: string) => void;
  onAttachPane?: (
    paneKey: string,
    tabKey: string,
  ) => void;
  onToggleGroup?: (groupId: string) => void;
  onRequestRenameProject?: (projectKey: string, label: string) => void;
  onNewChatInProject?: (projectPath: string, projectName: string) => void;
  pinnedKeys?: string[];
  archivedKeys?: string[];
  pinnedPaneKeys?: string[];
  archivedPaneKeys?: string[];
  sessionOrder?: string[];
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
  temporarySessions = [],
  activeKey,
  onSelect,
  onCloseTemporaryChat,
  onRequestDelete,
  onRequestDeleteMany,
  onTogglePin,
  onRequestRename,
  onRequestRenameTab,
  onToggleArchive,
  paneGroups = {},
  onSelectPane,
  onCreateTab,
  onDetachPane,
  onDissolveTab,
  onAttachPane,
  onToggleGroup,
  onRequestRenameProject,
  onNewChatInProject,
  pinnedKeys = [],
  archivedKeys = [],
  pinnedPaneKeys = [],
  archivedPaneKeys = [],
  sessionOrder = [],
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
  const tabRowRefs = useRef(new Map<string, HTMLLIElement>());
  const pendingTabRectsRef = useRef<Map<string, DOMRect> | null>(null);
  const tabLayoutAnimationsRef = useRef(new Map<string, Animation>());
  const [collapsedPaneGroups, setCollapsedPaneGroups] = useState<Set<string>>(
    readCollapsedPaneGroups,
  );
  const [deleteSelectionMode, setDeleteSelectionMode] = useState(false);
  const [selectedDeleteKeys, setSelectedDeleteKeys] = useState<Set<string>>(
    () => new Set(),
  );
  const deleteItemsByKey = useMemo(() => {
    const items = new Map<string, SidebarDeleteItem>();
    for (const group of Object.values(paneGroups)) {
      for (const pane of group.panes) {
        items.set(pane.key, { key: pane.key, label: pane.title });
      }
    }
    for (const session of sessions) {
      if (items.has(session.key)) continue;
      items.set(session.key, {
        key: session.key,
        label: displayTitle(session, titleOverrides, t("chat.newChat")),
      });
    }
    return items;
  }, [paneGroups, sessions, t, titleOverrides]);
  const paneGroupTargets = useMemo(() => Array.from(new Map(
    Object.values(paneGroups)
      .filter((group) => group.visible ?? group.panes.length > 1)
      .map((group) => [group.tabKey, {
        key: group.tabKey,
        title: group.title,
        paneCount: group.panes.length,
        atCapacity: group.panes.length >= MAX_WORKBENCH_PANES,
      }]),
  ).values()), [paneGroups]);
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
      sessionOrder,
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
      sessionOrder,
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
  const pinned = useMemo(() => new Set(pinnedKeys), [pinnedKeys]);
  const archived = useMemo(() => new Set(archivedKeys), [archivedKeys]);
  const pinnedPanes = useMemo(() => new Set(pinnedPaneKeys), [pinnedPaneKeys]);
  const archivedPanes = useMemo(() => new Set(archivedPaneKeys), [archivedPaneKeys]);
  const hiddenSessionCount = Math.max(0, totalSessionCount - visibleSessionCount);

  useEffect(() => {
    setVisibleLimit(INITIAL_VISIBLE_SESSIONS);
  }, [showArchived, sort]);

  useEffect(() => {
    if (!deleteSelectionMode) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setDeleteSelectionMode(false);
      setSelectedDeleteKeys(new Set());
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [deleteSelectionMode]);

  useEffect(() => {
    writeCollapsedPaneGroups(collapsedPaneGroups);
  }, [collapsedPaneGroups]);

  useEffect(() => {
    if (loading) return;
    setCollapsedPaneGroups((current) => {
      const next = new Set(Array.from(current).filter((key) => (
        paneGroups[key]?.visible ?? ((paneGroups[key]?.panes.length ?? 0) > 1)
      )));
      if (next.size === current.size && Array.from(next).every((key) => current.has(key))) {
        return current;
      }
      return next;
    });
  }, [loading, paneGroups]);

  const measureTabRows = useCallback(() => {
    const rects = new Map<string, DOMRect>();
    for (const [key, row] of tabRowRefs.current) {
      rects.set(key, row.getBoundingClientRect());
    }
    return rects;
  }, []);

  const captureTabLayout = useCallback(() => {
    for (const animation of tabLayoutAnimationsRef.current.values()) animation.cancel();
    tabLayoutAnimationsRef.current.clear();
    pendingTabRectsRef.current = measureTabRows();
  }, [measureTabRows]);

  const togglePaneGroup = useCallback((key: string) => {
    captureTabLayout();
    setCollapsedPaneGroups((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, [captureTabLayout]);

  useLayoutEffect(() => {
    const previousRects = pendingTabRectsRef.current;
    if (!previousRects) return;
    pendingTabRectsRef.current = null;
    const nextRects = measureTabRows();
    const reduceMotion = typeof window.matchMedia === "function"
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) return;
    for (const [key, nextRect] of nextRects) {
      const previousRect = previousRects.get(key);
      const row = tabRowRefs.current.get(key);
      if (!previousRect || !row || typeof row.animate !== "function") continue;
      const deltaY = previousRect.top - nextRect.top;
      if (Math.abs(deltaY) < 0.5) continue;
      const animation = row.animate(
        [
          { transform: `translateY(${deltaY}px)` },
          { transform: "translateY(0)" },
        ],
        {
          duration: 180,
          easing: "cubic-bezier(0.2, 0, 0, 1)",
        },
      );
      tabLayoutAnimationsRef.current.set(key, animation);
      animation.addEventListener("finish", () => {
        if (tabLayoutAnimationsRef.current.get(key) === animation) {
          tabLayoutAnimationsRef.current.delete(key);
        }
      }, { once: true });
    }
  }, [collapsedPaneGroups, measureTabRows]);

  useEffect(() => () => {
    for (const animation of tabLayoutAnimationsRef.current.values()) animation.cancel();
  }, []);

  if (loading && sessions.length === 0 && temporarySessions.length === 0) {
    return (
      <div className="px-3 py-6 text-[12px] text-muted-foreground">
        {t("chat.loading")}
      </div>
    );
  }

  if (sessions.length === 0 && temporarySessions.length === 0) {
    return (
      <div className="px-3 py-6 text-[12px] leading-5 text-muted-foreground/80">
        {emptyLabel ?? t("chat.noSessions")}
      </div>
    );
  }

  const running = new Set(runningChatIds);
  const updated = new Set(updatedChatIds);
  const compact = density === "compact";
  const firstProjectGroupIndex = limitedGroups.findIndex((group) => group.kind === "project");

  const beginDeleteSelection = (keys: string[]) => {
    setDeleteSelectionMode(true);
    setSelectedDeleteKeys(new Set(keys.filter((key) => deleteItemsByKey.has(key))));
  };
  const toggleDeleteSelection = (keys: string[]) => {
    setSelectedDeleteKeys((current) => {
      const next = new Set(current);
      const validKeys = keys.filter((key) => deleteItemsByKey.has(key));
      const remove = validKeys.length > 0 && validKeys.every((key) => next.has(key));
      for (const key of validKeys) {
        if (remove) next.delete(key);
        else next.add(key);
      }
      return next;
    });
  };
  const closeDeleteSelection = () => {
    setDeleteSelectionMode(false);
    setSelectedDeleteKeys(new Set());
  };
  const requestDeleteItems = (items: SidebarDeleteItem[]) => {
    if (items.length === 0) return;
    if (onRequestDeleteMany) onRequestDeleteMany(items);
    else if (items.length === 1) onRequestDelete(items[0].key, items[0].label);
  };
  const requestDeleteKeys = (keys: string[]) => {
    requestDeleteItems(keys
      .map((key) => deleteItemsByKey.get(key))
      .filter((item): item is SidebarDeleteItem => item !== undefined));
  };
  const confirmDeleteSelection = () => {
    requestDeleteKeys(Array.from(selectedDeleteKeys));
    closeDeleteSelection();
  };
  return (
    <div className="h-full min-h-0 min-w-0 overflow-x-hidden overflow-y-auto overscroll-contain scrollbar-thin scrollbar-track-transparent">
      <div
        data-chat-list-content
        className="relative min-w-0 space-y-3 px-2 py-1.5"
      >
        {temporarySessions.length > 0 ? (
          <TemporaryChatSection
            sessions={temporarySessions}
            activeKey={activeKey}
            running={running}
            onSelect={onSelect}
            onClose={onCloseTemporaryChat}
          />
        ) : null}
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
            <section key={group.id} aria-label={group.label} className="relative z-[1]">
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
                    const topicActive = s.key === activeKey;
                    const paneGroup = paneGroups[s.key];
                    const title = displayTitle(s, titleOverrides, t("chat.newChat"));
                    const resolvedPaneGroup = paneGroup ?? {
                      tabKey: s.key,
                      title,
                      activePaneKey: s.key,
                      panes: [{ key: s.key, chatId: s.chatId, title }],
                    };
                    const isWorkbenchTab = paneGroup?.visible
                      ?? ((paneGroup?.panes.length ?? 0) > 1);
                    const paneGroupCollapsed = isWorkbenchTab
                      && collapsedPaneGroups.has(s.key);
                    const paneGroupId = `sidebar-pane-group-${s.key.replace(
                      /[^a-zA-Z0-9_-]/g,
                      "-",
                    )}`;
                    const tabDeleteKeys = resolvedPaneGroup.panes.map((pane) => pane.key);
                    const tabSelected = tabDeleteKeys.every((key) => (
                      selectedDeleteKeys.has(key)
                    ));
                    const tabPartiallySelected = !tabSelected && tabDeleteKeys.some((key) => (
                      selectedDeleteKeys.has(key)
                    ));
                    const projectMode = group.kind === "project";

                    if (isWorkbenchTab) {
                      return (
                        <li
                          key={s.key}
                          ref={(element) => {
                            if (element) tabRowRefs.current.set(s.key, element);
                            else tabRowRefs.current.delete(s.key);
                          }}
                          data-sidebar-tab-group="true"
                          data-pane-group-collapsed={paneGroupCollapsed ? "true" : undefined}
                          className="relative my-1.5 min-w-0"
                        >
                          <div
                            data-workbench-tab-surface
                            className={cn(
                              "-mx-2 min-w-0 bg-sidebar-foreground/[0.045] px-3 dark:bg-white/[0.07]",
                              paneGroupCollapsed ? "py-0" : "py-1",
                              deleteSelectionMode && (tabSelected || tabPartiallySelected)
                                && "ring-1 ring-inset ring-sidebar-foreground/25",
                            )}
                          >
                            <div className={cn("min-w-0", projectMode && "ps-7")}>
                              <WorkbenchTabHeader
                                title={title}
                                controlsId={paneGroupId}
                                collapsed={paneGroupCollapsed}
                                deleteSelectionMode={deleteSelectionMode}
                                selected={tabSelected}
                                partiallySelected={tabPartiallySelected}
                                onToggle={() => togglePaneGroup(s.key)}
                                onToggleSelection={() => toggleDeleteSelection(tabDeleteKeys)}
                                onRequestRename={onRequestRenameTab
                                  ? () => onRequestRenameTab(s.key, title)
                                  : undefined}
                                onDissolve={onDissolveTab
                                  ? () => onDissolveTab(resolvedPaneGroup.tabKey)
                                  : undefined}
                                onRequestDelete={() => requestDeleteKeys(tabDeleteKeys)}
                                actionMenuPortalContainer={actionMenuPortalContainer}
                              />
                              {!paneGroupCollapsed ? (
                                <ActivePaneRows
                                  id={paneGroupId}
                                  group={resolvedPaneGroup}
                                  tabTitle={title}
                                  tabActive={topicActive}
                                  compact={compact}
                                  running={running}
                                  updated={updated}
                                  onSelectPane={onSelectPane}
                                  onRequestDelete={onRequestDelete}
                                  onRequestRename={onRequestRename}
                                  onTogglePin={onTogglePin}
                                  onToggleArchive={onToggleArchive}
                                  pinned={pinnedPanes}
                                  archived={archivedPanes}
                                  onDetachPane={onDetachPane}
                                  moveTargets={paneGroupTargets.filter((target) => (
                                    target.key !== resolvedPaneGroup.tabKey
                                  ))}
                                  onAttachPane={onAttachPane}
                                  deleteSelectionMode={deleteSelectionMode}
                                  selectedDeleteKeys={selectedDeleteKeys}
                                  onToggleDeleteSelection={toggleDeleteSelection}
                                  onBeginDeleteSelection={beginDeleteSelection}
                                  actionMenuPortalContainer={actionMenuPortalContainer}
                                />
                              ) : null}
                            </div>
                          </div>
                        </li>
                      );
                    }

                    const fallbackTitle = t("chat.fallbackTitle", {
                      id: s.chatId.slice(0, 6),
                    });
                    const generatedTitle = s.title?.trim() || "";
                    const tooltipTitle =
                      titleOverrides[s.key]?.trim() ||
                      generatedTitle ||
                      deriveTitle(s.preview, fallbackTitle);
                    const isPinned = pinned.has(s.key);
                    const isArchived = archived.has(s.key);
                    const preview = visibleSessionPreview(s.preview);
                    const showPreview = showPreviews && preview && preview !== title;
                    const timestamp = showTimestamps
                      ? relativeTime(s.updatedAt ?? s.createdAt)
                      : "";
                    const activityState = running.has(s.chatId)
                      ? "running"
                      : updated.has(s.chatId) && !topicActive
                        ? "updated"
                        : null;
                    const canDragSession = !topicActive && !deleteSelectionMode;
                    return (
                      <li
                        key={s.key}
                        ref={(element) => {
                          if (element) tabRowRefs.current.set(s.key, element);
                          else tabRowRefs.current.delete(s.key);
                        }}
                        className="relative min-w-0"
                      >
                        <div
                          data-chat-row={s.key}
                          data-sidebar-tab={s.key}
                          className={cn(
                            "group flex min-w-0 max-w-full items-center gap-1 rounded-[0.65rem] px-2 text-[13px]",
                            SIDEBAR_SELECTION_ITEM_CLASS,
                            compact ? "min-h-7" : "min-h-8",
                            topicActive
                              ? "bg-sidebar-selected text-sidebar-accent-foreground"
                              : "text-sidebar-foreground/82 hover:bg-sidebar-foreground/[0.075] hover:text-sidebar-foreground dark:hover:bg-white/[0.09]",
                            deleteSelectionMode && (tabSelected || tabPartiallySelected)
                              && "bg-sidebar-accent/55 text-sidebar-accent-foreground",
                          )}
                        >
                          <button
                            type="button"
                            onClick={() => {
                              if (deleteSelectionMode) {
                                toggleDeleteSelection(tabDeleteKeys);
                                return;
                              }
                              if (!topicActive) onSelect(s.key);
                            }}
                            draggable={canDragSession}
                            onDragStart={(event) => {
                              if (!canDragSession) {
                                event.preventDefault();
                                return;
                              }
                              writeDraggedSession(event.dataTransfer, s.key);
                            }}
                            onDragEnd={clearDraggedSession}
                            aria-current={topicActive ? "page" : undefined}
                            aria-pressed={deleteSelectionMode ? tabSelected : undefined}
                            title={tooltipTitle}
                            className={cn(
                              "flex min-w-0 flex-1 items-center gap-2 overflow-hidden text-left",
                              canDragSession && "cursor-grab active:cursor-grabbing",
                              deleteSelectionMode && "cursor-default",
                              compact ? "py-1" : "py-1.5",
                              projectMode && "pl-7",
                            )}
                          >
                            {deleteSelectionMode ? (
                              <SelectionIndicator
                                checked={tabSelected}
                                partial={tabPartiallySelected}
                              />
                            ) : null}
                            <span className="min-w-0 flex-1 overflow-hidden">
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
                            </span>
                          </button>
                          <SessionActivityIndicator state={activityState} />
                          {!deleteSelectionMode ? (
                            <DropdownMenu modal={false}>
                            <DropdownMenuTrigger
                              className={cn(
                                "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground/75 opacity-0 transition-opacity",
                                "hover:bg-sidebar-accent hover:text-sidebar-foreground group-hover:opacity-100",
                                "focus-visible:opacity-100 data-[state=open]:opacity-100",
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
                              <DropdownMenuItem onSelect={() => onTogglePin(s.key)}>
                                {isPinned ? (
                                  <PinOff className="h-4 w-4 shrink-0" />
                                ) : (
                                  <Pin className="h-4 w-4 shrink-0" />
                                )}
                                {isPinned ? t("chat.unpin") : t("chat.pin")}
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                onSelect={() => onRequestRename(s.key, title)}
                              >
                                <Pencil className="h-4 w-4 shrink-0" />
                                {t("chat.rename")}
                              </DropdownMenuItem>
                              <DropdownMenuItem onSelect={() => onToggleArchive(s.key)}>
                                {isArchived ? (
                                  <ArchiveRestore className="h-4 w-4 shrink-0" />
                                ) : (
                                  <Archive className="h-4 w-4 shrink-0" />
                                )}
                                {isArchived ? t("chat.unarchive") : t("chat.archive")}
                              </DropdownMenuItem>
                              {paneGroup && onCreateTab ? (
                                <DropdownMenuItem onSelect={() => onCreateTab(s.key)}>
                                  <PanelsTopLeft className="h-4 w-4 shrink-0" aria-hidden />
                                  {t("workbench.createGroup", {
                                    defaultValue: "Create group",
                                  })}
                                </DropdownMenuItem>
                              ) : null}
                              {paneGroup && onAttachPane ? (
                                <MoveToGroupSubmenu
                                  targets={paneGroupTargets.filter((target) => (
                                    target.key !== paneGroup.tabKey
                                  ))}
                                  onMove={(targetKey) => onAttachPane(s.key, targetKey)}
                                />
                              ) : null}
                              <DropdownMenuItem
                                onSelect={() => beginDeleteSelection(tabDeleteKeys)}
                              >
                                <ListChecks className="h-4 w-4 shrink-0" />
                                {t("chat.select", { defaultValue: "Select" })}
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                tone="destructive"
                                onSelect={() => {
                                  window.setTimeout(() => requestDeleteKeys(tabDeleteKeys), 0);
                                }}
                              >
                                <Trash2 className="h-4 w-4 shrink-0" />
                                {t("chat.delete")}
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
          <div className="relative z-[1] px-2 pb-2 pt-1">
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
        {deleteSelectionMode ? (
          <div
            data-testid="delete-selection-bar"
            className="sticky bottom-2 z-30 mx-1 mt-3 flex min-h-11 items-center gap-2 rounded-2xl border border-sidebar-border/80 bg-popover/95 p-1.5 pl-2 shadow-[0_10px_30px_rgba(15,23,42,0.14)] backdrop-blur-xl"
          >
            <button
              type="button"
              onClick={closeDeleteSelection}
              aria-label={t("chat.cancelSelection", {
                defaultValue: "Cancel selection",
              })}
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-accent/60 hover:text-foreground"
            >
              <X className="h-4 w-4" aria-hidden />
            </button>
            <span className="min-w-0 flex-1 truncate px-1 text-[12.5px] font-medium text-foreground/85">
              {t("chat.selectedCount", {
                defaultValue: "{{count}} selected",
                count: selectedDeleteKeys.size,
              })}
            </span>
            <button
              type="button"
              disabled={selectedDeleteKeys.size === 0}
              onClick={confirmDeleteSelection}
              className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full bg-destructive px-3 text-[12px] font-semibold text-destructive-foreground transition-colors hover:bg-destructive/90 disabled:pointer-events-none disabled:opacity-40"
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden />
              {t("chat.deleteSelected", { defaultValue: "Delete" })}
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
});

function WorkbenchTabHeader({
  title,
  controlsId,
  collapsed,
  deleteSelectionMode,
  selected,
  partiallySelected,
  onToggle,
  onToggleSelection,
  onRequestRename,
  onDissolve,
  onRequestDelete,
  actionMenuPortalContainer,
}: {
  title: string;
  controlsId: string;
  collapsed: boolean;
  deleteSelectionMode: boolean;
  selected: boolean;
  partiallySelected: boolean;
  onToggle: () => void;
  onToggleSelection: () => void;
  onRequestRename?: () => void;
  onDissolve?: () => void;
  onRequestDelete: () => void;
  actionMenuPortalContainer?: HTMLElement | null;
}) {
  const { t } = useTranslation();
  const disclosureLabel = t(
    collapsed ? "workbench.expandTabGroup" : "workbench.collapseTabGroup",
    { title },
  );

  return (
    <div
      data-workbench-tab
      className={cn(
        "group/tab flex min-w-0 items-center gap-0.5 rounded-[0.65rem] px-1.5 text-sidebar-foreground/85",
        collapsed ? "min-h-6" : "min-h-7",
      )}
    >
      <button
        type="button"
        onClick={deleteSelectionMode ? onToggleSelection : onToggle}
        draggable={false}
        aria-label={t("workbench.tabAria", { title })}
        aria-expanded={deleteSelectionMode ? undefined : !collapsed}
        aria-controls={deleteSelectionMode ? undefined : controlsId}
        aria-pressed={deleteSelectionMode ? selected : undefined}
        title={title}
        className={cn(
          "flex min-w-0 flex-1 items-center gap-2 overflow-hidden px-0.5 py-1 text-left",
          "text-[12.5px] font-normal leading-5",
          deleteSelectionMode && "cursor-default",
        )}
      >
        {deleteSelectionMode ? (
          <SelectionIndicator checked={selected} partial={partiallySelected} />
        ) : null}
        <span className="min-w-0 flex-1 truncate">{title}</span>
      </button>
      {!deleteSelectionMode ? (
        <>
          <DropdownMenu modal={false}>
            <DropdownMenuTrigger
              className={cn(
                "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md",
                "text-muted-foreground/75 opacity-0 transition-opacity",
                "hover:bg-sidebar-accent hover:text-sidebar-foreground group-hover/tab:opacity-100",
                "focus-visible:opacity-100 data-[state=open]:opacity-100",
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
              {onRequestRename ? (
                <DropdownMenuItem onSelect={onRequestRename}>
                  <Pencil className="h-4 w-4 shrink-0" />
                  {t("chat.rename")}
                </DropdownMenuItem>
              ) : null}
              {onDissolve ? (
                <DropdownMenuItem onSelect={onDissolve}>
                  <Ungroup className="h-4 w-4 shrink-0" />
                  {t("workbench.dissolveTab", { defaultValue: "Dissolve group" })}
                </DropdownMenuItem>
              ) : null}
              <DropdownMenuItem
                tone="destructive"
                onSelect={() => window.setTimeout(onRequestDelete, 0)}
                className="whitespace-nowrap"
              >
                <Trash2 className="h-4 w-4 shrink-0" />
                {t("workbench.deleteConversations", {
                  defaultValue: "Delete all chats",
                })}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <button
            type="button"
            aria-expanded={!collapsed}
            aria-controls={controlsId}
            aria-label={disclosureLabel}
            title={disclosureLabel}
            onClick={onToggle}
            className={cn(
              "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md",
              "text-muted-foreground/70 transition-[background-color,color,transform] duration-150 ease-out",
              "hover:bg-sidebar-accent hover:text-sidebar-foreground active:scale-[0.96]",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60",
              "motion-reduce:transition-none motion-reduce:active:scale-100",
            )}
          >
            <ChevronDown
              aria-hidden
              className={cn(
                "h-3.5 w-3.5 transition-transform duration-200 ease-out motion-reduce:transition-none",
                !collapsed && "rotate-180",
              )}
            />
          </button>
        </>
      ) : null}
    </div>
  );
}

function ActivePaneRows({
  id,
  group,
  tabTitle,
  tabActive,
  compact,
  running,
  updated,
  onSelectPane,
  onRequestDelete,
  onRequestRename,
  onTogglePin,
  onToggleArchive,
  pinned,
  archived,
  onDetachPane,
  moveTargets,
  onAttachPane,
  deleteSelectionMode,
  selectedDeleteKeys,
  onToggleDeleteSelection,
  onBeginDeleteSelection,
  actionMenuPortalContainer,
}: {
  id: string;
  group: SidebarPaneGroup;
  tabTitle: string;
  tabActive: boolean;
  compact: boolean;
  running: ReadonlySet<string>;
  updated: ReadonlySet<string>;
  onSelectPane?: (tabKey: string, paneKey: string) => void;
  onRequestDelete: (key: string, label: string) => void;
  onRequestRename: (key: string, label: string) => void;
  onTogglePin: (key: string) => void;
  onToggleArchive: (key: string) => void;
  pinned: ReadonlySet<string>;
  archived: ReadonlySet<string>;
  onDetachPane?: (tabKey: string, paneKey: string) => void;
  moveTargets: PaneGroupTarget[];
  onAttachPane?: (
    paneKey: string,
    tabKey: string,
  ) => void;
  deleteSelectionMode: boolean;
  selectedDeleteKeys: ReadonlySet<string>;
  onToggleDeleteSelection: (keys: string[]) => void;
  onBeginDeleteSelection: (keys: string[]) => void;
  actionMenuPortalContainer?: HTMLElement | null;
}) {
  const { t } = useTranslation();
  const panes = group.panes;
  return (
    <ul
      id={id}
      aria-label={t("workbench.panesInTab", {
        defaultValue: "Panes in {{title}}",
        title: tabTitle,
      })}
      className="mt-0.5 space-y-0.5"
    >
      {panes.map((pane) => {
        const active = tabActive && pane.key === group.activePaneKey;
        const activityState = running.has(pane.chatId)
          ? "running"
          : updated.has(pane.chatId) && !active
            ? "updated"
            : null;
        const paneActionsLabel = t("workbench.paneActions", {
          defaultValue: "{{title}} pane actions",
          title: pane.title,
        });
        const selected = selectedDeleteKeys.has(pane.key);
        const isPinned = pinned.has(pane.key);
        const isArchived = archived.has(pane.key);
        const canDragSession = !active && !deleteSelectionMode;

        return (
          <li
            key={pane.key}
            className="relative min-w-0"
          >
            <div
              data-chat-row={pane.key}
              data-sidebar-pane={pane.key}
              className={cn(
                "group/pane flex min-w-0 max-w-full items-center gap-1 rounded-[0.65rem] px-2 text-[13px]",
                SIDEBAR_SELECTION_ITEM_CLASS,
                compact ? "min-h-7" : "min-h-8",
                active
                  ? "bg-sidebar-selected text-sidebar-accent-foreground"
                  : "text-sidebar-foreground/82 hover:bg-sidebar-foreground/[0.075] hover:text-sidebar-foreground dark:hover:bg-white/[0.09]",
                deleteSelectionMode && selected
                  && "bg-sidebar-accent/55 text-sidebar-accent-foreground",
              )}
            >
              <button
                type="button"
                onClick={() => {
                  if (deleteSelectionMode) {
                    onToggleDeleteSelection([pane.key]);
                    return;
                  }
                  onSelectPane?.(group.tabKey, pane.key);
                }}
                draggable={canDragSession}
                onDragStart={(event) => {
                  if (!canDragSession) {
                    event.preventDefault();
                    return;
                  }
                  writeDraggedSession(event.dataTransfer, pane.key);
                }}
                onDragEnd={clearDraggedSession}
                aria-current={active ? "true" : undefined}
                aria-pressed={deleteSelectionMode ? selected : undefined}
                title={pane.title}
                className={cn(
                  "flex min-w-0 flex-1 items-center gap-2 overflow-hidden text-left font-medium leading-5",
                  canDragSession && "cursor-grab active:cursor-grabbing",
                  compact ? "py-1" : "py-1.5",
                  deleteSelectionMode && "cursor-default",
                )}
              >
                {deleteSelectionMode ? (
                  <SelectionIndicator checked={selected} partial={false} />
                ) : null}
                <span className="min-w-0 flex-1 truncate">{pane.title}</span>
                {isPinned ? <PinnedChatIndicator label={t("chat.groups.pinned")} /> : null}
              </button>
              <SessionActivityIndicator state={activityState} />
              {!deleteSelectionMode ? <DropdownMenu modal={false}>
                <DropdownMenuTrigger
                  className={cn(
                    "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground/70 opacity-0 transition-opacity",
                    "hover:bg-sidebar-accent hover:text-sidebar-foreground group-hover/pane:opacity-100",
                    "focus-visible:opacity-100 data-[state=open]:opacity-100",
                  )}
                  aria-label={paneActionsLabel}
                >
                  <MoreHorizontal className="h-3.5 w-3.5" />
                </DropdownMenuTrigger>
                <DropdownMenuContent
                  align="end"
                  className={ACTION_MENU_CONTENT_CLASS}
                  portalContainer={actionMenuPortalContainer}
                  onCloseAutoFocus={(event) => event.preventDefault()}
                >
                  <DropdownMenuItem onSelect={() => onTogglePin(pane.key)}>
                    {isPinned ? (
                      <PinOff className="h-4 w-4 shrink-0" />
                    ) : (
                      <Pin className="h-4 w-4 shrink-0" />
                    )}
                    {isPinned ? t("chat.unpin") : t("chat.pin")}
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onSelect={() => onRequestRename(pane.key, pane.title)}
                  >
                    <Pencil className="h-4 w-4 shrink-0" />
                    {t("chat.rename")}
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => onToggleArchive(pane.key)}>
                    {isArchived ? (
                      <ArchiveRestore className="h-4 w-4 shrink-0" />
                    ) : (
                      <Archive className="h-4 w-4 shrink-0" />
                    )}
                    {isArchived ? t("chat.unarchive") : t("chat.archive")}
                  </DropdownMenuItem>
                  {onDetachPane ? (
                    <DropdownMenuItem onSelect={() => onDetachPane(group.tabKey, pane.key)}>
                      <Unplug className="h-4 w-4 shrink-0" />
                      {t("workbench.detachPane", {
                        defaultValue: "Remove",
                        title: pane.title,
                      })}
                    </DropdownMenuItem>
                  ) : null}
                  {onAttachPane ? (
                    <MoveToGroupSubmenu
                      targets={moveTargets}
                      onMove={(targetKey) => onAttachPane(pane.key, targetKey)}
                    />
                  ) : null}
                  <DropdownMenuItem
                    onSelect={() => onBeginDeleteSelection([pane.key])}
                  >
                    <ListChecks className="h-4 w-4 shrink-0" />
                    {t("chat.select", { defaultValue: "Select" })}
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    tone="destructive"
                    onSelect={() => {
                      window.setTimeout(() => onRequestDelete(pane.key, pane.title), 0);
                    }}
                  >
                    <Trash2 className="h-4 w-4 shrink-0" />
                    {t("chat.delete")}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu> : null}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function SelectionIndicator({
  checked,
  partial,
}: {
  checked: boolean;
  partial: boolean;
}) {
  const Icon = partial ? SquareMinus : checked ? SquareCheckBig : Square;
  return (
    <Icon
      aria-hidden
      className={cn(
        "h-4 w-4 shrink-0",
        checked || partial ? "text-primary" : "text-muted-foreground/55",
      )}
    />
  );
}

function MoveToGroupSubmenu({
  targets,
  onMove,
}: {
  targets: PaneGroupTarget[];
  onMove: (targetKey: string) => void;
}) {
  const { t } = useTranslation();
  if (targets.length === 0) return null;
  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger>
        <MoveRight className="h-4 w-4 shrink-0" aria-hidden />
        {t("workbench.moveTo", { defaultValue: "Move to" })}
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent>
        {targets.map((target) => (
          <DropdownMenuItem
            key={target.key}
            disabled={target.atCapacity}
            onSelect={() => onMove(target.key)}
          >
            <span className="min-w-0 max-w-56 flex-1 truncate">{target.title}</span>
            <span className="shrink-0 tabular-nums text-muted-foreground/70">
              · {target.paneCount}/{MAX_WORKBENCH_PANES}
            </span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  );
}

function TemporaryChatSection({
  sessions,
  activeKey,
  running,
  onSelect,
  onClose,
}: {
  sessions: ChatSummary[];
  activeKey: string | null;
  running: ReadonlySet<string>;
  onSelect: (key: string) => void;
  onClose?: (key: string) => void;
}) {
  const { t } = useTranslation();

  return (
    <section aria-label={t("temporaryChat.sectionTitle")} className="relative z-[1]">
      <ChatsGroupHeader label={t("temporaryChat.sectionTitle")} />
      <ul className="space-y-0.5">
        {sessions.map((session) => {
          const active = session.key === activeKey;
          const title = deriveTemporaryChatTitle(session.preview, t("temporaryChat.title"));
          return (
            <li key={session.key} className="min-w-0">
              <div
                data-temporary-chat-row={session.key}
                className={cn(
                  "group flex min-h-8 min-w-0 max-w-full items-center gap-2 rounded-xl px-2 text-[13px]",
                  SIDEBAR_SELECTION_ITEM_CLASS,
                  active
                    ? "bg-sidebar-selected text-sidebar-accent-foreground"
                    : "text-sidebar-foreground/82 hover:bg-sidebar-foreground/[0.035] hover:text-sidebar-foreground dark:hover:bg-white/[0.05]",
                )}
              >
                <button
                  type="button"
                  onClick={() => onSelect(session.key)}
                  aria-current={active ? "page" : undefined}
                  title={title}
                  className="flex min-w-0 flex-1 items-center gap-2 overflow-hidden py-1.5 text-left"
                >
                  <MessageCircleDashed
                    className="h-3.5 w-3.5 shrink-0 text-[hsl(var(--temporary-foreground))]"
                    aria-hidden
                  />
                  <span className="min-w-0 flex-1 truncate font-medium leading-5">
                    {title}
                  </span>
                </button>
                <SessionActivityIndicator state={running.has(session.chatId) ? "running" : null} />
                {onClose ? (
                  <button
                    type="button"
                    aria-label={t("temporaryChat.closeAction", { title })}
                    onClick={() => onClose(session.key)}
                    className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground/60 transition-colors hover:bg-destructive/10 hover:text-destructive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
                  >
                    <X className="h-3.5 w-3.5" aria-hidden />
                  </button>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

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
              "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground/70 opacity-0 transition-opacity",
              "hover:bg-sidebar-accent hover:text-sidebar-foreground group-hover:opacity-100 focus-visible:opacity-100",
              "data-[state=open]:opacity-100",
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
            <DropdownMenuItem onSelect={onRequestRename}>
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
            "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground/70 opacity-0 transition-opacity",
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
    : `${hiddenCount} hidden topics`;

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
