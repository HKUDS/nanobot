import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { CSSProperties, MouseEvent as ReactMouseEvent, ReactElement } from "react";
import {
  Archive,
  ArchiveRestore,
  AlertTriangle,
  ChevronDown,
  Folder,
  FolderTree,
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
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { MAX_WORKBENCH_PANES } from "@/components/workbench/workbench-model";
import { SIDEBAR_SELECTION_ITEM_CLASS } from "@/components/SidebarSelectionHighlight";
import { relativeTime, visibleSessionPreview } from "@/lib/format";
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
import { sessionHandleColor } from "@/lib/session-handle";
import {
  clearDraggedSession,
  hasDraggedSession,
  readDraggedSession,
  writeDraggedSession,
} from "@/lib/session-drag";
import { cn } from "@/lib/utils";
import type { ChatSummary, SidebarDensity, SidebarSortMode } from "@/lib/types";

const INITIAL_VISIBLE_SESSIONS = 160;
const VISIBLE_SESSIONS_INCREMENT = 160;
const ACTION_MENU_CONTENT_CLASS = "w-[11rem] min-w-[11rem] whitespace-nowrap";
const COLLAPSED_PANE_GROUPS_STORAGE_KEY = "nanobot-webui.collapsed-pane-groups.v1";
const DETACH_PANE_DROP_TARGET = "__sidebar-standalone__";

interface SidebarActionMenuController {
  openId: string | null;
  onOpenChange: (id: string, open: boolean) => void;
  openFromContextMenu: (event: ReactMouseEvent<HTMLElement>, id: string) => void;
}

function SidebarItemTooltip({
  label,
  children,
}: {
  label: string;
  children: ReactElement;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side="top" align="start" className="max-w-80 break-words">
        {label}
      </TooltipContent>
    </Tooltip>
  );
}

function SidebarSelectionTrack({
  active,
  handle,
}: {
  active: boolean;
  handle: ChatSummary["handle"];
}) {
  return (
    <span
      data-sidebar-selection-track
      data-active={active ? "true" : "false"}
      aria-hidden
      className={cn(
        "pointer-events-none absolute inset-x-0 bottom-0 h-0.5 origin-left rounded-full",
        "transition-transform duration-200 ease-out motion-reduce:transition-none",
        active ? "scale-x-100" : "scale-x-0",
      )}
      style={{
        backgroundColor: handle ? sessionHandleColor(handle.id) : "currentColor",
      }}
    />
  );
}

function SidebarSessionHandle({ handle }: { handle: ChatSummary["handle"] }) {
  if (!handle) return null;
  return (
    <span
      data-sidebar-session-handle
      className="flex max-w-20 shrink-0 items-center overflow-hidden whitespace-nowrap text-[11px] font-medium leading-5"
    >
      <span
        data-sidebar-session-handle-underline
        className="inline border-b-2 text-foreground"
        style={{
          "--sidebar-session-handle-color": sessionHandleColor(handle.id),
          borderBottomColor: "var(--sidebar-session-handle-color)",
        } as CSSProperties}
      >
        @{handle.name}
      </span>
    </span>
  );
}

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
    handle?: ChatSummary["handle"];
  }>;
}

export interface SidebarDeleteItem {
  key: string;
  label: string;
}

function droppablePaneKey(
  dataTransfer: DataTransfer,
  group: SidebarPaneGroup,
): string | null {
  if (group.panes.length >= MAX_WORKBENCH_PANES
    || !hasDraggedSession(dataTransfer)) return null;
  const paneKey = readDraggedSession(dataTransfer);
  if (!paneKey || group.panes.some((pane) => pane.key === paneKey)) return null;
  return paneKey;
}

function detachablePaneSource(
  dataTransfer: DataTransfer,
  groups: Record<string, SidebarPaneGroup>,
): { paneKey: string; tabKey: string } | null {
  if (!hasDraggedSession(dataTransfer)) return null;
  const paneKey = readDraggedSession(dataTransfer);
  if (!paneKey) return null;
  const source = Object.values(groups).find((group) => (
    (group.visible ?? group.panes.length > 1)
    && group.panes.some((pane) => pane.key === paneKey)
  ));
  return source ? { paneKey, tabKey: source.tabKey } : null;
}

