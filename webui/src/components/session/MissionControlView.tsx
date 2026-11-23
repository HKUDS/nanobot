import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArchiveRestore,
  ChevronDown,
  Columns2,
  MoreHorizontal,
  PanelsTopLeft,
  Pencil,
  Pin,
  PinOff,
  Plus,
  Search,
  Square,
  SquareCheckBig,
  Trash2,
  Ungroup,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import type { SidebarDeleteItem } from "@/components/ChatList";
import {
  AutomationProtectedBadge,
  LiveElapsedBadge,
  MutedHandleBadge,
  SessionStatusDot,
  SplitGroupBadge,
  SubtlePinMark,
  ZenDoneCircle,
  useLiveClock,
} from "@/components/session/SessionVisuals";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { HoverHint } from "@/components/ui/hover-hint";
import {
  formatCompactRelativeTime,
  type DecoupledWorkbenchGroup,
  type EnrichedSession,
  type ProjectWorkspaceGroup,
  type SessionIntelligenceSnapshot,
} from "@/lib/session-intelligence";
import { cn } from "@/lib/utils";
import "./session-zen.css";

export type MissionControlTab = "open" | "done";

export interface MissionControlViewProps {
  intelligence: SessionIntelligenceSnapshot;
  activeKey: string | null;
  initialTab?: MissionControlTab;
  selectedProjectId?: string | null;
  onSelectedProjectChange?: (projectId: string | null) => void;
  onSelectSession: (key: string) => void;
  onSelectWorkbenchGroup: (tabKey: string) => void;
  onNewChat: () => void;
  onNewChatInProject: (projectPath: string, projectName: string) => void;
  onTogglePin: (key: string) => void;
  onArchiveMany: (keys: string[], archive: boolean) => void;
  onRequestDeleteMany: (items: SidebarDeleteItem[]) => void;
  onRequestRename: (key: string, title: string) => Promise<void>;
  onRequestRenameProject: (projectKey: string, label: string) => void;
  onRequestRenameTab?: (tabKey: string, label: string) => void;
  onCreateTab?: (paneKey: string) => void;
  onDissolveTab?: (tabKey: string) => void;
}

