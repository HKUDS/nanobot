import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type RefObject,
} from "react";
import {
  Archive,
  ArchiveRestore,
  BringToFront,
  CornerDownRight,
  Folder,
  ListChecks,
  MessageCircleDashed,
  MoreHorizontal,
  PanelsTopLeft,
  Pencil,
  Pin,
  PinOff,
  Plus,
  Square,
  SquareCheckBig,
  SquareMinus,
  Trash2,
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
import {
  SIDEBAR_SELECTION_ITEM_CLASS,
  SidebarSelectionHighlight,
} from "@/components/SidebarSelectionHighlight";
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
import {
  clearDraggedSession,
  writeDraggedPane,
  writeDraggedSession,
  type DraggedPane,
} from "@/lib/session-drag";
import { MAX_WORKBENCH_PANES } from "@/components/workbench/workbench-model";
import { deriveTemporaryChatTitle } from "@/lib/temporary-chat";
import { cn } from "@/lib/utils";
import type { ChatSummary, SidebarDensity, SidebarSortMode } from "@/lib/types";

const INITIAL_VISIBLE_SESSIONS = 160;
const VISIBLE_SESSIONS_INCREMENT = 160;
const ACTION_MENU_CONTENT_CLASS = "w-[8.5rem] min-w-[8.5rem]";

export interface SidebarPaneGroup {
  topicKey: string;
  activePaneKey: string;
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
  onToggleArchive: (key: string) => void;
  paneGroups?: Record<string, SidebarPaneGroup>;
  onSelectPane?: (tabKey: string, paneKey: string) => void;
  onDetachPane?: (tabKey: string, paneKey: string) => void;
  onPromotePane?: (tabKey: string, paneKey: string) => void;
  attachableTabKeys?: string[];
  paneAcceptingTabKeys?: string[];
  onAttachPane?: (paneKey: string, tabKey: string) => void;
  onReorderSessions?: (keys: string[]) => void;
  onToggleGroup?: (groupId: string) => void;
  onRequestRenameProject?: (projectKey: string, label: string) => void;
  onNewChatInProject?: (projectPath: string, projectName: string) => void;
  pinnedKeys?: string[];
  archivedKeys?: string[];
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
  onToggleArchive,
  paneGroups = {},
  onSelectPane,
  onDetachPane,
  onPromotePane,
  attachableTabKeys = [],
  paneAcceptingTabKeys = [],
  onAttachPane,
  onReorderSessions,
  onToggleGroup,
  onRequestRenameProject,
  onNewChatInProject,
  pinnedKeys = [],
  archivedKeys = [],
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
  const [draggedSessionKey, setDraggedSessionKey] = useState<string | null>(null);
  const [sessionDropTarget, setSessionDropTarget] = useState<{
    edge: "before" | "after";
    key: string;
  } | null>(null);
  const [draggedSessionHeight, setDraggedSessionHeight] = useState(0);
  const [draggedPane, setDraggedPane] = useState<DraggedPane | null>(null);
  const [tabAttachTargetKey, setTabAttachTargetKey] = useState<string | null>(null);
  const tabAttachTargetRef = useRef<string | null>(null);
  const tabRowRefs = useRef(new Map<string, HTMLLIElement>());
  const pendingTabRectsRef = useRef<Map<string, DOMRect> | null>(null);
  const tabLayoutAnimationsRef = useRef(new Map<string, Animation>());
  const [deleteSelectionMode, setDeleteSelectionMode] = useState(false);
  const [selectedDeleteKeys, setSelectedDeleteKeys] = useState<Set<string>>(
    () => new Set(),
  );
  const activeRowRef = useRef<HTMLDivElement>(null);
  const selectedPaneGroup = activeKey ? paneGroups[activeKey] : undefined;
  const selectedRowKey = selectedPaneGroup
    ? selectedPaneGroup.activePaneKey
    : activeKey;
  const attachableTabs = useMemo(() => new Set(attachableTabKeys), [attachableTabKeys]);
  const paneAcceptingTabs = useMemo(
    () => new Set(paneAcceptingTabKeys),
    [paneAcceptingTabKeys],
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
  const paneMoveTargets = useMemo(() => sessions
    .filter((session) => paneAcceptingTabs.has(session.key))
    .map((session) => ({
      key: session.key,
      title: deleteItemsByKey.get(session.key)?.label ?? session.title ?? session.chatId,
    })), [deleteItemsByKey, paneAcceptingTabs, sessions]);
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
  const sessionLanes = useMemo(() => {
    const lanes = new Map<string, string>();
    for (const group of groups) {
      const scope = group.id.startsWith("date:") ? "timeline" : group.id;
      for (const session of group.sessions) {
        const status = pinned.has(session.key)
          ? "pinned"
          : archived.has(session.key) ? "archived" : "normal";
        lanes.set(session.key, `${scope}:${status}`);
      }
    }
    return lanes;
  }, [archived, groups, pinned]);
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

  const measureTabRows = useCallback(() => {
    const rects = new Map<string, DOMRect>();
    for (const [key, row] of tabRowRefs.current) {
      rects.set(key, row.getBoundingClientRect());
    }
    return rects;
  }, []);

  const updateTabAttachTarget = useCallback((next: string | null) => {
    if (tabAttachTargetRef.current === next) return;
    for (const animation of tabLayoutAnimationsRef.current.values()) animation.cancel();
    tabLayoutAnimationsRef.current.clear();
    pendingTabRectsRef.current = measureTabRows();
    tabAttachTargetRef.current = next;
    setTabAttachTargetKey(next);
  }, [measureTabRows]);

  const resetDragState = useCallback(() => {
    clearDraggedSession();
    setDraggedSessionKey(null);
    setDraggedPane(null);
    setSessionDropTarget(null);
    updateTabAttachTarget(null);
    setDraggedSessionHeight(0);
  }, [updateTabAttachTarget]);

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
  }, [measureTabRows, tabAttachTargetKey]);

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

  const canReorderSession = (targetKey: string) => (
    !deleteSelectionMode
    && !!draggedSessionKey
    && draggedSessionKey !== targetKey
    && sessionLanes.get(draggedSessionKey) === sessionLanes.get(targetKey)
  );
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
  const draggedItemTitle = draggedPane
    ? deleteItemsByKey.get(draggedPane.paneKey)?.label
    : draggedSessionKey ? deleteItemsByKey.get(draggedSessionKey)?.label : undefined;
  const reorderSession = (targetKey: string, edge: "before" | "after") => {
    if (!draggedSessionKey || !canReorderSession(targetKey) || !onReorderSessions) return;
    const keys = groups.flatMap((group) => group.sessions.map((session) => session.key));
    const reordered = keys.filter((key) => key !== draggedSessionKey);
    const targetIndex = reordered.indexOf(targetKey);
    if (targetIndex < 0) return;
    reordered.splice(targetIndex + (edge === "after" ? 1 : 0), 0, draggedSessionKey);
    const groupedKeys = new Set(keys);
    onReorderSessions([
      ...reordered,
      ...sessionOrder.filter((key) => !groupedKeys.has(key)),
    ]);
  };

  return (
    <div className="h-full min-h-0 min-w-0 overflow-x-hidden overflow-y-auto overscroll-contain scrollbar-thin scrollbar-track-transparent">
      <SidebarSelectionHighlight
        targetRef={activeRowRef}
        activeId={draggedSessionKey || draggedPane ? null : selectedRowKey}
        scope="sessions"
        data-chat-list-content
        className="relative min-w-0 space-y-3 px-2 py-1.5"
      >
        {temporarySessions.length > 0 ? (
          <TemporaryChatSection
            sessions={temporarySessions}
            activeKey={activeKey}
            activeRowRef={activeRowRef}
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
          const reorderOffsets = sessionReorderOffsets(
            visibleSessions.map((session) => session.key),
            draggedSessionKey,
            sessionDropTarget,
            draggedSessionHeight,
          );

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
                    const fallbackTitle = t("chat.fallbackTitle", {
                      id: s.chatId.slice(0, 6),
                    });
                    const generatedTitle = s.title?.trim() || "";
                    const title = displayTitle(s, titleOverrides, t("chat.newChat"));
                    const resolvedPaneGroup = paneGroup ?? {
                      topicKey: s.key,
                      activePaneKey: s.key,
                      panes: [{ key: s.key, chatId: s.chatId, title }],
                    };
                    const active = topicActive && resolvedPaneGroup.activePaneKey === s.key;
                    const paneCount = resolvedPaneGroup.panes.length;
                    const tabDeleteKeys = resolvedPaneGroup.panes.map((pane) => pane.key);
                    const tabSelected = tabDeleteKeys.every((key) => (
                      selectedDeleteKeys.has(key)
                    ));
                    const tabPartiallySelected = !tabSelected && tabDeleteKeys.some((key) => (
                      selectedDeleteKeys.has(key)
                    ));
                    const isAttachTarget = tabAttachTargetKey === s.key;
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
                    const projectMode = group.kind === "project";
                    const activityState = running.has(s.chatId)
                      ? "running"
                      : updated.has(s.chatId) && !topicActive
                        ? "updated"
                        : null;
                    return (
                      <li
                        key={s.key}
                        ref={(element) => {
                          if (element) tabRowRefs.current.set(s.key, element);
                          else tabRowRefs.current.delete(s.key);
                        }}
                        data-session-dragging={draggedSessionKey === s.key ? "true" : undefined}
                        data-session-displaced={reorderOffsets.has(s.key) ? "true" : undefined}
                        data-tab-attach-target={tabAttachTargetKey === s.key ? "true" : undefined}
                        className={cn(
                          "relative min-w-0 rounded-xl transition-[transform,opacity,background-color,box-shadow] duration-200 [transition-timing-function:cubic-bezier(0.2,0,0,1)] motion-reduce:transition-none",
                          draggedSessionKey === s.key && "opacity-0",
                          isAttachTarget
                            && "bg-sidebar-accent/35 shadow-[inset_0_0_0_1px_hsl(var(--sidebar-border))]",
                        )}
                        style={{
                          transform: reorderOffsets.has(s.key)
                            ? `translateY(${reorderOffsets.get(s.key)}px)`
                            : undefined,
                        }}
                        onDragOver={(event) => {
                          const rect = event.currentTarget.getBoundingClientRect();
                          const relativeY = rect.height > 0
                            ? (event.clientY - rect.top) / rect.height
                            : 0.5;
                          const paneCanAttach = Boolean(
                            !deleteSelectionMode
                            && draggedPane
                            && draggedPane.sourceTabKey !== s.key
                            && paneAcceptingTabs.has(s.key)
                            && onAttachPane,
                          );
                          const tabCanAttach = Boolean(
                            !deleteSelectionMode
                            && draggedSessionKey
                            && draggedSessionKey !== s.key
                            && attachableTabs.has(draggedSessionKey)
                            && paneAcceptingTabs.has(s.key)
                            && relativeY >= 0.25
                            && relativeY <= 0.75
                            && onAttachPane,
                          );
                          if (paneCanAttach || tabCanAttach) {
                            event.preventDefault();
                            event.dataTransfer.dropEffect = "move";
                            setSessionDropTarget(null);
                            updateTabAttachTarget(s.key);
                            return;
                          }
                          updateTabAttachTarget(null);
                          if (!canReorderSession(s.key)) return;
                          event.preventDefault();
                          event.dataTransfer.dropEffect = "move";
                          const nextTarget = {
                            key: s.key,
                            edge: event.clientY < rect.top + rect.height / 2 ? "before" : "after",
                          } as const;
                          setSessionDropTarget((current) => (
                            current?.key === nextTarget.key && current.edge === nextTarget.edge
                              ? current
                              : nextTarget
                          ));
                        }}
                        onDrop={(event) => {
                          if (tabAttachTargetKey === s.key && onAttachPane) {
                            const paneKey = draggedPane?.paneKey ?? draggedSessionKey;
                            if (paneKey) {
                              event.preventDefault();
                              onAttachPane(paneKey, s.key);
                            }
                            resetDragState();
                            return;
                          }
                          if (!canReorderSession(s.key)) return;
                          event.preventDefault();
                          const rect = event.currentTarget.getBoundingClientRect();
                          const edge = event.clientY < rect.top + rect.height / 2
                            ? "before"
                            : "after";
                          reorderSession(s.key, edge);
                          resetDragState();
                        }}
                      >
                        <div
                          ref={active ? activeRowRef : undefined}
                          data-chat-row={s.key}
                          data-sidebar-tab={s.key}
                          className={cn(
                            "group flex min-w-0 max-w-full items-center gap-2 rounded-xl px-2 text-[13px]",
                            SIDEBAR_SELECTION_ITEM_CLASS,
                            compact ? "min-h-7" : "min-h-8",
                            active
                              ? "text-sidebar-accent-foreground"
                              : "text-sidebar-foreground/82 hover:bg-sidebar-foreground/[0.035] hover:text-sidebar-foreground dark:hover:bg-white/[0.05]",
                            isAttachTarget
                              && "bg-sidebar-accent/65 text-sidebar-accent-foreground",
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
                              if (topicActive && paneGroup && onSelectPane) {
                                onSelectPane(s.key, s.key);
                                return;
                              }
                              onSelect(s.key);
                            }}
                            draggable={!deleteSelectionMode}
                            onDragStart={(event) => {
                              setDraggedSessionKey(s.key);
                              setDraggedPane(null);
                              setSessionDropTarget(null);
                              updateTabAttachTarget(null);
                              setDraggedSessionHeight(
                                event.currentTarget.closest("li")?.getBoundingClientRect().height
                                  ?? event.currentTarget.getBoundingClientRect().height,
                              );
                              writeDraggedSession(event.dataTransfer, s.key);
                            }}
                            onDragEnd={resetDragState}
                            aria-current={active ? "page" : undefined}
                            aria-pressed={deleteSelectionMode ? tabSelected : undefined}
                            title={tooltipTitle}
                            className={cn(
                              "flex min-w-0 flex-1 items-center gap-2 overflow-hidden text-left",
                              deleteSelectionMode
                                ? "cursor-default"
                                : "cursor-grab active:cursor-grabbing",
                              compact ? "py-1" : "py-1.5",
                              projectMode && "pl-7",
                            )}
                          >
                            {deleteSelectionMode ? (
                              <SelectionIndicator
                                checked={tabSelected}
                                partial={tabPartiallySelected}
                              />
                            ) : paneCount > 1 || isAttachTarget ? (
                              <PanelsTopLeft
                                aria-hidden
                                className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60"
                              />
                            ) : null}
                            <span className="min-w-0 flex-1 overflow-hidden">
                            {projectMode ? (
                              <span className="flex w-full min-w-0 items-baseline gap-2">
                                <span className="min-w-0 flex-1 truncate font-medium leading-5">
                                  {title}
                                </span>
                                {paneCount > 1 ? (
                                  <span
                                    aria-hidden
                                    className="shrink-0 text-[10.5px] tabular-nums text-muted-foreground/55"
                                  >
                                    {paneCount}/{MAX_WORKBENCH_PANES}
                                  </span>
                                ) : null}
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
                                {paneCount > 1 ? (
                                  <span
                                    aria-hidden
                                    className="shrink-0 text-[10.5px] tabular-nums text-muted-foreground/55"
                                  >
                                    {paneCount}/{MAX_WORKBENCH_PANES}
                                  </span>
                                ) : null}
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
                          {!deleteSelectionMode ? <DropdownMenu modal={false}>
                            <DropdownMenuTrigger
                              className={cn(
                                "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground/75 opacity-40 transition-opacity",
                                "hover:bg-sidebar-accent hover:text-sidebar-foreground group-hover:opacity-100",
                                "focus-visible:opacity-100",
                                topicActive && "opacity-100",
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
                              {paneGroup
                              && paneGroup.panes.findIndex((pane) => pane.key === s.key) > 0
                              && onPromotePane ? (
                                <DropdownMenuItem onSelect={() => onPromotePane(s.key, s.key)}>
                                  <BringToFront className="h-4 w-4 shrink-0" />
                                  {t("workbench.promotePane", {
                                    defaultValue: "Make {{title}} the primary pane",
                                    title,
                                  })}
                                </DropdownMenuItem>
                              ) : null}
                              <DropdownMenuItem
                                onSelect={() => onTogglePin(s.key)}
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
                              >
                                <Pencil className="h-4 w-4 shrink-0" />
                                {t("chat.rename")}
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                onSelect={() => onToggleArchive(s.key)}
                              >
                                {isArchived ? (
                                  <ArchiveRestore className="h-4 w-4 shrink-0" />
                                ) : (
                                  <Archive className="h-4 w-4 shrink-0" />
                                )}
                                {isArchived ? t("chat.unarchive") : t("chat.archive")}
                              </DropdownMenuItem>
                              {attachableTabs.has(s.key) && onAttachPane ? (
                                <MoveToTabSubmenu
                                  targets={paneMoveTargets.filter((target) => target.key !== s.key)}
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
                          </DropdownMenu> : null}
                        </div>
                        {paneCount > 1 || isAttachTarget ? (
                          <ActivePaneRows
                            group={resolvedPaneGroup}
                            tabTitle={title}
                            tabActive={topicActive}
                            activeRowRef={activeRowRef}
                            running={running}
                            updated={updated}
                            onSelectPane={onSelectPane}
                            onRequestDelete={onRequestDelete}
                            onRequestRename={onRequestRename}
                            onDetachPane={onDetachPane}
                            onPromotePane={onPromotePane}
                            moveTargets={paneMoveTargets.filter((target) => (
                              target.key !== resolvedPaneGroup.topicKey
                            ))}
                            onAttachPane={onAttachPane}
                            deleteSelectionMode={deleteSelectionMode}
                            selectedDeleteKeys={selectedDeleteKeys}
                            onToggleDeleteSelection={toggleDeleteSelection}
                            onBeginDeleteSelection={beginDeleteSelection}
                            dropPreview={isAttachTarget && draggedItemTitle ? {
                              paneTitle: draggedItemTitle,
                              targetTitle: title,
                            } : null}
                            draggedPaneKey={draggedPane?.paneKey ?? null}
                            onPaneDragStart={(event, pane) => {
                              setDraggedPane(pane);
                              setDraggedSessionKey(null);
                              setSessionDropTarget(null);
                              updateTabAttachTarget(null);
                              setDraggedSessionHeight(
                                event.currentTarget.closest("li")?.getBoundingClientRect().height
                                  ?? event.currentTarget.getBoundingClientRect().height,
                              );
                              writeDraggedPane(event.dataTransfer, pane);
                            }}
                            onPaneDragEnd={resetDragState}
                            actionMenuPortalContainer={actionMenuPortalContainer}
                          />
                        ) : null}
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
      </SidebarSelectionHighlight>
    </div>
  );
});

function sessionReorderOffsets(
  keys: string[],
  draggedKey: string | null,
  target: { edge: "before" | "after"; key: string } | null,
  draggedHeight: number,
): Map<string, number> {
  const offsets = new Map<string, number>();
  if (!draggedKey || !target || draggedHeight <= 0) return offsets;
  const sourceIndex = keys.indexOf(draggedKey);
  if (sourceIndex < 0 || target.key === draggedKey) return offsets;
  const remaining = keys.filter((key) => key !== draggedKey);
  const targetIndex = remaining.indexOf(target.key);
  if (targetIndex < 0) return offsets;
  const finalIndex = targetIndex + (target.edge === "after" ? 1 : 0);

  if (sourceIndex < finalIndex) {
    for (let index = sourceIndex + 1; index <= finalIndex; index += 1) {
      offsets.set(keys[index], -draggedHeight);
    }
  } else if (sourceIndex > finalIndex) {
    for (let index = finalIndex; index < sourceIndex; index += 1) {
      offsets.set(keys[index], draggedHeight);
    }
  }
  return offsets;
}

function ActivePaneRows({
  group,
  tabTitle,
  tabActive,
  activeRowRef,
  running,
  updated,
  onSelectPane,
  onRequestDelete,
  onRequestRename,
  onDetachPane,
  onPromotePane,
  moveTargets,
  onAttachPane,
  deleteSelectionMode,
  selectedDeleteKeys,
  onToggleDeleteSelection,
  onBeginDeleteSelection,
  dropPreview,
  draggedPaneKey,
  onPaneDragStart,
  onPaneDragEnd,
  actionMenuPortalContainer,
}: {
  group: SidebarPaneGroup;
  tabTitle: string;
  tabActive: boolean;
  activeRowRef: RefObject<HTMLDivElement>;
  running: ReadonlySet<string>;
  updated: ReadonlySet<string>;
  onSelectPane?: (tabKey: string, paneKey: string) => void;
  onRequestDelete: (key: string, label: string) => void;
  onRequestRename: (key: string, label: string) => void;
  onDetachPane?: (tabKey: string, paneKey: string) => void;
  onPromotePane?: (tabKey: string, paneKey: string) => void;
  moveTargets: Array<{ key: string; title: string }>;
  onAttachPane?: (paneKey: string, tabKey: string) => void;
  deleteSelectionMode: boolean;
  selectedDeleteKeys: ReadonlySet<string>;
  onToggleDeleteSelection: (keys: string[]) => void;
  onBeginDeleteSelection: (keys: string[]) => void;
  dropPreview: { paneTitle: string; targetTitle: string } | null;
  draggedPaneKey: string | null;
  onPaneDragStart: (event: DragEvent<HTMLButtonElement>, pane: DraggedPane) => void;
  onPaneDragEnd: () => void;
  actionMenuPortalContainer?: HTMLElement | null;
}) {
  const { t } = useTranslation();
  const childPanes = group.panes.filter((pane) => pane.key !== group.topicKey);

  return (
    <ul
      aria-label={t("workbench.panesInTab", {
        defaultValue: "Panes in {{title}}",
        title: tabTitle,
      })}
      className={cn(
        "relative ml-5 mr-1 mt-0.5 space-y-0.5 rounded-bl-lg border-l border-sidebar-border/60 py-0.5 pl-2 pr-0.5",
        dropPreview && "pb-1",
      )}
    >
      {childPanes.map((pane) => {
        const index = group.panes.findIndex((candidate) => candidate.key === pane.key);
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

        return (
          <li
            key={pane.key}
            data-pane-dragging={draggedPaneKey === pane.key ? "true" : undefined}
            className="relative min-w-0 before:absolute before:-left-2 before:top-1/2 before:h-px before:w-2 before:bg-sidebar-border/45"
          >
            <div
              ref={active ? activeRowRef : undefined}
              data-chat-row={pane.key}
              data-sidebar-pane={pane.key}
              className={cn(
                "group/pane flex min-h-7 min-w-0 items-center gap-1 rounded-lg px-2 text-[12.5px]",
                SIDEBAR_SELECTION_ITEM_CLASS,
                active
                  ? "text-sidebar-accent-foreground"
                  : "text-sidebar-foreground/72 hover:bg-sidebar-foreground/[0.035] hover:text-sidebar-foreground dark:hover:bg-white/[0.05]",
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
                  onSelectPane?.(group.topicKey, pane.key);
                }}
                draggable={!deleteSelectionMode}
                onDragStart={(event) => onPaneDragStart(event, {
                  paneKey: pane.key,
                  sourceTabKey: group.topicKey,
                })}
                onDragEnd={onPaneDragEnd}
                aria-current={active ? "true" : undefined}
                aria-pressed={deleteSelectionMode ? selected : undefined}
                title={pane.title}
                className={cn(
                  "flex min-w-0 flex-1 items-center gap-2 py-1 text-left font-medium leading-5",
                  deleteSelectionMode ? "cursor-default" : "cursor-grab active:cursor-grabbing",
                )}
              >
                {deleteSelectionMode ? (
                  <SelectionIndicator checked={selected} partial={false} />
                ) : null}
                <span className="min-w-0 flex-1 truncate">{pane.title}</span>
              </button>
              <SessionActivityIndicator state={activityState} />
              {!deleteSelectionMode ? <DropdownMenu modal={false}>
                <DropdownMenuTrigger
                  className={cn(
                    "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground/70 opacity-0 transition-opacity",
                    "hover:bg-sidebar-accent hover:text-sidebar-foreground group-hover/pane:opacity-100",
                    "focus-visible:opacity-100",
                    active && "opacity-100",
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
                  {index > 0 && onPromotePane ? (
                    <DropdownMenuItem onSelect={() => onPromotePane(group.topicKey, pane.key)}>
                      <BringToFront className="h-4 w-4 shrink-0" />
                      {t("workbench.promotePane", {
                        defaultValue: "Make {{title}} the primary pane",
                        title: pane.title,
                      })}
                    </DropdownMenuItem>
                  ) : null}
                  <DropdownMenuItem
                    onSelect={() => onRequestRename(pane.key, pane.title)}
                  >
                    <Pencil className="h-4 w-4 shrink-0" />
                    {t("chat.rename")}
                  </DropdownMenuItem>
                  {onDetachPane ? (
                    <DropdownMenuItem onSelect={() => onDetachPane(group.topicKey, pane.key)}>
                      <Unplug className="h-4 w-4 shrink-0" />
                      {t("workbench.detachPane", {
                        defaultValue: "Move {{title}} to its own topic",
                        title: pane.title,
                      })}
                    </DropdownMenuItem>
                  ) : null}
                  {onAttachPane ? (
                    <MoveToTabSubmenu
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
      {dropPreview ? (
        <li
          data-pane-drop-preview
          role="status"
          aria-label={t("workbench.dropPane", {
            defaultValue: "Move {{pane}} into {{tab}}",
            pane: dropPreview.paneTitle,
            tab: dropPreview.targetTitle,
          })}
          className="relative min-w-0 before:absolute before:-left-2 before:top-1/2 before:h-px before:w-2 before:bg-primary/45"
        >
          <div className="flex min-h-7 items-center gap-2 rounded-lg border border-primary/30 bg-primary/[0.07] px-2 text-[12.5px] font-medium text-foreground/80 shadow-[inset_0_0_0_1px_hsl(var(--background)/0.5)] motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-top-1 motion-safe:duration-150">
            <CornerDownRight className="h-3.5 w-3.5 shrink-0 text-primary/75" aria-hidden />
            <span className="min-w-0 flex-1 truncate">{dropPreview.paneTitle}</span>
          </div>
        </li>
      ) : null}
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

function MoveToTabSubmenu({
  targets,
  onMove,
}: {
  targets: Array<{ key: string; title: string }>;
  onMove: (targetKey: string) => void;
}) {
  const { t } = useTranslation();
  if (targets.length === 0) return null;
  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger>
        <PanelsTopLeft className="h-4 w-4 shrink-0" aria-hidden />
        {t("workbench.moveToTab", { defaultValue: "Move to tab" })}
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent>
        {targets.map((target) => (
          <DropdownMenuItem key={target.key} onSelect={() => onMove(target.key)}>
            <span className="max-w-56 truncate">{target.title}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  );
}

function TemporaryChatSection({
  sessions,
  activeKey,
  activeRowRef,
  running,
  onSelect,
  onClose,
}: {
  sessions: ChatSummary[];
  activeKey: string | null;
  activeRowRef: RefObject<HTMLDivElement>;
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
                ref={active ? activeRowRef : undefined}
                data-temporary-chat-row={session.key}
                className={cn(
                  "group flex min-h-8 min-w-0 max-w-full items-center gap-2 rounded-xl px-2 text-[13px]",
                  SIDEBAR_SELECTION_ITEM_CLASS,
                  active
                    ? "text-sidebar-accent-foreground"
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