function isWorkbenchTabSurface(target: EventTarget | null): boolean {
  return target instanceof Element
    && target.closest("[data-workbench-tab-surface]") !== null;
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
  recoveryChatIds?: string[];
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
  recoveryChatIds = [],
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
  const layoutRowRefs = useRef(new Map<string, HTMLElement>());
  const pendingLayoutRectsRef = useRef<Map<string, DOMRect> | null>(null);
  const layoutAnimationsRef = useRef(new Map<string, Animation>());
  const [collapsedPaneGroups, setCollapsedPaneGroups] = useState<Set<string>>(
    readCollapsedPaneGroups,
  );
  const [paneDropTarget, setPaneDropTarget] = useState<string | null>(null);
  const [deleteSelectionMode, setDeleteSelectionMode] = useState(false);
  const [openActionMenuId, setOpenActionMenuId] = useState<string | null>(null);
  const [selectedDeleteKeys, setSelectedDeleteKeys] = useState<Set<string>>(
    () => new Set(),
  );
  const deleteSelectionAnchorRef = useRef<string | null>(null);

  useEffect(() => {
    const clearPaneDropTarget = () => setPaneDropTarget(null);
    window.addEventListener("dragend", clearPaneDropTarget);
    window.addEventListener("drop", clearPaneDropTarget);
    return () => {
      window.removeEventListener("dragend", clearPaneDropTarget);
      window.removeEventListener("drop", clearPaneDropTarget);
    };
  }, []);
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
  const handleActionMenuOpenChange = useCallback((id: string, open: boolean) => {
    setOpenActionMenuId((current) => {
      if (open) return id;
      return current === id ? null : current;
    });
  }, []);
  const openActionMenuFromContextMenu = useCallback((
    event: ReactMouseEvent<HTMLElement>,
    id: string,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    if (deleteSelectionMode) return;
    setOpenActionMenuId(id);
  }, [deleteSelectionMode]);
  const actionMenus: SidebarActionMenuController = {
    openId: openActionMenuId,
    onOpenChange: handleActionMenuOpenChange,
    openFromContextMenu: openActionMenuFromContextMenu,
  };

  useEffect(() => {
    setVisibleLimit(INITIAL_VISIBLE_SESSIONS);
  }, [showArchived, sort]);

  useEffect(() => {
    if (!deleteSelectionMode) return;
    setOpenActionMenuId(null);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setDeleteSelectionMode(false);
      setSelectedDeleteKeys(new Set());
      deleteSelectionAnchorRef.current = null;
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

  const measureLayoutRows = useCallback(() => {
    const rects = new Map<string, DOMRect>();
    for (const [key, row] of layoutRowRefs.current) {
      rects.set(key, row.getBoundingClientRect());
    }
    return rects;
  }, []);

  const captureLayout = useCallback(() => {
    for (const animation of layoutAnimationsRef.current.values()) animation.cancel();
    layoutAnimationsRef.current.clear();
    pendingLayoutRectsRef.current = measureLayoutRows();
  }, [measureLayoutRows]);

  const togglePaneGroup = useCallback((key: string) => {
    captureLayout();
    setCollapsedPaneGroups((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, [captureLayout]);

  const toggleProjectGroup = useCallback((key: string) => {
    if (!onToggleGroup) return;
    captureLayout();
    onToggleGroup(key);
  }, [captureLayout, onToggleGroup]);

  useLayoutEffect(() => {
    const previousRects = pendingLayoutRectsRef.current;
    if (!previousRects) return;
    pendingLayoutRectsRef.current = null;
    const nextRects = measureLayoutRows();
    const reduceMotion = typeof window.matchMedia === "function"
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) return;
    for (const [key, nextRect] of nextRects) {
      const previousRect = previousRects.get(key);
      const row = layoutRowRefs.current.get(key);
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
      layoutAnimationsRef.current.set(key, animation);
      animation.addEventListener("finish", () => {
        if (layoutAnimationsRef.current.get(key) === animation) {
          layoutAnimationsRef.current.delete(key);
        }
      }, { once: true });
    }
  }, [collapsedGroups, collapsedPaneGroups, measureLayoutRows]);

  useEffect(() => () => {
    for (const animation of layoutAnimationsRef.current.values()) animation.cancel();
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
  const recovery = new Set(recoveryChatIds);
  const compact = density === "compact";
  const firstProjectGroupIndex = limitedGroups.findIndex((group) => group.kind === "project");
  const selectableDeleteKeys = Array.from(new Set(limitedGroups.flatMap((group) => (
    group.sessions.flatMap((session) => {
      const paneGroup = paneGroups[session.key];
      const isWorkbenchTab = paneGroup?.visible
        ?? ((paneGroup?.panes.length ?? 0) > 1);
      return isWorkbenchTab
        ? paneGroup?.panes.map((pane) => pane.key) ?? [session.key]
        : [session.key];
    })
  ))));

  const beginDeleteSelection = (keys: string[]) => {
    const validKeys = keys.filter((key) => deleteItemsByKey.has(key));
    setDeleteSelectionMode(true);
    setSelectedDeleteKeys(new Set(validKeys));
    deleteSelectionAnchorRef.current = validKeys[0] ?? null;
  };
  const toggleDeleteSelection = (
    keys: string[],
    shiftKey = false,
    targetKey = keys[0],
  ) => {
    const validKeys = keys.filter((key) => deleteItemsByKey.has(key));
    const anchorKey = deleteSelectionAnchorRef.current;
    const range = shiftKey && anchorKey && targetKey
      ? selectionRange(selectableDeleteKeys, anchorKey, targetKey)
      : null;
    setSelectedDeleteKeys((current) => {
      const next = new Set(current);
      if (range) {
        for (const key of range) next.add(key);
        for (const key of validKeys) next.add(key);
        return next;
      }
      const remove = validKeys.length > 0 && validKeys.every((key) => next.has(key));
      for (const key of validKeys) {
        if (remove) next.delete(key);
        else next.add(key);
      }
      return next;
    });
    if (!range) deleteSelectionAnchorRef.current = targetKey ?? null;
  };
  const closeDeleteSelection = () => {
    setDeleteSelectionMode(false);
    setSelectedDeleteKeys(new Set());
    deleteSelectionAnchorRef.current = null;
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
    <TooltipProvider delayDuration={650} skipDelayDuration={120}>
    <div className="h-full min-h-0 min-w-0 overflow-x-hidden overflow-y-auto overscroll-contain scrollbar-thin scrollbar-track-transparent">
      <div
        data-chat-list-content
        data-pane-detach-target={
          paneDropTarget === DETACH_PANE_DROP_TARGET ? "true" : undefined
        }
        onDragEnter={(event) => {
          if (isWorkbenchTabSurface(event.target)) {
            setPaneDropTarget((current) => (
              current === DETACH_PANE_DROP_TARGET ? null : current
            ));
            return;
          }
          const source = onDetachPane && !deleteSelectionMode
            ? detachablePaneSource(event.dataTransfer, paneGroups)
            : null;
          if (!source) return;
          event.preventDefault();
          event.dataTransfer.dropEffect = "move";
          setPaneDropTarget(DETACH_PANE_DROP_TARGET);
        }}
        onDragOver={(event) => {
          if (isWorkbenchTabSurface(event.target)) {
            setPaneDropTarget((current) => (
              current === DETACH_PANE_DROP_TARGET ? null : current
            ));
            return;
          }
          const source = onDetachPane && !deleteSelectionMode
            ? detachablePaneSource(event.dataTransfer, paneGroups)
            : null;
          if (!source) return;
          event.preventDefault();
          event.dataTransfer.dropEffect = "move";
          setPaneDropTarget(DETACH_PANE_DROP_TARGET);
        }}
        onDragLeave={(event) => {
          const nextTarget = event.relatedTarget;
          if (nextTarget instanceof Node && event.currentTarget.contains(nextTarget)) return;
          setPaneDropTarget((current) => (
            current === DETACH_PANE_DROP_TARGET ? null : current
          ));
        }}
        onDrop={(event) => {
          if (isWorkbenchTabSurface(event.target)) return;
          const source = onDetachPane && !deleteSelectionMode
            ? detachablePaneSource(event.dataTransfer, paneGroups)
            : null;
          if (!source || !onDetachPane) return;
          event.preventDefault();
          setPaneDropTarget(null);
          clearDraggedSession();
          onDetachPane(source.tabKey, source.paneKey);
        }}
        className={cn(
          "relative min-w-0 space-y-3 rounded-panel px-2 py-1.5",
          "transition-[background-color,box-shadow]",
          paneDropTarget === DETACH_PANE_DROP_TARGET
            && "bg-primary/[0.05] ring-1 ring-inset ring-primary/25",
        )}
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
          const projectCollapsed = group.kind === "project"
            && Boolean(collapsedGroups[group.id]);
          return (
            <section key={group.id} aria-label={group.label} className="relative z-[1]">
              {index === firstProjectGroupIndex ? (
                <div className="px-2 pb-1 text-[12px] font-medium text-muted-foreground/65">
                  {labels.projects}
                </div>
              ) : null}
              <div>
                <div
                  ref={(element) => {
                    const key = `group:${group.id}`;
                    if (element) layoutRowRefs.current.set(key, element);
                    else layoutRowRefs.current.delete(key);
                  }}
                  data-sidebar-group-header={group.id}
                >
                  {group.kind === "project" ? (
                    <ProjectGroupHeader
                      label={group.label}
                      path={group.projectPath}
                      actionMenuId={`project:${group.id}`}
                      actionMenus={actionMenus}
                      collapsed={projectCollapsed}
                      onToggle={() => toggleProjectGroup(group.id)}
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
                </div>
                {projectCollapsed ? null : (
                <div
                  data-sidebar-project-surface={group.kind === "project" ? "true" : undefined}
                  className={cn(
                    group.kind === "project"
                      && "rounded-es-[16px] border-s-2 border-sidebar-foreground/10 pb-1",
                  )}
                >
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
                            if (element) layoutRowRefs.current.set(s.key, element);
                            else layoutRowRefs.current.delete(s.key);
                          }}
                          data-sidebar-tab-group="true"
                          data-pane-group-collapsed={paneGroupCollapsed ? "true" : undefined}
                          data-pane-drop-target={
                            paneDropTarget === resolvedPaneGroup.tabKey ? "true" : undefined
                          }
                          className="relative my-1.5 min-w-0"
                        >
                          <div
                            data-workbench-tab-surface
                            onDragEnter={(event) => {
                              const paneKey = onAttachPane && !deleteSelectionMode
                                ? droppablePaneKey(event.dataTransfer, resolvedPaneGroup)
                                : null;
                              if (!paneKey) return;
                              event.preventDefault();
                              event.stopPropagation();
                              event.dataTransfer.dropEffect = "move";
                              setPaneDropTarget(resolvedPaneGroup.tabKey);
                            }}
                            onDragOver={(event) => {
                              const paneKey = onAttachPane && !deleteSelectionMode
                                ? droppablePaneKey(event.dataTransfer, resolvedPaneGroup)
                                : null;
                              if (!paneKey) return;
                              event.preventDefault();
                              event.stopPropagation();
                              event.dataTransfer.dropEffect = "move";
                              setPaneDropTarget(resolvedPaneGroup.tabKey);
                            }}
                            onDragLeave={(event) => {
                              const nextTarget = event.relatedTarget;
                              if (nextTarget instanceof Node
                                && event.currentTarget.contains(nextTarget)) return;
                              setPaneDropTarget((current) => (
                                current === resolvedPaneGroup.tabKey ? null : current
                              ));
                            }}
                            onDrop={(event) => {
                              const paneKey = onAttachPane && !deleteSelectionMode
                                ? droppablePaneKey(event.dataTransfer, resolvedPaneGroup)
                                : null;
                              if (!paneKey || !onAttachPane) return;
                              event.preventDefault();
                              event.stopPropagation();
                              setPaneDropTarget(null);
                              clearDraggedSession();
                              onAttachPane(paneKey, resolvedPaneGroup.tabKey);
                            }}
                            className={cn(
                              "min-w-0 transition-[background-color,box-shadow]",
                              projectMode && "-ms-0.5",
                              deleteSelectionMode && (tabSelected || tabPartiallySelected)
                                && "ring-1 ring-inset ring-sidebar-foreground/25",
                              paneDropTarget === resolvedPaneGroup.tabKey
                                && "bg-primary/[0.09] ring-2 ring-inset ring-primary/35 dark:bg-primary/[0.14]",
                            )}
                          >
                              <WorkbenchTabHeader
                                title={title}
                                actionMenuId={`tab:${resolvedPaneGroup.tabKey}`}
                                actionMenus={actionMenus}
                                controlsId={paneGroupId}
                                collapsed={paneGroupCollapsed}
                                deleteSelectionMode={deleteSelectionMode}
                                selected={tabSelected}
                                partiallySelected={tabPartiallySelected}
                                onToggle={() => togglePaneGroup(s.key)}
                                onToggleSelection={(shiftKey) => toggleDeleteSelection(
                                  tabDeleteKeys,
                                  shiftKey,
                                  tabDeleteKeys[0],
                                )}
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
                                  recovery={recovery}
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
                                  actionMenus={actionMenus}
                                />
                              ) : null}
                          </div>
                        </li>
                      );
                    }

                    const isPinned = pinned.has(s.key);
                    const isArchived = archived.has(s.key);
                    const preview = visibleSessionPreview(s.preview);
                    const showPreview = showPreviews && preview && preview !== title;
                    const timestamp = showTimestamps
                      ? relativeTime(s.updatedAt ?? s.createdAt)
                      : "";
                    const activityState = running.has(s.chatId)
                      ? "running"
                      : recovery.has(s.chatId)
                        ? "recovery"
                        : updated.has(s.chatId) && !topicActive
                          ? "updated"
                          : null;
                    const hasPaneMoveTarget = Boolean(onAttachPane)
                      && paneGroupTargets.some((target) => (
                        target.key !== paneGroup?.tabKey && !target.atCapacity
                      ));
                    const canDragSession = !deleteSelectionMode
                      && (!topicActive || hasPaneMoveTarget);
                    const actionMenuId = `session:${s.key}`;
                    return (
                      <li
                        key={s.key}
                        ref={(element) => {
                          if (element) layoutRowRefs.current.set(s.key, element);
                          else layoutRowRefs.current.delete(s.key);
                        }}
                        className="relative min-w-0"
                      >
                        <div
                          data-chat-row={s.key}
                          data-sidebar-tab={s.key}
                          onContextMenu={(event) => (
                            actionMenus.openFromContextMenu(event, actionMenuId)
                          )}
                          className={cn(
                            "group flex min-w-0 max-w-full items-center gap-1 rounded-control px-2 text-[13px]",
                            SIDEBAR_SELECTION_ITEM_CLASS,
                            compact ? "min-h-7" : "min-h-8",
                            topicActive
                              ? "text-sidebar-foreground"
                              : "text-sidebar-foreground/82 hover:text-sidebar-foreground",
                            deleteSelectionMode && (tabSelected || tabPartiallySelected)
                              && "bg-sidebar-accent/55 text-sidebar-accent-foreground",
                          )}
                        >
                          <button
                              type="button"
                              onClick={(event) => {
                                if (deleteSelectionMode) {
                                  toggleDeleteSelection(tabDeleteKeys, event.shiftKey, s.key);
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
                              className={cn(
                                "flex min-w-0 flex-1 items-center gap-2 overflow-hidden text-left",
                                canDragSession && "cursor-grab active:cursor-grabbing",
                                deleteSelectionMode && "cursor-default",
                                compact ? "py-1" : "py-1.5",
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
                                    <span className="relative flex w-full min-w-0 items-baseline gap-2">
                                      <SidebarSessionHandle handle={s.handle} />
                                      <span className="min-w-0 flex-1 truncate font-medium leading-5">
                                        {title}
                                      </span>
                                      {isPinned ? <PinnedChatIndicator /> : null}
                                    {timestamp ? (
                                      <span className="shrink-0 text-[11.5px] font-medium text-muted-foreground/58">
                                        {timestamp}
                                      </span>
                                    ) : null}
                                    <SidebarSelectionTrack active={topicActive} handle={s.handle} />
                                  </span>
                                ) : (
                                  <span className="relative flex w-full min-w-0 items-center gap-1.5">
                                    <SidebarSessionHandle handle={s.handle} />
                                    <span className="min-w-0 flex-1 truncate font-medium leading-5">
                                      {title}
                                    </span>
                                    {isPinned ? <PinnedChatIndicator /> : null}
                                    <SidebarSelectionTrack active={topicActive} handle={s.handle} />
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
                            <DropdownMenu
                              modal={false}
                              open={actionMenus.openId === actionMenuId}
                              onOpenChange={(open) => (
                                actionMenus.onOpenChange(actionMenuId, open)
                              )}
                            >
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
                                  {t("workbench.createGroup")}
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
                  {foldableChatsGroup && canToggleFold ? (
                    <ChatsFoldFooter
                      folded={foldedChatsGroup}
                      hiddenCount={hiddenInGroup}
                      onToggle={() => onToggleGroup?.(group.id)}
                    />
                  ) : null}
                </div>
                )}
              </div>
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
    </TooltipProvider>
  );
});

function WorkbenchTabHeader({
  title,
  actionMenuId,
  actionMenus,
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
  actionMenuId: string;
  actionMenus: SidebarActionMenuController;
  controlsId: string;
  collapsed: boolean;
  deleteSelectionMode: boolean;
  selected: boolean;
  partiallySelected: boolean;
  onToggle: () => void;
  onToggleSelection: (shiftKey: boolean) => void;
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
      onContextMenu={(event) => actionMenus.openFromContextMenu(event, actionMenuId)}
      className={cn(
        "group/tab flex min-w-0 items-center gap-0.5 rounded-control px-1.5 text-sidebar-foreground/85",
        collapsed ? "min-h-6" : "min-h-7",
      )}
    >
      <SidebarItemTooltip label={title}>
        <button
          type="button"
          onClick={(event) => {
            if (deleteSelectionMode) onToggleSelection(event.shiftKey);
            else onToggle();
          }}
          draggable={false}
          aria-label={t("workbench.tabAria", { title })}
          aria-expanded={deleteSelectionMode ? undefined : !collapsed}
          aria-controls={deleteSelectionMode ? undefined : controlsId}
          aria-pressed={deleteSelectionMode ? selected : undefined}
          className={cn(
            "flex min-w-0 flex-1 items-center gap-2 overflow-hidden px-0.5 py-1 text-left",
            "text-[12.5px] font-normal leading-5",
            deleteSelectionMode && "cursor-default",
          )}
        >
          {deleteSelectionMode ? (
            <SelectionIndicator checked={selected} partial={partiallySelected} />
          ) : null}
          <FolderTree
            className="h-3.5 w-3.5 shrink-0 text-muted-foreground/70"
            strokeWidth={1.75}
            aria-hidden
          />
          <span className="min-w-0 flex-1 truncate">{title}</span>
        </button>
      </SidebarItemTooltip>
      {!deleteSelectionMode ? (
        <>
          <DropdownMenu
            modal={false}
            open={actionMenus.openId === actionMenuId}
            onOpenChange={(open) => actionMenus.onOpenChange(actionMenuId, open)}
          >
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
                  {t("workbench.dissolveTab")}
                </DropdownMenuItem>
              ) : null}
              <DropdownMenuItem
                tone="destructive"
                onSelect={() => window.setTimeout(onRequestDelete, 0)}
                className="whitespace-nowrap"
              >
                <Trash2 className="h-4 w-4 shrink-0" />
                {t("workbench.deleteConversations")}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <SidebarItemTooltip label={disclosureLabel}>
            <button
              type="button"
              aria-expanded={!collapsed}
              aria-controls={controlsId}
              aria-label={disclosureLabel}
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
                  collapsed && "rotate-90",
                )}
              />
            </button>
          </SidebarItemTooltip>
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
  recovery,
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
  actionMenus,
}: {
  id: string;
  group: SidebarPaneGroup;
  tabTitle: string;
  tabActive: boolean;
  compact: boolean;
  running: ReadonlySet<string>;
  updated: ReadonlySet<string>;
  recovery: ReadonlySet<string>;
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
  onToggleDeleteSelection: (
    keys: string[],
    shiftKey?: boolean,
    targetKey?: string,
  ) => void;
  onBeginDeleteSelection: (keys: string[]) => void;
  actionMenuPortalContainer?: HTMLElement | null;
  actionMenus: SidebarActionMenuController;
}) {
  const { t } = useTranslation();
  const panes = group.panes;
  return (
    <ul
      id={id}
      aria-label={t("workbench.panesInTab", { title: tabTitle })}
      className="mt-0.5 space-y-0.5 rounded-es-[14px] border-s-2 border-sidebar-foreground/25 pb-1"
    >
      {panes.map((pane) => {
        const active = tabActive && pane.key === group.activePaneKey;
        const activityState = running.has(pane.chatId)
          ? "running"
          : recovery.has(pane.chatId)
            ? "recovery"
            : updated.has(pane.chatId) && !active
              ? "updated"
              : null;
        const paneActionsLabel = t("workbench.paneActions", { title: pane.title });
        const selected = selectedDeleteKeys.has(pane.key);
        const isPinned = pinned.has(pane.key);
        const isArchived = archived.has(pane.key);
        const hasPaneMoveTarget = Boolean(onAttachPane)
          && moveTargets.some((target) => !target.atCapacity);
        const canDragSession = !deleteSelectionMode
          && (!active || Boolean(onDetachPane) || hasPaneMoveTarget);
        const actionMenuId = `pane:${pane.key}`;

        return (
          <li
            key={pane.key}
            className="relative min-w-0"
          >
            <div
              data-chat-row={pane.key}
              data-sidebar-pane={pane.key}
              onContextMenu={(event) => (
                actionMenus.openFromContextMenu(event, actionMenuId)
              )}
              className={cn(
                "group/pane flex min-w-0 max-w-full items-center gap-1 rounded-control px-2 text-[13px]",
                SIDEBAR_SELECTION_ITEM_CLASS,
                compact ? "min-h-7" : "min-h-8",
                active
                  ? "text-sidebar-foreground"
                  : "text-sidebar-foreground/82 hover:text-sidebar-foreground",
                deleteSelectionMode && selected
                  && "bg-sidebar-accent/55 text-sidebar-accent-foreground",
              )}
            >
              <button
                  type="button"
                  onClick={(event) => {
                    if (deleteSelectionMode) {
                      onToggleDeleteSelection([pane.key], event.shiftKey, pane.key);
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
                  <span className="relative flex min-w-0 flex-1 items-center gap-2 overflow-hidden">
                    <SidebarSessionHandle handle={pane.handle} />
                    <span className="min-w-0 flex-1 truncate">{pane.title}</span>
                    {isPinned ? <PinnedChatIndicator /> : null}
                    <SidebarSelectionTrack active={active} handle={pane.handle} />
                  </span>
              </button>
              <SessionActivityIndicator state={activityState} />
              {!deleteSelectionMode ? <DropdownMenu
                modal={false}
                open={actionMenus.openId === actionMenuId}
                onOpenChange={(open) => actionMenus.onOpenChange(actionMenuId, open)}
              >
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
                      {t("workbench.detachPane", { title: pane.title })}
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

function selectionRange(order: string[], anchorKey: string, targetKey: string): string[] | null {
  const anchorIndex = order.indexOf(anchorKey);
  const targetIndex = order.indexOf(targetKey);
  if (anchorIndex < 0 || targetIndex < 0) return null;
  const start = Math.min(anchorIndex, targetIndex);
  const end = Math.max(anchorIndex, targetIndex);
  return order.slice(start, end + 1);
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
        {t("workbench.moveTo")}
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
  actionMenuId,
  actionMenus,
  collapsed,
  onToggle,
  onRequestRename,
  onNewChat,
  actionMenuPortalContainer,
  updatedAt,
}: {
  label: string;
  path?: string;
  actionMenuId: string;
  actionMenus: SidebarActionMenuController;
  collapsed: boolean;
  onToggle: () => void;
  onRequestRename?: () => void;
  onNewChat?: () => void;
  actionMenuPortalContainer?: HTMLElement | null;
  updatedAt?: string | null;
}) {
  const { t } = useTranslation();
  const projectButton = (
    <button
      type="button"
      aria-expanded={!collapsed}
      onClick={onToggle}
      className="flex min-w-0 flex-1 items-center gap-2 rounded-lg px-1.5 py-1 text-left transition-colors hover:bg-sidebar-accent/45 hover:text-sidebar-foreground"
    >
      <Folder className="h-3.5 w-3.5 shrink-0" aria-hidden />
      <span className="min-w-0 flex-1 truncate">{label}</span>
    </button>
  );
  const disclosureLabel = `${t("chat.groups.projects")}: ${label}`;

  return (
      <div
        onContextMenu={onRequestRename || onNewChat
          ? (event) => actionMenus.openFromContextMenu(event, actionMenuId)
          : undefined}
        className="group flex min-w-0 items-center gap-1 px-1 pb-1 pt-1 text-[12px] font-medium text-muted-foreground/78"
      >
        {path ? (
          <Tooltip>
            <TooltipTrigger asChild>{projectButton}</TooltipTrigger>
            <TooltipContent side="top" align="start" className="max-w-72 break-words">
              {path}
            </TooltipContent>
          </Tooltip>
        ) : projectButton}
        {updatedAt ? (
          <span className="shrink-0 text-[11px] text-muted-foreground/55">
            {relativeTime(updatedAt)}
          </span>
        ) : null}
        {onRequestRename || onNewChat ? (
          <DropdownMenu
            modal={false}
            open={actionMenus.openId === actionMenuId}
            onOpenChange={(open) => actionMenus.onOpenChange(actionMenuId, open)}
          >
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
              {onNewChat ? (
                <DropdownMenuItem onSelect={onNewChat}>
                  <Plus className="h-4 w-4 shrink-0" aria-hidden />
                  {t("sidebar.newChat")}
                </DropdownMenuItem>
              ) : null}
              {onRequestRename ? (
                <DropdownMenuItem onSelect={onRequestRename}>
                  <Pencil className="h-4 w-4 shrink-0" />
                  {t("chat.rename")}
                </DropdownMenuItem>
              ) : null}
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
        <SidebarItemTooltip label={disclosureLabel}>
          <button
            type="button"
            aria-expanded={!collapsed}
            aria-label={disclosureLabel}
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
              data-sidebar-project-disclosure-icon
              aria-hidden
              className={cn(
                "h-3.5 w-3.5 transition-transform duration-200 ease-out motion-reduce:transition-none",
                collapsed && "rotate-90",
              )}
            />
          </button>
        </SidebarItemTooltip>
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

function PinnedChatIndicator() {
  return (
    <span
      data-sidebar-pinned-indicator
      aria-hidden="true"
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
  state: "running" | "updated" | "recovery" | null;
}) {
  const { t } = useTranslation();

  if (state === "recovery") {
    const label = t("chat.activity.recovery", {
      defaultValue: "This conversation needs your attention",
    });
    return (
      <SidebarItemTooltip label={label}>
        <span
          role="img"
          aria-label={label}
          className="grid h-4 w-4 shrink-0 place-items-center text-[#ff8a3d]"
        >
          <AlertTriangle className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
        </span>
      </SidebarItemTooltip>
    );
  }

  if (state === "running") {
    const label = t("chat.activity.running");
    return (
      <SidebarItemTooltip label={label}>
        <span
          role="img"
          aria-label={label}
          className="grid h-4 w-4 shrink-0 place-items-center"
        >
          <span className="h-3 w-3 animate-spin rounded-full border border-blue-500/25 border-t-blue-500 [animation-duration:1.4s] motion-reduce:animate-none dark:border-blue-400/25 dark:border-t-blue-400" />
        </span>
      </SidebarItemTooltip>
    );
  }

  if (state === "updated") {
    const label = t("chat.activity.updated");
    return (
      <SidebarItemTooltip label={label}>
        <span
          role="img"
          aria-label={label}
          className="grid h-4 w-4 shrink-0 place-items-center"
        >
          <span className="h-2 w-2 rounded-full bg-[#ff8a3d] shadow-[0_0_0_2px_rgba(255,138,61,0.16)]" />
        </span>
      </SidebarItemTooltip>
    );
  }

  return <span className="h-4 w-4 shrink-0" aria-hidden="true" />;
}