export function MissionControlView({
  intelligence,
  activeKey,
  initialTab = "open",
  selectedProjectId = null,
  onSelectedProjectChange,
  onSelectSession,
  onSelectWorkbenchGroup,
  onNewChat,
  onNewChatInProject,
  onTogglePin,
  onArchiveMany,
  onRequestDeleteMany,
  onRequestRename,
  onRequestRenameProject,
  onRequestRenameTab,
  onCreateTab,
  onDissolveTab,
}: MissionControlViewProps) {
  const { t, i18n } = useTranslation();
  const isZh = Boolean(i18n.resolvedLanguage?.startsWith("zh"));
  const [tab, setTab] = useState<MissionControlTab>(initialTab);
  const [localProjectFilter, setLocalProjectFilter] = useState<string | null>(selectedProjectId);
  const [cleanupExpanded, setCleanupExpanded] = useState(false);
  const [selectedCleanupKeys, setSelectedCleanupKeys] = useState<Set<string>>(() => new Set());
  const [doneFilter, setDoneFilter] = useState("");
  const [renamingKey, setRenamingKey] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [completingKeys, setCompletingKeys] = useState<Set<string>>(() => new Set());
  const [focusedKey, setFocusedKey] = useState<string | null>(null);
  const completionTimersRef = useRef<number[]>([]);

  useEffect(() => () => {
    for (const id of completionTimersRef.current) window.clearTimeout(id);
  }, []);

  useEffect(() => {
    setTab(initialTab);
  }, [initialTab]);

  useEffect(() => {
    setLocalProjectFilter(selectedProjectId);
  }, [selectedProjectId]);

  const projectFilter = onSelectedProjectChange ? selectedProjectId : localProjectFilter;
  const setProjectFilter = (next: string | null) => {
    setLocalProjectFilter(next);
    onSelectedProjectChange?.(next);
  };

  const nowMs = useLiveClock(intelligence.running.length > 0, 1000);

  const visibleProjects = useMemo(() => {
    const withOpen = intelligence.projects.filter((group) => group.openSessions.length > 0);
    if (!projectFilter) return withOpen;
    return withOpen.filter((group) => group.project.id === projectFilter);
  }, [intelligence.projects, projectFilter]);

  const filteredAttention = useMemo(() => {
    if (!projectFilter) return intelligence.attention;
    return intelligence.attention.filter((item) => item.project.id === projectFilter);
  }, [intelligence.attention, projectFilter]);

  const filteredCleanup = useMemo(() => {
    if (!projectFilter) return intelligence.cleanupCandidates;
    return intelligence.cleanupCandidates.filter((item) => item.project.id === projectFilter);
  }, [intelligence.cleanupCandidates, projectFilter]);

  const filteredWorkbenchGroups = useMemo(() => {
    if (!projectFilter) return intelligence.workbenchGroups;
    return intelligence.workbenchGroups.filter((group) =>
      group.panes.some((pane) => pane.project.id === projectFilter),
    );
  }, [intelligence.workbenchGroups, projectFilter]);

  const filteredArchived = useMemo(() => {
    const needle = doneFilter.trim().toLowerCase();
    return intelligence.archived.filter((item) => {
      if (projectFilter && item.project.id !== projectFilter) return false;
      if (!needle) return true;
      return (
        item.title.toLowerCase().includes(needle)
        || item.preview.toLowerCase().includes(needle)
        || item.project.name.toLowerCase().includes(needle)
        || (item.session.handle?.name.toLowerCase().includes(needle) ?? false)
      );
    });
  }, [doneFilter, intelligence.archived, projectFilter]);

  useEffect(() => {
    setSelectedCleanupKeys(new Set(filteredCleanup.map((item) => item.session.key)));
  }, [filteredCleanup]);

  const navigableKeys = useMemo(
    () => visibleProjects.flatMap((group) => group.openSessions.map((item) => item.session.key)),
    [visibleProjects],
  );

  // Tactile completion ritual: brief check & gentle slide before archiving
  const completeSessionWithRitual = useCallback((key: string) => {
    if (completingKeys.has(key)) return;
    setCompletingKeys((current) => new Set(current).add(key));
    const timer = window.setTimeout(() => {
      onArchiveMany([key], true);
      setCompletingKeys((current) => {
        const next = new Set(current);
        next.delete(key);
        return next;
      });
    }, 180);
    completionTimersRef.current.push(timer);
  }, [completingKeys, onArchiveMany]);

  // Smooth keyboard navigation (j/k or ArrowDown/ArrowUp, Enter to open, e to complete)
  useEffect(() => {
    if (tab !== "open" || renamingKey !== null) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) {
        return;
      }
      if (navigableKeys.length === 0) return;

      if (event.key === "ArrowDown" || event.key === "j") {
        event.preventDefault();
        setFocusedKey((current) => {
          const idx = current ? navigableKeys.indexOf(current) : -1;
          return navigableKeys[(idx + 1) % navigableKeys.length];
        });
      } else if (event.key === "ArrowUp" || event.key === "k") {
        event.preventDefault();
        setFocusedKey((current) => {
          const idx = current ? navigableKeys.indexOf(current) : 0;
          return navigableKeys[(idx - 1 + navigableKeys.length) % navigableKeys.length];
        });
      } else if (event.key === "Enter" && focusedKey && navigableKeys.includes(focusedKey)) {
        event.preventDefault();
        onSelectSession(focusedKey);
      } else if (event.key === "e" && focusedKey && navigableKeys.includes(focusedKey)) {
        const item = intelligence.byKey.get(focusedKey);
        if (item && item.session.projectLocked !== false) {
          event.preventDefault();
          completeSessionWithRitual(focusedKey);
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [completeSessionWithRitual, focusedKey, intelligence.byKey, navigableKeys, onSelectSession, renamingKey, tab]);

  const projectPills = useMemo(
    () => intelligence.projects.filter((group) =>
      tab === "open" ? group.openSessions.length > 0 : group.archivedSessions.length > 0,
    ),
    [intelligence.projects, tab],
  );

  const staleCount = filteredCleanup.filter((item) => item.cleanupReason === "stale").length;
  const quickCount = filteredCleanup.filter((item) => item.cleanupReason === "quick_chat").length;

  const beginInlineRename = (item: EnrichedSession) => {
    setRenamingKey(item.session.key);
    setRenameDraft(item.title);
  };

  const commitInlineRename = async (key: string) => {
    const trimmed = renameDraft.trim();
    setRenamingKey(null);
    if (!trimmed) return;
    await onRequestRename(key, trimmed).catch(() => {});
  };

  const toggleCleanupKey = (key: string) => {
    setSelectedCleanupKeys((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const summaryLine = useMemo(() => {
    const parts: string[] = [];
    if (intelligence.running.length > 0) {
      parts.push(isZh ? `${intelligence.running.length} 项推进中` : `${intelligence.running.length} running`);
    }
    if (intelligence.recovery.length > 0) {
      parts.push(isZh ? `${intelligence.recovery.length} 项等你确认` : `${intelligence.recovery.length} waiting for you`);
    }
    if (intelligence.updated.length > 0) {
      parts.push(isZh ? `${intelligence.updated.length} 项待验收` : `${intelligence.updated.length} ready`);
    }
    if (parts.length === 0) {
      return isZh
        ? `共 ${intelligence.open.length} 项在办，此刻一切平静`
        : `${intelligence.open.length} open · all quiet right now`;
    }
    return parts.join(" · ");
  }, [intelligence.open.length, intelligence.recovery.length, intelligence.running.length, intelligence.updated.length, isZh]);

  return (
    <div
      data-testid="mission-control-view"
      className="relative h-full min-h-0 w-full overflow-y-auto overscroll-contain bg-background"
    >
      <div className="mx-auto flex w-full max-w-[900px] flex-col gap-9 px-6 py-9 sm:px-10 sm:py-12">
        {/* Serene Editorial Header */}
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-0 space-y-1.5">
            <h1 className="text-[24px] font-medium tracking-[-0.02em] text-foreground">
              {isZh ? "工作台" : "Workspace"}
            </h1>
            <p className="text-[13px] text-muted-foreground/80">
              {summaryLine}
            </p>
          </div>

          <div className="flex items-center gap-4">
            {/* Minimal text tabs for Open / Done */}
            <div role="tablist" aria-label={isZh ? "会话状态" : "Session state"} className="flex items-center gap-4 text-[13px]">
              <button
                type="button"
                role="tab"
                aria-selected={tab === "open"}
                onClick={() => setTab("open")}
                className={cn(
                  "relative pb-1 transition-colors",
                  tab === "open"
                    ? "font-medium text-foreground after:absolute after:inset-x-0 after:bottom-0 after:h-[1.5px] after:bg-foreground"
                    : "text-muted-foreground/70 hover:text-foreground",
                )}
              >
                {isZh ? "在办" : "Open"}
                <span className="ml-1.5 text-[11.5px] tabular-nums opacity-55">{intelligence.open.length}</span>
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={tab === "done"}
                onClick={() => setTab("done")}
                className={cn(
                  "relative pb-1 transition-colors",
                  tab === "done"
                    ? "font-medium text-foreground after:absolute after:inset-x-0 after:bottom-0 after:h-[1.5px] after:bg-foreground"
                    : "text-muted-foreground/70 hover:text-foreground",
                )}
              >
                {isZh ? "已结单" : "Done"}
                <span className="ml-1.5 text-[11.5px] tabular-nums opacity-55">{intelligence.archived.length}</span>
              </button>
            </div>

            <button
              type="button"
              onClick={onNewChat}
              className="inline-flex h-8 items-center gap-1.5 rounded-full bg-foreground/[0.06] px-3.5 text-[12.5px] font-medium text-foreground transition-colors hover:bg-foreground/[0.11]"
            >
              <Plus className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
              <span>{t("sidebar.newChat")}</span>
            </button>
          </div>
        </header>

        {/* Quiet Underline Project Filter Bar */}
        {projectPills.length > 1 ? (
          <div
            role="tablist"
            aria-label={isZh ? "按项目筛选" : "Filter by project"}
            className="-mt-4 flex items-center gap-5 overflow-x-auto border-b border-border/45 text-[13px]"
          >
            <button
              type="button"
              role="tab"
              aria-selected={projectFilter === null}
              onClick={() => setProjectFilter(null)}
              className={cn(
                "relative shrink-0 pb-2.5 transition-colors",
                projectFilter === null
                  ? "font-medium text-foreground after:absolute after:inset-x-0 after:bottom-[-1px] after:h-[1.5px] after:bg-foreground"
                  : "text-muted-foreground/70 hover:text-foreground",
              )}
            >
              {isZh ? "全部" : "All"}
            </button>
            {projectPills.map((group) => {
              const selected = projectFilter === group.project.id;
              const count = tab === "open" ? group.openSessions.length : group.archivedSessions.length;
              const hasRecovery = tab === "open" && group.recoveryCount > 0;
              const hasRunning = tab === "open" && group.runningCount > 0;
              return (
                <button
                  key={group.project.id}
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  onClick={() => setProjectFilter(selected ? null : group.project.id)}
                  className={cn(
                    "relative inline-flex shrink-0 items-center gap-1.5 pb-2.5 transition-colors",
                    selected
                      ? "font-medium text-foreground after:absolute after:inset-x-0 after:bottom-[-1px] after:h-[1.5px] after:bg-foreground"
                      : "text-muted-foreground/70 hover:text-foreground",
                  )}
                >
                  {hasRecovery ? (
                    <span className="h-1.5 w-1.5 rounded-full bg-amber-500" aria-hidden />
                  ) : hasRunning ? (
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden />
                  ) : null}
                  <span className="max-w-[11rem] truncate">{group.project.name}</span>
                  <span className="text-[11.5px] tabular-nums opacity-50">{count}</span>
                </button>
              );
            })}
          </div>
        ) : null}

        {tab === "open" ? (
          <>
            {/* Section 1: Monochrome Quiet Attention Surface */}
            {filteredAttention.length > 0 ? (
              <section aria-labelledby="mc-attention-heading" className="space-y-3.5">
                <h2
                  id="mc-attention-heading"
                  className="text-[11.5px] font-medium tracking-[0.04em] text-muted-foreground/70"
                >
                  {isZh ? "此刻进行" : "Active now"}
                </h2>

                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {filteredAttention.map((item) => (
                    <AttentionCard
                      key={item.session.key}
                      item={item}
                      isActive={item.session.key === activeKey}
                      completing={completingKeys.has(item.session.key)}
                      nowMs={nowMs}
                      isZh={isZh}
                      locale={i18n.resolvedLanguage}
                      onOpen={() => onSelectSession(item.session.key)}
                      onDone={
                        item.attention === "updated" && item.session.projectLocked !== false
                          ? () => completeSessionWithRitual(item.session.key)
                          : undefined
                      }
                    />
                  ))}
                </div>
              </section>
            ) : null}

            {/* Section 2: Decoupled Split Workspaces — calm horizontal strip */}
            {filteredWorkbenchGroups.length > 0 ? (
              <section aria-labelledby="mc-splits-heading" className="space-y-3">
                <h2
                  id="mc-splits-heading"
                  className="text-[11.5px] font-medium tracking-[0.04em] text-muted-foreground/70"
                >
                  {isZh ? "分屏组合" : "Split workspaces"}
                </h2>
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  {filteredWorkbenchGroups.map((group) => (
                    <SplitWorkspaceCard
                      key={group.tabKey}
                      group={group}
                      isZh={isZh}
                      onOpen={() => onSelectWorkbenchGroup(group.tabKey)}
                      onSelectPane={onSelectSession}
                      onRename={onRequestRenameTab ? () => onRequestRenameTab(group.tabKey, group.title) : undefined}
                      onDissolve={onDissolveTab ? () => onDissolveTab(group.tabKey) : undefined}
                    />
                  ))}
                </div>
              </section>
            ) : null}

            {/* Section 3: Gentle Hygiene Whisper (borderless editorial strip + smooth accordion) */}
            {filteredCleanup.length > 0 ? (
              <section
                aria-label={isZh ? "智能清理建议" : "Smart cleanup suggestions"}
                className="rounded-2xl bg-foreground/[0.025] px-4 py-3 dark:bg-white/[0.025]"
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-[13px] text-foreground/85">
                      {isZh
                        ? `有 ${filteredCleanup.length} 条会话已沉睡多日`
                        : `${filteredCleanup.length} quiet sessions look ready to archive`}
                      <span className="ml-2 text-[12px] text-muted-foreground/70">
                        {isZh
                          ? [
                              staleCount > 0 ? `${staleCount} 条超 7 天未动` : null,
                              quickCount > 0 ? `${quickCount} 条短对话` : null,
                            ].filter(Boolean).join(" · ")
                          : [
                              staleCount > 0 ? `${staleCount} idle 7d+` : null,
                              quickCount > 0 ? `${quickCount} quick chats` : null,
                            ].filter(Boolean).join(" · ")}
                      </span>
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-3 text-[12.5px]">
                    <button
                      type="button"
                      onClick={() => setCleanupExpanded((open) => !open)}
                      className="inline-flex items-center gap-1 text-muted-foreground/80 transition-colors hover:text-foreground"
                    >
                      <span>{cleanupExpanded ? (isZh ? "收起" : "Hide") : (isZh ? "查看明细" : "Review")}</span>
                      <ChevronDown
                        className={cn("h-3.5 w-3.5 transition-transform duration-200", cleanupExpanded && "rotate-180")}
                        aria-hidden
                      />
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        onArchiveMany(filteredCleanup.map((item) => item.session.key), true);
                        setCleanupExpanded(false);
                      }}
                      className="font-medium text-foreground/85 transition-colors hover:text-foreground"
                    >
                      {isZh ? "全部结单归档" : "Archive all"}
                    </button>
                  </div>
                </div>

                <div className="zen-disclosure" data-collapsed={!cleanupExpanded}>
                  <div className="zen-disclosure-inner">
                    <div className="mt-3 border-t border-border/35 pt-2.5">
                      <ul className="max-h-56 divide-y divide-border/25 overflow-y-auto">
                        {filteredCleanup.map((item) => {
                          const checked = selectedCleanupKeys.has(item.session.key);
                          return (
                            <li key={item.session.key} className="flex items-center gap-3 py-2 text-[13px]">
                              <button
                                type="button"
                                onClick={() => toggleCleanupKey(item.session.key)}
                                aria-pressed={checked}
                                className="inline-flex h-5 w-5 shrink-0 items-center justify-center text-muted-foreground/70 transition-colors hover:text-foreground"
                              >
                                {checked ? (
                                  <SquareCheckBig className="h-3.5 w-3.5 text-foreground/85" aria-hidden />
                                ) : (
                                  <Square className="h-3.5 w-3.5" aria-hidden />
                                )}
                              </button>
                              <button
                                type="button"
                                onClick={() => onSelectSession(item.session.key)}
                                className="flex min-w-0 flex-1 items-center gap-2 text-left"
                              >
                                <span className="shrink-0 text-[12px] text-muted-foreground/65">
                                  {item.project.name}
                                </span>
                                <span className="min-w-0 flex-1 truncate text-foreground/90">
                                  {item.title}
                                </span>
                              </button>
                              <span className="shrink-0 text-[11.5px] text-muted-foreground/65">
                                {item.cleanupReason === "stale"
                                  ? (isZh ? "久未活跃" : "7d+ idle")
                                  : (isZh ? "短对话" : "Quick")}
                              </span>
                              <span className="w-14 shrink-0 text-right text-[11.5px] tabular-nums text-muted-foreground/60">
                                {formatCompactRelativeTime(item.updatedMs, i18n.resolvedLanguage, nowMs)}
                              </span>
                            </li>
                          );
                        })}
                      </ul>
                      <div className="mt-2.5 flex items-center justify-between pt-2 text-[12px] text-muted-foreground/70">
                        <span>{isZh ? "运行中、钉住和含定时任务的会话已自动跳过" : "Running, pinned & automated sessions are protected"}</span>
                        <button
                          type="button"
                          disabled={selectedCleanupKeys.size === 0}
                          onClick={() => {
                            onArchiveMany(Array.from(selectedCleanupKeys), true);
                            setCleanupExpanded(false);
                          }}
                          className="rounded-full bg-foreground/[0.08] px-3 py-1 font-medium text-foreground transition-colors hover:bg-foreground/[0.14] disabled:opacity-35"
                        >
                          {isZh
                            ? `归档所选 (${selectedCleanupKeys.size})`
                            : `Archive selected (${selectedCleanupKeys.size})`}
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              </section>
            ) : null}

            {/* Section 4: Borderless Editorial Project Lists */}
            {visibleProjects.length === 0 ? (
              <div className="flex flex-col items-center justify-center gap-2.5 py-20 text-center">
                <p className="text-[15px] font-medium text-foreground/85">
                  {isZh ? "一切清朗，暂无待办" : "Clear horizon"}
                </p>
                <p className="max-w-xs text-[13px] text-muted-foreground/75">
                  {isZh
                    ? "随时开启一段新对话，或切到「已结单」回看沉淀。"
                    : "Start a fresh conversation or revisit completed work in Done."}
                </p>
              </div>
            ) : (
              <div className="space-y-9 pb-12">
                {visibleProjects.map((group) => (
                  <ProjectSection
                    key={group.project.id}
                    group={group}
                    activeKey={activeKey}
                    focusedKey={focusedKey}
                    completingKeys={completingKeys}
                    nowMs={nowMs}
                    isZh={isZh}
                    locale={i18n.resolvedLanguage}
                    renamingKey={renamingKey}
                    renameDraft={renameDraft}
                    onRenameDraftChange={setRenameDraft}
                    onBeginRename={beginInlineRename}
                    onCommitRename={commitInlineRename}
                    onCancelRename={() => setRenamingKey(null)}
                    onSelectSession={onSelectSession}
                    onNewChatInProject={onNewChatInProject}
                    onNewChat={onNewChat}
                    onTogglePin={onTogglePin}
                    onCompleteSession={completeSessionWithRitual}
                    onArchiveMany={onArchiveMany}
                    onRequestDeleteMany={onRequestDeleteMany}
                    onRequestRenameProject={onRequestRenameProject}
                    onCreateTab={onCreateTab}
                  />
                ))}
              </div>
            )}
          </>
        ) : (
          /* Serene Done / Archived View */
          <section className="space-y-5 pb-12">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="relative min-w-[14rem] max-w-xs flex-1">
                <Search className="pointer-events-none absolute left-0 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground/60" aria-hidden />
                <input
                  value={doneFilter}
                  onChange={(event) => setDoneFilter(event.target.value)}
                  placeholder={isZh ? "筛选已结单..." : "Filter completed..."}
                  className="h-8 w-full border-b border-border/55 bg-transparent pl-6 pr-2 text-[13px] text-foreground outline-none placeholder:text-muted-foreground/60 focus:border-foreground/45"
                />
              </div>
              {filteredArchived.length > 0 ? (
                <button
                  type="button"
                  onClick={() => onArchiveMany(filteredArchived.map((item) => item.session.key), false)}
                  className="inline-flex items-center gap-1.5 text-[12px] text-muted-foreground/75 transition-colors hover:text-foreground"
                >
                  <ArchiveRestore className="h-3.5 w-3.5" aria-hidden />
                  <span>{isZh ? `全部恢复 (${filteredArchived.length})` : `Restore all (${filteredArchived.length})`}</span>
                </button>
              ) : null}
            </div>

            {filteredArchived.length === 0 ? (
              <div className="py-16 text-center">
                <p className="text-[14px] text-foreground/75">
                  {isZh ? "暂无已结单的会话" : "Nothing archived yet"}
                </p>
              </div>
            ) : (
              <ul className="divide-y divide-border/35">
                {filteredArchived.map((item) => (
                  <li
                    key={item.session.key}
                    className="group flex items-center gap-3.5 py-3 transition-colors"
                  >
                    <button
                      type="button"
                      onClick={() => onSelectSession(item.session.key)}
                      className="flex min-w-0 flex-1 flex-col gap-0.5 text-left"
                    >
                      <div className="flex min-w-0 items-center gap-2.5">
                        <span className="shrink-0 text-[12px] text-muted-foreground/60">
                          {item.project.name}
                        </span>
                        <span className="min-w-0 flex-1 truncate text-[13.5px] text-foreground/75 transition-colors group-hover:text-foreground">
                          {item.title}
                        </span>
                        <MutedHandleBadge handle={item.session.handle} />
                        <AutomationProtectedBadge count={item.automationCount} />
                      </div>
                      {item.preview ? (
                        <p className="truncate text-[12px] text-muted-foreground/60">{item.preview}</p>
                      ) : null}
                    </button>

                    <div className="relative flex shrink-0 items-center">
                      <span className="text-[12px] tabular-nums text-muted-foreground/60 transition-opacity duration-150 group-hover:opacity-0">
                        {formatCompactRelativeTime(item.updatedMs, i18n.resolvedLanguage, nowMs)}
                      </span>
                      <div className="pointer-events-none absolute right-0 flex translate-x-1 items-center gap-1 opacity-0 transition-all duration-150 group-hover:pointer-events-auto group-hover:translate-x-0 group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:translate-x-0 group-focus-within:opacity-100">
                        <button
                          type="button"
                          onClick={() => onArchiveMany([item.session.key], false)}
                          className="inline-flex h-7 items-center gap-1 rounded-lg px-2 text-[12px] text-muted-foreground hover:bg-foreground/[0.05] hover:text-foreground"
                        >
                          <ArchiveRestore className="h-3.5 w-3.5" aria-hidden />
                          <span>{isZh ? "恢复" : "Restore"}</span>
                        </button>
                        <button
                          type="button"
                          aria-label={t("chat.delete")}
                          onClick={() => onRequestDeleteMany([{ key: item.session.key, label: item.title }])}
                          className="inline-flex h-7 w-7 items-center justify-center rounded-lg text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                        >
                          <Trash2 className="h-3.5 w-3.5" aria-hidden />
                        </button>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}
      </div>
    </div>
  );
}

/**
 * Pure Monochrome Zen Attention Card:
 * Zero colored card fills, zero redundant buttons — the entire card is a calm tactile surface
 * illuminated only by a single point of semantic light.
 */
function AttentionCard({
  item,
  isActive,
  completing,
  nowMs,
  isZh,
  locale,
  onOpen,
  onDone,
}: {
  item: EnrichedSession;
  isActive: boolean;
  completing: boolean;
  nowMs: number;
  isZh: boolean;
  locale?: string;
  onOpen: () => void;
  onDone?: () => void;
}) {
  const statusText = item.attention === "recovery"
    ? (isZh ? "等你确认" : "Waiting")
    : item.attention === "running"
      ? (isZh ? "运行中" : "Running")
      : (isZh ? "新结果" : "Ready");

  return (
    <article
      className={cn(
        "group relative flex flex-col justify-between gap-3 rounded-2xl bg-foreground/[0.024] p-4 ring-1 ring-border/45 transition-all duration-200 hover:bg-foreground/[0.042] hover:ring-border/80 dark:bg-white/[0.028] dark:hover:bg-white/[0.048]",
        isActive && "ring-foreground/25",
        completing && "zen-completing",
      )}
    >
      <div className="space-y-2">
        <div className="flex items-center justify-between gap-2 text-[11.5px]">
          <span className="inline-flex items-center gap-1.5 text-muted-foreground/85">
            <SessionStatusDot state={item.attention} />
            <span className="font-medium text-foreground/80">{statusText}</span>
            {item.attention === "running" ? (
              <LiveElapsedBadge startedAtSec={item.session.runStartedAt} nowMs={nowMs} className="ml-0.5" />
            ) : null}
          </span>
          <span className="max-w-[8.5rem] truncate text-muted-foreground/65">
            {item.project.name}
          </span>
        </div>

        <button
          type="button"
          onClick={onOpen}
          className="block w-full text-left focus-visible:outline-none"
        >
          <h3 className="line-clamp-2 text-[14px] font-medium leading-[1.45] text-foreground">
            {item.title}
          </h3>
          {item.preview ? (
            <p className="mt-1 line-clamp-1 text-[12px] leading-relaxed text-muted-foreground/75">
              {item.preview}
            </p>
          ) : null}
        </button>
      </div>

      <div className="flex h-5 items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          {item.attention !== "running" ? (
            <span className="text-[11.5px] tabular-nums text-muted-foreground/60">
              {formatCompactRelativeTime(item.updatedMs, locale, nowMs)}
            </span>
          ) : null}
          <MutedHandleBadge handle={item.session.handle} />
          <AutomationProtectedBadge count={item.automationCount} compact />
        </div>

        {onDone ? (
          <div className="opacity-55 transition-opacity duration-150 group-hover:opacity-100 group-focus-within:opacity-100">
            <ZenDoneCircle
              completed={completing}
              label={isZh ? `结单：${item.title}` : `Done: ${item.title}`}
              onClick={onDone}
            />
          </div>
        ) : null}
      </div>
    </article>
  );
}

function SplitWorkspaceCard({
  group,
  isZh,
  onOpen,
  onSelectPane,
  onRename,
  onDissolve,
}: {
  group: DecoupledWorkbenchGroup;
  isZh: boolean;
  onOpen: () => void;
  onSelectPane: (key: string) => void;
  onRename?: () => void;
  onDissolve?: () => void;
}) {
  return (
    <div className="group flex flex-col gap-2.5 rounded-2xl bg-foreground/[0.022] p-4 ring-1 ring-border/45 transition-all duration-200 hover:bg-foreground/[0.038] hover:ring-border/75 dark:bg-white/[0.025]">
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={onOpen}
          className="flex min-w-0 items-center gap-2 text-left"
        >
          <Columns2 className="h-3.5 w-3.5 shrink-0 text-muted-foreground/65" strokeWidth={1.75} aria-hidden />
          <span className="truncate text-[13.5px] font-medium text-foreground">{group.title}</span>
          <span className="text-[11.5px] text-muted-foreground/60">
            {isZh ? `${group.panes.length} 栏` : `${group.panes.length} panes`}
          </span>
        </button>

        {onRename || onDissolve ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                aria-label={group.title}
                className="inline-flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground/60 opacity-0 transition-opacity hover:bg-foreground/[0.05] hover:text-foreground group-hover:opacity-100 focus-visible:opacity-100"
              >
                <MoreHorizontal className="h-3.5 w-3.5" aria-hidden />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-40">
              {onRename ? (
                <DropdownMenuItem onSelect={onRename}>
                  <Pencil className="h-3.5 w-3.5" aria-hidden />
                  {isZh ? "重命名分屏组" : "Rename split"}
                </DropdownMenuItem>
              ) : null}
              {onDissolve ? (
                <DropdownMenuItem onSelect={onDissolve}>
                  <Ungroup className="h-3.5 w-3.5" aria-hidden />
                  {isZh ? "拆分为独立会话" : "Dissolve split"}
                </DropdownMenuItem>
              ) : null}
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </div>

      <div className="flex flex-col gap-1">
        {group.panes.map((pane) => (
          <button
            key={pane.session.key}
            type="button"
            onClick={() => onSelectPane(pane.session.key)}
            className="flex min-w-0 items-center gap-2 rounded-lg px-2 py-1 text-left text-[12.5px] transition-colors hover:bg-foreground/[0.04]"
          >
            <SessionStatusDot state={pane.attention} size="sm" />
            <span className="shrink-0 text-[11.5px] text-muted-foreground/65">{pane.project.name}</span>
            <span aria-hidden className="text-foreground/15">/</span>
            <span className="min-w-0 flex-1 truncate text-foreground/85">{pane.title}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function ProjectSection({
  group,
  activeKey,
  focusedKey,
  completingKeys,
  nowMs,
  isZh,
  locale,
  renamingKey,
  renameDraft,
  onRenameDraftChange,
  onBeginRename,
  onCommitRename,
  onCancelRename,
  onSelectSession,
  onNewChatInProject,
  onNewChat,
  onTogglePin,
  onCompleteSession,
  onArchiveMany,
  onRequestDeleteMany,
  onRequestRenameProject,
  onCreateTab,
}: {
  group: ProjectWorkspaceGroup;
  activeKey: string | null;
  focusedKey: string | null;
  completingKeys: ReadonlySet<string>;
  nowMs: number;
  isZh: boolean;
  locale?: string;
  renamingKey: string | null;
  renameDraft: string;
  onRenameDraftChange: (value: string) => void;
  onBeginRename: (item: EnrichedSession) => void;
  onCommitRename: (key: string) => Promise<void>;
  onCancelRename: () => void;
  onSelectSession: (key: string) => void;
  onNewChatInProject: (projectPath: string, projectName: string) => void;
  onNewChat: () => void;
  onTogglePin: (key: string) => void;
  onCompleteSession: (key: string) => void;
  onArchiveMany: (keys: string[], archive: boolean) => void;
  onRequestDeleteMany: (items: SidebarDeleteItem[]) => void;
  onRequestRenameProject: (projectKey: string, label: string) => void;
  onCreateTab?: (paneKey: string) => void;
}) {
  const { t } = useTranslation();
  const { project } = group;

  return (
    <section aria-label={project.name} className="group/section space-y-1.5">
      {/* Hairline Editorial Project Header */}
      <div className="flex items-center justify-between gap-2 border-b border-border/40 pb-2">
        <div className="flex min-w-0 items-center gap-2.5">
          <h2 className="truncate text-[13.5px] font-semibold tracking-[-0.01em] text-foreground/90">
            {project.name}
          </h2>
          <span className="text-[12px] tabular-nums text-muted-foreground/55">
            {group.openSessions.length}
          </span>
          {!project.isGeneral && project.path ? (
            <span className="hidden max-w-[18rem] truncate font-mono text-[11px] text-muted-foreground/45 md:inline">
              {project.path}
            </span>
          ) : null}
          {group.recoveryCount > 0 ? (
            <span className="inline-flex items-center gap-1 text-[11.5px] text-amber-600/90 dark:text-amber-400/90">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-500" aria-hidden />
              <span className="tabular-nums">{group.recoveryCount}</span>
            </span>
          ) : null}
          {group.runningCount > 0 ? (
            <span className="inline-flex items-center gap-1 text-[11.5px] text-emerald-700/90 dark:text-emerald-300/90">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden />
              <span className="tabular-nums">{group.runningCount}</span>
            </span>
          ) : null}
        </div>

        {/* Quiet Project Actions — awaken gently on section hover */}
        <div className="flex shrink-0 items-center gap-2 opacity-65 transition-opacity duration-150 group-hover/section:opacity-100 focus-within:opacity-100">
          {group.cleanupCandidates.length > 0 ? (
            <button
              type="button"
              onClick={() => onArchiveMany(group.cleanupCandidates.map((item) => item.session.key), true)}
              className="text-[11.5px] text-muted-foreground/75 transition-colors hover:text-foreground"
            >
              {isZh
                ? `清理空闲 (${group.cleanupCandidates.length})`
                : `Clean idle (${group.cleanupCandidates.length})`}
            </button>
          ) : null}
          <HoverHint content={isZh ? `在 ${project.name} 新建` : `New in ${project.name}`} side="top">
            <button
              type="button"
              aria-label={isZh ? `在 ${project.name} 新建` : `New in ${project.name}`}
              onClick={() => {
                if (!project.isGeneral && project.path) {
                  onNewChatInProject(project.path, project.name);
                } else {
                  onNewChat();
                }
              }}
              className="inline-flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground/75 transition-colors hover:bg-foreground/[0.05] hover:text-foreground"
            >
              <Plus className="h-3.5 w-3.5" aria-hidden />
            </button>
          </HoverHint>
          {!project.isGeneral && project.key ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  aria-label={t("chat.actions", { title: project.name })}
                  className="inline-flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground/75 transition-colors hover:bg-foreground/[0.05] hover:text-foreground"
                >
                  <MoreHorizontal className="h-3.5 w-3.5" aria-hidden />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-44">
                <DropdownMenuItem onSelect={() => onRequestRenameProject(project.key!, project.name)}>
                  <Pencil className="h-3.5 w-3.5" aria-hidden />
                  {t("chat.rename")}
                </DropdownMenuItem>
                {group.openSessions.some((item) => item.session.projectLocked !== false) ? (
                  <DropdownMenuItem
                    onSelect={() => onArchiveMany(
                      group.openSessions
                        .filter((item) => item.session.projectLocked !== false)
                        .map((item) => item.session.key),
                      true,
                    )}
                  >
                    {isZh ? "归档本项目全部会话" : "Archive all in project"}
                  </DropdownMenuItem>
                ) : null}
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null}
        </div>
      </div>

      {/* Borderless Editorial Rows */}
      <ul className="space-y-0.5 pt-1">
        {group.openSessions.map((item) => {
          const isCurrent = item.session.key === activeKey;
          const isFocused = item.session.key === focusedKey;
          const isRenaming = renamingKey === item.session.key;
          const completing = completingKeys.has(item.session.key);
          const canArchive = item.session.projectLocked !== false;

          return (
            <li key={item.session.key}>
              <div
                data-mission-session-row={item.session.key}
                className={cn(
                  "group relative -mx-3 flex items-center gap-3.5 rounded-xl px-3 py-3 transition-all duration-150 hover:bg-foreground/[0.032] dark:hover:bg-white/[0.035]",
                  isCurrent && "bg-foreground/[0.038]",
                  isFocused && "ring-1 ring-foreground/20",
                  completing && "zen-completing",
                )}
              >
                <SessionStatusDot state={item.attention} />

                <div className="min-w-0 flex-1">
                  {isRenaming ? (
                    <input
                      value={renameDraft}
                      autoFocus
                      onChange={(event) => onRenameDraftChange(event.target.value)}
                      onBlur={() => { void onCommitRename(item.session.key); }}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          void onCommitRename(item.session.key);
                        } else if (event.key === "Escape") {
                          event.preventDefault();
                          onCancelRename();
                        }
                      }}
                      className="h-7 w-full max-w-md border-b border-foreground/40 bg-transparent px-0.5 text-[14px] font-medium text-foreground outline-none"
                    />
                  ) : (
                    <button
                      type="button"
                      onClick={() => onSelectSession(item.session.key)}
                      className="block w-full min-w-0 text-left focus-visible:outline-none"
                    >
                      <div className="flex min-w-0 items-center gap-2">
                        <span className="min-w-0 truncate text-[14px] font-normal leading-snug text-foreground group-hover:text-foreground">
                          {item.title}
                        </span>
                        {item.pinned ? <SubtlePinMark /> : null}
                        <MutedHandleBadge handle={item.session.handle} />
                        <AutomationProtectedBadge count={item.automationCount} />
                        <SplitGroupBadge title={item.workbenchTabTitle} />
                      </div>
                      {item.preview && item.preview !== item.title ? (
                        <p className="mt-0.5 truncate text-[12px] leading-relaxed text-muted-foreground/65">
                          {item.preview}
                        </p>
                      ) : null}
                    </button>
                  )}
                </div>

                {/* Smooth cross-fade between calm timestamp and tactile Done circle + menu */}
                {!isRenaming ? (
                  <div className="relative flex h-7 shrink-0 items-center">
                    <div className="flex items-center gap-2 transition-opacity duration-150 group-hover:opacity-0 group-focus-within:opacity-0">
                      {item.attention === "running" ? (
                        <LiveElapsedBadge startedAtSec={item.session.runStartedAt} nowMs={nowMs} />
                      ) : (
                        <span className="text-[12px] tabular-nums text-muted-foreground/55">
                          {formatCompactRelativeTime(item.updatedMs, locale, nowMs)}
                        </span>
                      )}
                    </div>

                    <div className="pointer-events-none absolute right-0 flex translate-x-1.5 items-center gap-1.5 opacity-0 transition-all duration-150 group-hover:pointer-events-auto group-hover:translate-x-0 group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:translate-x-0 group-focus-within:opacity-100">
                      {canArchive ? (
                        <ZenDoneCircle
                          completed={completing}
                          label={isZh ? `结单：${item.title}` : `Done: ${item.title}`}
                          onClick={() => onCompleteSession(item.session.key)}
                        />
                      ) : null}

                      <HoverHint content={item.pinned ? t("chat.unpin") : t("chat.pin")} side="top">
                        <button
                          type="button"
                          aria-label={item.pinned ? t("chat.unpin") : t("chat.pin")}
                          onClick={() => onTogglePin(item.session.key)}
                          className="inline-flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground/70 transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                        >
                          {item.pinned ? <PinOff className="h-3.5 w-3.5" aria-hidden /> : <Pin className="h-3.5 w-3.5" aria-hidden />}
                        </button>
                      </HoverHint>

                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <button
                            type="button"
                            aria-label={t("chat.actions", { title: item.title })}
                            className="inline-flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground/70 transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                          >
                            <MoreHorizontal className="h-3.5 w-3.5" aria-hidden />
                          </button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-44">
                          <DropdownMenuItem onSelect={() => onBeginRename(item)}>
                            <Pencil className="h-3.5 w-3.5" aria-hidden />
                            {t("chat.rename")}
                          </DropdownMenuItem>
                          {onCreateTab && !item.workbenchTabKey ? (
                            <DropdownMenuItem onSelect={() => onCreateTab(item.session.key)}>
                              <PanelsTopLeft className="h-3.5 w-3.5" aria-hidden />
                              {t("workbench.createGroup")}
                            </DropdownMenuItem>
                          ) : null}
                          <DropdownMenuSeparator />
                          <DropdownMenuItem
                            tone="destructive"
                            onSelect={() => onRequestDeleteMany([{ key: item.session.key, label: item.title }])}
                          >
                            <Trash2 className="h-3.5 w-3.5" aria-hidden />
                            {t("chat.delete")}
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                  </div>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
