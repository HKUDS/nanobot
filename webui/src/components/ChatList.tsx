import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
} from "react";
import {
  Archive,
  ArchiveRestore,
  BringToFront,
  ChevronDown,
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
import { SIDEBAR_SELECTION_ITEM_CLASS } from "@/components/SidebarSelectionHighlight";
import {
  paneDropSlotForRow,
  paneTabDragLayout,
  samePaneDropSlot,
  type PaneDropSlot,
  type PaneTabDragState,
} from "@/components/pane-tab-drag";
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
import { deriveTemporaryChatTitle } from "@/lib/temporary-chat";
import { cn } from "@/lib/utils";
import type { ChatSummary, SidebarDensity, SidebarSortMode } from "@/lib/types";

const INITIAL_VISIBLE_SESSIONS = 160;
const VISIBLE_SESSIONS_INCREMENT = 160;
const ACTION_MENU_CONTENT_CLASS = "w-[8.5rem] min-w-[8.5rem]";
const DEFAULT_PANE_ROW_HEIGHT = 32;

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

interface PaneDragMotion {
  frame: number | null;
  grabOffsetX: number;
  grabOffsetY: number;
  originHeight: number;
  originLeft: number;
  originTop: number;
  originWidth: number;
  overlay: HTMLElement;
  pointerX: number;
  pointerY: number;
  snapHeight: number | null;
  snapLeft: number | null;
  snapTop: number | null;
  snapWidth: number | null;
}

function positionPaneDragMotion(motion: PaneDragMotion): void {
  const left = motion.snapLeft ?? motion.pointerX - motion.grabOffsetX;
  const top = motion.snapTop ?? motion.pointerY - motion.grabOffsetY;
  motion.overlay.style.width = `${motion.snapWidth ?? motion.originWidth}px`;
  motion.overlay.style.height = `${motion.snapHeight ?? motion.originHeight}px`;
  motion.overlay.style.transform = `translate3d(${left - motion.originLeft}px, ${
    top - motion.originTop
  }px, 0)`;
}

function updatePaneDragSnap(
  motion: PaneDragMotion,
  slot: HTMLElement | null,
): void {
  const rect = slot?.getBoundingClientRect();
  motion.snapHeight = rect?.height ?? null;
  motion.snapLeft = rect?.left ?? null;
  motion.snapTop = rect?.top ?? null;
  motion.snapWidth = rect?.width ?? null;
}

function hideNativeDragPreview(dataTransfer: DataTransfer): void {
  if (typeof dataTransfer.setDragImage !== "function") return;
  const canvas = document.createElement("canvas");
  canvas.width = 1;
  canvas.height = 1;
  canvas.style.position = "fixed";
  canvas.style.left = "-2px";
  canvas.style.top = "-2px";
  canvas.style.pointerEvents = "none";
  document.body.append(canvas);
  try {
    dataTransfer.setDragImage(canvas, 0, 0);
  } catch {
    // Some DOM shims expose setDragImage without implementing it.
  }
  window.setTimeout(() => canvas.remove(), 0);
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
  onAttachPane?: (
    paneKey: string,
    tabKey: string,
    beforePaneKey?: string | null,
  ) => void;
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
  const [sessionDropTarget, setSessionDropTarget] = useState<{
    edge: "before" | "after";
    key: string;
  } | null>(null);
  const [paneDrag, setPaneDrag] = useState<PaneTabDragState | null>(null);
  const tabRowRefs = useRef(new Map<string, HTMLLIElement>());
  const pendingTabRectsRef = useRef<Map<string, DOMRect> | null>(null);
  const tabLayoutAnimationsRef = useRef(new Map<string, Animation>());
  const paneDragMotionRef = useRef<PaneDragMotion | null>(null);
  const [collapsedPaneGroups, setCollapsedPaneGroups] = useState<Set<string>>(
    () => new Set(),
  );
  const [deleteSelectionMode, setDeleteSelectionMode] = useState(false);
  const [selectedDeleteKeys, setSelectedDeleteKeys] = useState<Set<string>>(
    () => new Set(),
  );
  const draggedSessionKey = paneDrag?.origin === "tab"
    ? paneDrag.item.paneKey
    : null;
  const draggedSessionHeight = paneDrag?.origin === "tab" ? paneDrag.height : 0;
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

  useEffect(() => {
    setCollapsedPaneGroups((current) => {
      const next = new Set(Array.from(current).filter((key) => (
        (paneGroups[key]?.panes.length ?? 0) > 1
      )));
      if (next.size === current.size && Array.from(next).every((key) => current.has(key))) {
        return current;
      }
      return next;
    });
  }, [paneGroups]);

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

  const updatePaneDropSlot = useCallback((next: PaneDropSlot | null) => {
    if (!paneDrag || samePaneDropSlot(paneDrag.slot, next)) return;
    captureTabLayout();
    setPaneDrag({ ...paneDrag, slot: next });
  }, [captureTabLayout, paneDrag]);

  const togglePaneGroup = useCallback((key: string) => {
    captureTabLayout();
    setCollapsedPaneGroups((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, [captureTabLayout]);

  const updatePaneDragMotion = useCallback((clientX: number, clientY: number) => {
    const motion = paneDragMotionRef.current;
    if (!motion || (clientX === 0 && clientY === 0)) return;
    motion.pointerX = clientX;
    motion.pointerY = clientY;
    if (motion.frame !== null) return;
    motion.frame = window.requestAnimationFrame(() => {
      const current = paneDragMotionRef.current;
      if (!current) return;
      current.frame = null;
      if (current.snapLeft !== null) {
        const slot = document.querySelector<HTMLElement>("[data-pane-snap-slot]");
        if (slot) updatePaneDragSnap(current, slot);
      }
      positionPaneDragMotion(current);
    });
  }, []);

  const beginPaneDragMotion = useCallback((event: DragEvent<HTMLButtonElement>) => {
    const element = event.currentTarget.closest<HTMLLIElement>("li");
    if (!element) return;
    const visual = element.querySelector<HTMLElement>(
      "[data-sidebar-pane], [data-sidebar-tab]",
    ) ?? element;
    const rect = visual.getBoundingClientRect();
    const overlay = visual.cloneNode(true) as HTMLElement;
    overlay.removeAttribute("data-chat-row");
    overlay.removeAttribute("data-sidebar-pane");
    overlay.removeAttribute("data-sidebar-tab");
    overlay.setAttribute("data-pane-drag-overlay", "true");
    overlay.setAttribute("aria-hidden", "true");
    overlay.classList.add(
      "!bg-sidebar-selected",
      "!shadow-none",
    );
    overlay.querySelectorAll<HTMLElement>("button, [tabindex]").forEach((child) => {
      child.tabIndex = -1;
    });
    Object.assign(overlay.style, {
      position: "fixed",
      left: `${rect.left}px`,
      top: `${rect.top}px`,
      width: `${rect.width}px`,
      height: `${rect.height}px`,
      margin: "0",
      opacity: "1",
      visibility: "visible",
      pointerEvents: "none",
      zIndex: "2147483647",
      transform: "translate3d(0, 0, 0)",
      transition: "none",
      boxShadow: "none",
    });
    document.body.append(overlay);
    const pointerX = event.clientX || rect.left + rect.width / 2;
    const pointerY = event.clientY || rect.top + rect.height / 2;
    paneDragMotionRef.current = {
      frame: null,
      grabOffsetX: pointerX - rect.left,
      grabOffsetY: pointerY - rect.top,
      originHeight: rect.height,
      originLeft: rect.left,
      originTop: rect.top,
      originWidth: rect.width,
      overlay,
      pointerX,
      pointerY,
      snapHeight: null,
      snapLeft: null,
      snapTop: null,
      snapWidth: null,
    };
    hideNativeDragPreview(event.dataTransfer);
  }, []);

  const clearPaneDragMotion = useCallback(() => {
    const motion = paneDragMotionRef.current;
    if (!motion) return;
    if (motion.frame !== null) window.cancelAnimationFrame(motion.frame);
    motion.overlay.remove();
    paneDragMotionRef.current = null;
  }, []);

  const resetDragState = useCallback(() => {
    clearPaneDragMotion();
    clearDraggedSession();
    setPaneDrag(null);
    setSessionDropTarget(null);
  }, [clearPaneDragMotion]);

  const finishDragState = useCallback(() => {
    resetDragState();
  }, [resetDragState]);

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
  }, [
    collapsedPaneGroups,
    measureTabRows,
    paneDrag?.slot?.beforePaneKey,
    paneDrag?.slot?.tabKey,
  ]);

  useLayoutEffect(() => {
    const motion = paneDragMotionRef.current;
    if (!motion) return;
    const slot = paneDrag?.slot
      ? Array.from(document.querySelectorAll<HTMLElement>("[data-pane-snap-slot]"))
          .find((element) => element.dataset.paneSnapTab === paneDrag.slot?.tabKey)
      : null;
    if (slot) {
      updatePaneDragSnap(motion, slot);
      const reduceMotion = typeof window.matchMedia === "function"
        && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      motion.overlay.style.transition = reduceMotion
        ? "none"
        : "transform 140ms cubic-bezier(0.2, 0, 0, 1), width 140ms cubic-bezier(0.2, 0, 0, 1), height 140ms cubic-bezier(0.2, 0, 0, 1)";
    } else {
      updatePaneDragSnap(motion, null);
      motion.overlay.style.transition = "none";
    }
    positionPaneDragMotion(motion);
  }, [paneDrag?.slot?.beforePaneKey, paneDrag?.slot?.tabKey]);

  useEffect(() => () => {
    clearPaneDragMotion();
    for (const animation of tabLayoutAnimationsRef.current.values()) animation.cancel();
  }, [clearPaneDragMotion]);

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
    <div
      className="h-full min-h-0 min-w-0 overflow-x-hidden overflow-y-auto overscroll-contain scrollbar-thin scrollbar-track-transparent"
      onDragCapture={(event) => updatePaneDragMotion(event.clientX, event.clientY)}
      onDragOverCapture={(event) => updatePaneDragMotion(event.clientX, event.clientY)}
    >
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
                    const paneCount = resolvedPaneGroup.panes.length;
                    const draggingTab = draggedSessionKey === s.key;
                    const paneGroupCollapsed = paneCount > 1
                      && collapsedPaneGroups.has(s.key);
                    const paneGroupExpanded = !paneGroupCollapsed;
                    const active = topicActive && (paneCount === 1 || paneGroupCollapsed);
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
                    const tabActivityState = resolvedPaneGroup.panes.some((pane) => (
                      running.has(pane.chatId)
                    ))
                      ? "running"
                      : resolvedPaneGroup.panes.some((pane) => (
                          updated.has(pane.chatId)
                          && (!topicActive || pane.key !== resolvedPaneGroup.activePaneKey)
                        ))
                        ? "updated"
                        : activityState;
                    return (
                      <li
                        key={s.key}
                        ref={(element) => {
                          if (element) tabRowRefs.current.set(s.key, element);
                          else tabRowRefs.current.delete(s.key);
                        }}
                        data-session-dragging={draggedSessionKey === s.key ? "true" : undefined}
                        data-session-displaced={reorderOffsets.has(s.key) ? "true" : undefined}
                        data-sidebar-tab-group={paneCount > 1 ? "true" : undefined}
                        data-pane-group-collapsed={paneGroupCollapsed ? "true" : undefined}
                        className={cn(
                          "relative min-w-0 rounded-[0.7rem] transition-transform duration-200 [transition-timing-function:cubic-bezier(0.2,0,0,1)] motion-reduce:transition-none",
                          paneCount > 1 && "my-1",
                        )}
                        style={{
                          transform: reorderOffsets.has(s.key)
                            ? `translateY(${reorderOffsets.get(s.key)}px)`
                            : undefined,
                        }}
                        onDragOver={(event) => {
                          updatePaneDropSlot(null);
                          const rect = event.currentTarget
                            .querySelector<HTMLElement>(":scope > [data-sidebar-tab]")
                            ?.getBoundingClientRect()
                            ?? event.currentTarget.getBoundingClientRect();
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
                          if (!canReorderSession(s.key)) return;
                          event.preventDefault();
                          const rect = event.currentTarget
                            .querySelector<HTMLElement>(":scope > [data-sidebar-tab]")
                            ?.getBoundingClientRect()
                            ?? event.currentTarget.getBoundingClientRect();
                          const edge = event.clientY < rect.top + rect.height / 2
                            ? "before"
                            : "after";
                          reorderSession(s.key, edge);
                          resetDragState();
                        }}
                      >
                        <div
                          data-chat-row={paneCount === 1 ? s.key : undefined}
                          data-sidebar-tab={s.key}
                          className={cn(
                            "group flex min-w-0 max-w-full items-center gap-1 rounded-[0.65rem] px-2 text-[13px]",
                            SIDEBAR_SELECTION_ITEM_CLASS,
                            compact ? "min-h-7" : "min-h-8",
                            paneCount > 1 && !active
                              && "bg-sidebar-foreground/[0.05] dark:bg-white/[0.065]",
                            active
                              ? "bg-sidebar-selected text-sidebar-accent-foreground"
                              : "text-sidebar-foreground/82 hover:bg-sidebar-foreground/[0.075] hover:text-sidebar-foreground dark:hover:bg-white/[0.09]",
                            deleteSelectionMode && (tabSelected || tabPartiallySelected)
                              && "bg-sidebar-accent/55 text-sidebar-accent-foreground",
                            draggingTab
                              && "!bg-transparent !text-transparent !shadow-none [&_*]:!text-transparent",
                          )}
                        >
                          <button
                            type="button"
                            onClick={() => {
                              if (deleteSelectionMode) {
                                toggleDeleteSelection(tabDeleteKeys);
                                return;
                              }
                              if (topicActive) return;
                              onSelect(s.key);
                            }}
                            draggable={!deleteSelectionMode}
                            onDragStart={(event) => {
                              beginPaneDragMotion(event);
                              setSessionDropTarget(null);
                              const measuredHeight = event.currentTarget
                                .closest<HTMLElement>("[data-sidebar-tab]")
                                ?.getBoundingClientRect().height
                                ?? event.currentTarget.getBoundingClientRect().height;
                              setPaneDrag({
                                origin: "tab",
                                item: { paneKey: s.key, sourceTabKey: s.key },
                                height: measuredHeight > 0
                                  ? measuredHeight
                                  : DEFAULT_PANE_ROW_HEIGHT,
                                slot: null,
                              });
                              writeDraggedSession(event.dataTransfer, s.key);
                            }}
                            onDragEnd={finishDragState}
                            aria-current={active ? "page" : undefined}
                            aria-pressed={deleteSelectionMode ? tabSelected : undefined}
                            aria-label={paneCount > 1
                              ? t("workbench.tabAria", { title })
                              : draggingTab ? title : undefined}
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
                            {draggedSessionKey === s.key ? null : (
                              <>
                                {deleteSelectionMode ? (
                                  <SelectionIndicator
                                    checked={tabSelected}
                                    partial={tabPartiallySelected}
                                  />
                                ) : null}
                                {paneCount > 1 && !deleteSelectionMode ? (
                                  <PanelsTopLeft
                                    aria-hidden
                                    className="h-3.5 w-3.5 shrink-0 text-muted-foreground/65"
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
                              </>
                            )}
                          </button>
                          {draggedSessionKey !== s.key
                          && (paneCount === 1 || paneGroupCollapsed) ? (
                            <SessionActivityIndicator state={tabActivityState} />
                          ) : null}
                          {!deleteSelectionMode && draggedSessionKey !== s.key ? (
                            <DropdownMenu modal={false}>
                            <DropdownMenuTrigger
                              className={cn(
                                "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground/75 transition-opacity",
                                paneCount > 1 ? "opacity-0" : "opacity-40",
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
                          </DropdownMenu>
                          ) : null}
                          {!deleteSelectionMode
                          && draggedSessionKey !== s.key
                          && paneCount > 1 ? (
                            <button
                              type="button"
                              aria-expanded={!paneGroupCollapsed}
                              aria-controls={paneGroupId}
                              aria-label={t(
                                paneGroupCollapsed
                                  ? "workbench.expandTabGroup"
                                  : "workbench.collapseTabGroup",
                                { title },
                              )}
                              title={t(
                                paneGroupCollapsed
                                  ? "workbench.expandTabGroup"
                                  : "workbench.collapseTabGroup",
                                { title },
                              )}
                              onClick={() => togglePaneGroup(s.key)}
                              className={cn(
                                "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground/70",
                                "transition-[background-color,color,transform] duration-150 ease-out",
                                "hover:bg-sidebar-accent hover:text-sidebar-foreground active:scale-[0.96]",
                                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60",
                                "motion-reduce:transition-none motion-reduce:active:scale-100",
                              )}
                            >
                              <ChevronDown
                                aria-hidden
                                className={cn(
                                  "h-3.5 w-3.5 transition-transform duration-200 ease-out motion-reduce:transition-none",
                                  !paneGroupCollapsed && "rotate-180",
                                )}
                              />
                            </button>
                          ) : null}
                        </div>
                        {paneCount > 1 && paneGroupExpanded ? (
                          <ActivePaneRows
                            id={paneGroupId}
                            group={resolvedPaneGroup}
                            tabTitle={title}
                            tabActive={topicActive}
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
                            paneDrag={paneDrag}
                            onPaneDropSlotChange={(slot) => {
                              updatePaneDropSlot(slot);
                            }}
                            onPaneDragStart={(event, pane) => {
                              beginPaneDragMotion(event);
                              setSessionDropTarget(null);
                              const measuredHeight = event.currentTarget.closest("li")
                                ?.getBoundingClientRect().height
                                ?? event.currentTarget.getBoundingClientRect().height;
                              const height = measuredHeight > 0
                                ? measuredHeight
                                : DEFAULT_PANE_ROW_HEIGHT;
                              setPaneDrag({ origin: "pane", item: pane, height, slot: null });
                              writeDraggedPane(event.dataTransfer, pane);
                            }}
                            onPaneDragEnd={finishDragState}
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
      </div>
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
    offsets.set(draggedKey, (finalIndex - sourceIndex) * draggedHeight);
    for (let index = sourceIndex + 1; index <= finalIndex; index += 1) {
      offsets.set(keys[index], -draggedHeight);
    }
  } else if (sourceIndex > finalIndex) {
    offsets.set(draggedKey, (finalIndex - sourceIndex) * draggedHeight);
    for (let index = finalIndex; index < sourceIndex; index += 1) {
      offsets.set(keys[index], draggedHeight);
    }
  }
  return offsets;
}

function ActivePaneRows({
  id,
  group,
  tabTitle,
  tabActive,
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
  paneDrag,
  onPaneDropSlotChange,
  onPaneDragStart,
  onPaneDragEnd,
  actionMenuPortalContainer,
}: {
  id: string;
  group: SidebarPaneGroup;
  tabTitle: string;
  tabActive: boolean;
  running: ReadonlySet<string>;
  updated: ReadonlySet<string>;
  onSelectPane?: (tabKey: string, paneKey: string) => void;
  onRequestDelete: (key: string, label: string) => void;
  onRequestRename: (key: string, label: string) => void;
  onDetachPane?: (tabKey: string, paneKey: string) => void;
  onPromotePane?: (tabKey: string, paneKey: string) => void;
  moveTargets: Array<{ key: string; title: string }>;
  onAttachPane?: (
    paneKey: string,
    tabKey: string,
    beforePaneKey?: string | null,
  ) => void;
  deleteSelectionMode: boolean;
  selectedDeleteKeys: ReadonlySet<string>;
  onToggleDeleteSelection: (keys: string[]) => void;
  onBeginDeleteSelection: (keys: string[]) => void;
  paneDrag: PaneTabDragState | null;
  onPaneDropSlotChange: (slot: PaneDropSlot) => void;
  onPaneDragStart: (event: DragEvent<HTMLButtonElement>, pane: DraggedPane) => void;
  onPaneDragEnd: () => void;
  actionMenuPortalContainer?: HTMLElement | null;
}) {
  const { t } = useTranslation();
  const panes = group.panes;
  const paneKeys = panes.map((pane) => pane.key);
  const draggedPane = paneDrag?.item ?? null;
  const ownsDraggedPane = paneDrag?.origin === "pane"
    && draggedPane?.sourceTabKey === group.topicKey;
  const activeDropSlot = ownsDraggedPane && paneDrag?.slot?.tabKey === group.topicKey
    ? paneDrag.slot
    : null;
  const dragLayout = paneTabDragLayout(
    paneKeys,
    group.topicKey,
    paneDrag,
  );
  const commitPaneDrop = () => {
    if (!draggedPane || !activeDropSlot || !onAttachPane) {
      return;
    }
    onAttachPane(
      draggedPane.paneKey,
      group.topicKey,
      activeDropSlot.beforePaneKey,
    );
    onPaneDragEnd();
  };

  return (
    <ul
      id={id}
      aria-label={t("workbench.panesInTab", {
        defaultValue: "Panes in {{title}}",
        title: tabTitle,
      })}
      className={cn(
        "relative ms-3 me-0.5 mt-1 space-y-0.5 pb-0.5 ps-3 pe-0.5",
        "before:absolute before:bottom-1 before:start-1 before:top-0 before:w-px before:rounded-full before:bg-sidebar-foreground/15",
        "motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-top-1 motion-safe:duration-150",
      )}
      onDragOverCapture={(event) => {
        if (!activeDropSlot) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
      }}
      onDropCapture={(event) => {
        if (!draggedPane || !activeDropSlot || !onAttachPane) return;
        event.preventDefault();
        event.stopPropagation();
        commitPaneDrop();
      }}
    >
      {activeDropSlot && paneDrag && dragLayout.slotIndex >= 0 ? (
        <li
          key={`${activeDropSlot.tabKey}:${activeDropSlot.beforePaneKey ?? "end"}`}
          data-pane-snap-slot
          data-pane-snap-tab={group.topicKey}
          data-pane-snap-before={activeDropSlot.beforePaneKey ?? ""}
          aria-hidden="true"
          className="absolute end-0.5 start-3 top-0 z-[3] !mt-0 rounded-[0.65rem] bg-transparent"
          style={{
            height: `${paneDrag.height}px`,
            transform: `translateY(${dragLayout.slotIndex * (paneDrag.height + 2)}px)`,
          }}
        />
      ) : null}
      {panes.map((pane) => {
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
        const dragging = draggedPane?.paneKey === pane.key;
        const displaced = dragLayout.offsets.has(pane.key);

        return (
          <li
            key={pane.key}
            data-pane-dragging={dragging ? "true" : undefined}
            data-pane-displaced={displaced ? "true" : undefined}
            className={cn(
              "relative min-w-0 transition-transform duration-200 [transition-timing-function:cubic-bezier(0.2,0,0,1)] motion-reduce:transition-none",
              dragging ? "z-0" : displaced && "z-[2] rounded-[0.65rem] bg-sidebar",
            )}
            style={{
              transform: displaced
                ? `translateY(${dragLayout.offsets.get(pane.key)}px)`
                : undefined,
            }}
            onDragOver={(event) => {
              if (!draggedPane || !ownsDraggedPane || draggedPane.paneKey === pane.key) {
                return;
              }
              event.preventDefault();
              event.stopPropagation();
              event.dataTransfer.dropEffect = "move";
              const rect = event.currentTarget.getBoundingClientRect();
              onPaneDropSlotChange(paneDropSlotForRow(
                group.topicKey,
                paneKeys,
                draggedPane.paneKey,
                pane.key,
                event.clientY < rect.top + rect.height / 2 ? "before" : "after",
              ));
            }}
          >
            <div
              data-chat-row={pane.key}
              data-sidebar-pane={pane.key}
              className={cn(
                "group/pane flex min-h-8 min-w-0 items-center gap-1 rounded-[0.65rem] px-2 text-[13px]",
                SIDEBAR_SELECTION_ITEM_CLASS,
                active
                  ? "bg-sidebar-selected text-sidebar-accent-foreground"
                  : "text-sidebar-foreground/78 hover:bg-sidebar-foreground/[0.065] hover:text-sidebar-foreground dark:hover:bg-white/[0.08]",
                deleteSelectionMode && selected
                  && "bg-sidebar-accent/55 text-sidebar-accent-foreground",
                dragging
                  && "!bg-transparent !text-transparent !shadow-none [&_*]:!text-transparent",
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
                aria-label={dragging ? pane.title : undefined}
                title={pane.title}
                className={cn(
                  "flex min-w-0 flex-1 items-center gap-2 py-1 text-left font-medium leading-5",
                  deleteSelectionMode
                    ? "cursor-default"
                    : dragging ? "cursor-grabbing" : "cursor-grab active:cursor-grabbing",
                )}
              >
                {deleteSelectionMode ? (
                  <SelectionIndicator checked={selected} partial={false} />
                ) : null}
                {dragging ? null : (
                  <span className="min-w-0 flex-1 truncate">{pane.title}</span>
                )}
              </button>
              {!dragging ? <SessionActivityIndicator state={activityState} /> : null}
              {!deleteSelectionMode && !dragging ? <DropdownMenu modal={false}>
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
                  {pane.key !== group.topicKey && onDetachPane ? (
                    <DropdownMenuItem onSelect={() => onDetachPane(group.topicKey, pane.key)}>
                      <Unplug className="h-4 w-4 shrink-0" />
                      {t("workbench.detachPane", {
                        defaultValue: "Move {{title}} to a new tab",
                        title: pane.title,
                      })}
                    </DropdownMenuItem>
                  ) : null}
                  {pane.key !== group.topicKey && onAttachPane ? (
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
