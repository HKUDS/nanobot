import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Archive,
  ArchiveRestore,
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
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import type { SidebarDeleteItem } from "@/components/ChatList";
import {
  AutomationProtectedBadge,
  LiveElapsedBadge,
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
import { hasAnyOverlayMounted } from "@/lib/dom-overlays";
import {
  formatCompactRelativeTime,
  type DecoupledWorkbenchGroup,
  type EnrichedSession,
  type ProjectWorkspaceGroup,
  type SessionIntelligenceSnapshot,
} from "@/lib/session-intelligence";
import { cn } from "@/lib/utils";
import "./session-zen.css";

export type MissionControlTab = "open" | "clean" | "done";

export interface MissionControlViewProps {
  intelligence: SessionIntelligenceSnapshot;
  activeKey: string | null;
  initialTab?: "open" | "done";
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
  const [selectedCleanupKeys, setSelectedCleanupKeys] = useState<Set<string>>(() => new Set());
  const [doneFilter, setDoneFilter] = useState("");
  const [renamingKey, setRenamingKey] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [completingKeys, setCompletingKeys] = useState<Set<string>>(() => new Set());
  const [focusedKey, setFocusedKey] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
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
  const setProjectFilter = useCallback((next: string | null) => {
    setLocalProjectFilter(next);
    onSelectedProjectChange?.(next);
  }, [onSelectedProjectChange]);

  const selectedProject = useMemo(
    () => (projectFilter ? intelligence.projects.find((group) => group.project.id === projectFilter) ?? null : null),
    [intelligence.projects, projectFilter],
  );

  useEffect(() => {
    if (projectFilter && !selectedProject) {
      setProjectFilter(null);
    }
  }, [projectFilter, selectedProject, setProjectFilter]);

  const nowMs = useLiveClock(intelligence.running.length > 0, 1000);

  // Live items (recovery + running) get the quiet top grid ONLY in "All projects" view.
  // They are excluded from the project list below so NO session ever renders twice!
  const liveNowItems = useMemo(() => {
    if (projectFilter) return [];
    return [...intelligence.recovery, ...intelligence.running];
  }, [intelligence.recovery, intelligence.running, projectFilter]);

  const liveNowKeySet = useMemo(
    () => new Set(liveNowItems.map((item) => item.session.key)),
    [liveNowItems],
  );

  const visibleProjects = useMemo(() => {
    const base = projectFilter
      ? intelligence.projects.filter((group) => group.project.id === projectFilter)
      : intelligence.projects;
    return base
      .map((group) => ({
        ...group,
        openSessions: projectFilter
          ? group.openSessions
          : group.openSessions.filter((item) => !liveNowKeySet.has(item.session.key)),
      }))
      .filter((group) => group.openSessions.length > 0);
  }, [intelligence.projects, liveNowKeySet, projectFilter]);

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

  const projectScopedArchived = useMemo(() => {
    if (!projectFilter) return intelligence.archived;
    return intelligence.archived.filter((item) => item.project.id === projectFilter);
  }, [intelligence.archived, projectFilter]);

  const filteredArchived = useMemo(() => {
    const needle = doneFilter.trim().toLowerCase();
    if (!needle) return projectScopedArchived;
    return projectScopedArchived.filter((item) => (
      item.title.toLowerCase().includes(needle)
      || item.project.name.toLowerCase().includes(needle)
      || (item.session.handle?.name.toLowerCase().includes(needle) ?? false)
    ));
  }, [doneFilter, projectScopedArchived]);

  useEffect(() => {
    setSelectedCleanupKeys(new Set(filteredCleanup.map((item) => item.session.key)));
  }, [filteredCleanup]);

  // Auto-return to Open if the user cleans out the last candidate while on Clean tab
  useEffect(() => {
    if (tab === "clean" && filteredCleanup.length === 0) setTab("open");
  }, [filteredCleanup.length, tab]);

  const navigableKeys = useMemo(
    () => [
      ...liveNowItems.map((item) => item.session.key),
      ...visibleProjects.flatMap((group) => group.openSessions.map((item) => item.session.key)),
    ],
    [liveNowItems, visibleProjects],
  );

  useEffect(() => {
    if (tab !== "open") {
      setFocusedKey(null);
      return;
    }
    setFocusedKey((current) => (current && navigableKeys.includes(current) ? current : null));
  }, [navigableKeys, tab]);

  useEffect(() => {
    if (!focusedKey || !containerRef.current) return;
    const rows = containerRef.current.querySelectorAll<HTMLElement>("[data-mission-session-row]");
    for (const row of rows) {
      if (row.getAttribute("data-mission-session-row") === focusedKey) {
        if (typeof row.scrollIntoView === "function") {
          const reducedMotion = typeof window !== "undefined"
            && typeof window.matchMedia === "function"
            && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
          row.scrollIntoView({ block: "nearest", behavior: reducedMotion ? "auto" : "smooth" });
        }
        break;
      }
    }
  }, [focusedKey]);

  const completeSessionWithRitual = useCallback((key: string) => {
    if (completingKeys.has(key)) return;
    if (focusedKey === key) {
      const idx = navigableKeys.indexOf(key);
      if (idx !== -1) {
        const nextKey = navigableKeys[idx + 1] ?? navigableKeys[idx - 1] ?? null;
        setFocusedKey(nextKey === key ? null : nextKey);
      }
    }
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
  }, [completingKeys, focusedKey, navigableKeys, onArchiveMany]);

  useEffect(() => {
    if (tab !== "open" || renamingKey !== null) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
      if (hasAnyOverlayMounted()) return;
      const target = event.target as HTMLElement | null;
      if (
        target
        && (
          target.tagName === "INPUT"
          || target.tagName === "TEXTAREA"
          || target.tagName === "SELECT"
          || target.isContentEditable
        )
      ) {
        return;
      }
      if (event.key === "Escape") {
        if (focusedKey !== null) {
          event.preventDefault();
          setFocusedKey(null);
        }
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
        if (
          item
          && item.session.projectLocked !== false
          && item.attention !== "running"
          && item.attention !== "recovery"
        ) {
          event.preventDefault();
          completeSessionWithRitual(focusedKey);
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [completeSessionWithRitual, focusedKey, intelligence.byKey, navigableKeys, onSelectSession, renamingKey, tab]);

  const projectTabs = useMemo(
    () => intelligence.projects.filter((group) => {
      if (group.project.id === projectFilter) return true;
      if (tab === "done") return group.archivedSessions.length > 0;
      if (tab === "clean") return group.cleanupCandidates.length > 0;
      return group.openSessions.length > 0;
    }),
    [intelligence.projects, projectFilter, tab],
  );

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

  const allCleanupSelected = filteredCleanup.length > 0 && selectedCleanupKeys.size === filteredCleanup.length;

  const handleEmptyNewChat = () => {
    if (selectedProject && !selectedProject.project.isGeneral && selectedProject.project.path) {
      onNewChatInProject(selectedProject.project.path, selectedProject.project.name);
      return;
    }
    onNewChat();
  };

  return (
    <div
      ref={containerRef}
      data-testid="mission-control-view"
      className="zen-surface-enter relative h-full min-h-0 w-full overflow-y-auto overscroll-contain bg-background"
    >
      <div className="mx-auto flex w-full max-w-[780px] flex-col gap-9 px-5 pb-16 pt-6 sm:gap-10 sm:px-10 sm:pt-11">
        {/* Single Quiet Navigation Rail: Projects on left, Lifecycle on right — zero filler copy */}
        <header className="flex flex-col gap-2.5 border-b border-border/40 pb-3 sm:flex-row sm:items-end sm:justify-between sm:gap-6 sm:pb-0">
          <div
            role="tablist"
            aria-label={isZh ? "项目" : "Projects"}
            className="zen-no-scrollbar flex min-w-0 flex-1 items-center gap-4 overflow-x-auto pr-2 text-[13.5px] leading-5 sm:gap-5 sm:pr-0"
          >
            <button
              type="button"
              role="tab"
              aria-selected={projectFilter === null}
              onClick={() => setProjectFilter(null)}
              className={cn(
                "relative shrink-0 pb-1.5 transition-colors sm:pb-3",
                projectFilter === null
                  ? "font-medium text-foreground after:absolute after:inset-x-0 after:bottom-0 after:h-[1.5px] after:rounded-full after:bg-foreground"
                  : "text-muted-foreground/65 hover:text-foreground",
              )}
            >
              {isZh ? "全部" : "All"}
            </button>
            {projectTabs.map((group) => {
              const selected = projectFilter === group.project.id;
              const hasRecovery = tab !== "done" && group.recoveryCount > 0;
              const hasRunning = tab !== "done" && group.runningCount > 0;
              return (
                <button
                  key={group.project.id}
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  onClick={() => setProjectFilter(selected ? null : group.project.id)}
                  className={cn(
                    "relative inline-flex shrink-0 items-center gap-1.5 pb-1.5 transition-colors sm:pb-3",
                    selected
                      ? "font-medium text-foreground after:absolute after:inset-x-0 after:bottom-0 after:h-[1.5px] after:rounded-full after:bg-foreground"
                      : "text-muted-foreground/65 hover:text-foreground",
                  )}
                >
                  {hasRecovery ? (
                    <span className="h-1.5 w-1.5 rounded-full bg-amber-500" aria-hidden />
                  ) : hasRunning ? (
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden />
                  ) : null}
                  <span className="max-w-[9.5rem] truncate">{group.project.name}</span>
                </button>
              );
            })}
          </div>

          <div
            role="tablist"
            aria-label={isZh ? "视图" : "View"}
            className="flex shrink-0 items-center gap-4 text-[12.5px] leading-5 sm:pb-3"
          >
            <button
              type="button"
              role="tab"
              aria-selected={tab === "open"}
              onClick={() => setTab("open")}
              className={cn(
                "transition-colors",
                tab === "open" ? "font-medium text-foreground" : "text-muted-foreground/60 hover:text-foreground",
              )}
            >
              {isZh ? "当前" : "Active"}
            </button>

            {filteredCleanup.length > 0 ? (
              <button
                type="button"
                role="tab"
                aria-selected={tab === "clean"}
                onClick={() => setTab(tab === "clean" ? "open" : "clean")}
                className={cn(
                  "inline-flex items-center gap-1 transition-colors",
                  tab === "clean" ? "font-medium text-foreground" : "text-muted-foreground/60 hover:text-foreground",
                )}
              >
                <span>{isZh ? "整理" : "Tidy"}</span>
                <span className="tabular-nums opacity-65">{filteredCleanup.length}</span>
              </button>
            ) : null}

            <button
              type="button"
              role="tab"
              aria-selected={tab === "done"}
              onClick={() => setTab("done")}
              className={cn(
                "inline-flex items-center gap-1 transition-colors",
                tab === "done" ? "font-medium text-foreground" : "text-muted-foreground/60 hover:text-foreground",
              )}
            >
              <span>{isZh ? "已归档" : "Archived"}</span>
              {projectScopedArchived.length > 0 ? (
                <span className="tabular-nums opacity-55">{projectScopedArchived.length}</span>
              ) : null}
            </button>
          </div>
        </header>

        {tab === "open" ? (
          <div key="tab-open" className="zen-tab-enter flex flex-col gap-9 sm:gap-10">
            {/* Live Now — ultra-minimal 2-line tiles for actively running / waiting items ONLY */}
            {liveNowItems.length > 0 ? (
              <section aria-label={isZh ? "运行中" : "Running"} className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                {liveNowItems.map((item) => (
                  <LiveTile
                    key={item.session.key}
                    item={item}
                    isActive={item.session.key === activeKey}
                    isFocused={item.session.key === focusedKey}
                    isZh={isZh}
                    nowMs={nowMs}
                    locale={i18n.resolvedLanguage}
                    onOpen={() => onSelectSession(item.session.key)}
                  />
                ))}
              </section>
            ) : null}

            {/* Compact Split Workspace Chips (desktop only; mobile workbench disables split) */}
            {filteredWorkbenchGroups.length > 0 ? (
              <div className={cn("hidden flex-wrap items-center gap-2 md:flex", liveNowItems.length > 0 && "-mt-5")}>
                {filteredWorkbenchGroups.map((group) => (
                  <SplitChip
                    key={group.tabKey}
                    group={group}
                    onOpen={() => onSelectWorkbenchGroup(group.tabKey)}
                    onRename={onRequestRenameTab ? () => onRequestRenameTab(group.tabKey, group.title) : undefined}
                    onDissolve={onDissolveTab ? () => onDissolveTab(group.tabKey) : undefined}
                  />
                ))}
              </div>
            ) : null}

            {/* Borderless Single-Line Project Lists (Zero duplication with Live tiles above!) */}
            {visibleProjects.length === 0 && liveNowItems.length === 0 ? (
              <div className="flex flex-col items-center justify-center gap-3 py-24 text-center">
                <p className="text-[14px] text-muted-foreground/80">
                  {isZh ? "暂无会话" : "No active sessions"}
                </p>
                <button
                  type="button"
                  onClick={handleEmptyNewChat}
                  className="inline-flex h-8 items-center gap-1.5 rounded-full bg-foreground/[0.06] px-3.5 text-[12.5px] font-medium text-foreground transition-colors hover:bg-foreground/[0.1]"
                >
                  <Plus className="h-3.5 w-3.5" aria-hidden />
                  <span>
                    {selectedProject && !selectedProject.project.isGeneral
                      ? (isZh ? `在 ${selectedProject.project.name} 新建` : `New in ${selectedProject.project.name}`)
                      : t("sidebar.newChat")}
                  </span>
                </button>
              </div>
            ) : (
              <div className="space-y-8">
                {visibleProjects.map((group) => (
                  <ProjectSection
                    key={group.project.id}
                    group={group}
                    isFilteredProject={projectFilter !== null}
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
                    onOpenProjectTidy={(projectId) => {
                      setProjectFilter(projectId);
                      setTab("clean");
                    }}
                    onRequestDeleteMany={onRequestDeleteMany}
                    onRequestRenameProject={onRequestRenameProject}
                    onCreateTab={onCreateTab}
                  />
                ))}
              </div>
            )}
          </div>
        ) : tab === "clean" ? (
          /* Minimal Tidy View — zero lecture copy */
          <section key="tab-clean" aria-label={isZh ? "整理" : "Tidy"} className="zen-tab-enter space-y-5">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-3 text-[12.5px]">
                <span className="text-muted-foreground/75">
                  {isZh ? `${filteredCleanup.length} 项待整理` : `${filteredCleanup.length} to tidy`}
                </span>
                {filteredCleanup.length > 1 ? (
                  <button
                    type="button"
                    onClick={() => {
                      if (allCleanupSelected) {
                        setSelectedCleanupKeys(new Set());
                      } else {
                        setSelectedCleanupKeys(new Set(filteredCleanup.map((item) => item.session.key)));
                      }
                    }}
                    className="text-muted-foreground/55 transition-colors hover:text-foreground"
                  >
                    {allCleanupSelected
                      ? (isZh ? "取消全选" : "Clear")
                      : (isZh ? "全选" : "Select all")}
                  </button>
                ) : null}
              </div>
              <button
                type="button"
                disabled={selectedCleanupKeys.size === 0}
                onClick={() => {
                  const selectedCount = selectedCleanupKeys.size;
                  onArchiveMany(Array.from(selectedCleanupKeys), true);
                  if (selectedCount >= filteredCleanup.length) {
                    setTab("open");
                  }
                }}
                className="rounded-full bg-foreground/[0.07] px-3.5 py-1.5 text-[12.5px] font-medium text-foreground transition-colors hover:bg-foreground/[0.13] active:scale-[0.98] disabled:opacity-35"
              >
                {isZh
                  ? `归档所选 (${selectedCleanupKeys.size})`
                  : `Archive (${selectedCleanupKeys.size})`}
              </button>
            </div>

            <ul className="space-y-0.5">
              {filteredCleanup.map((item) => {
                const checked = selectedCleanupKeys.has(item.session.key);
                return (
                  <li
                    key={item.session.key}
                    className="-mx-3 flex items-center gap-3 rounded-xl px-3 py-2.5 text-[13.5px] transition-colors hover:bg-foreground/[0.032] dark:hover:bg-white/[0.035]"
                  >
                    <button
                      type="button"
                      onClick={() => toggleCleanupKey(item.session.key)}
                      aria-pressed={checked}
                      aria-label={item.title}
                      className="inline-flex h-5 w-5 shrink-0 items-center justify-center text-muted-foreground/65 transition-colors hover:text-foreground"
                    >
                      {checked ? (
                        <SquareCheckBig className="h-4 w-4 text-foreground/85" aria-hidden />
                      ) : (
                        <Square className="h-4 w-4" aria-hidden />
                      )}
                    </button>
                    <button
                      type="button"
                      onClick={() => onSelectSession(item.session.key)}
                      className="flex min-w-0 flex-1 items-center gap-2.5 text-left"
                    >
                      <span className="min-w-0 flex-1 truncate text-foreground/90">{item.title}</span>
                      {item.cleanupReason === "quick_chat" ? (
                        <span className="hidden shrink-0 text-[11.5px] text-muted-foreground/45 sm:inline">
                          {isZh ? "短对话" : "Quick"}
                        </span>
                      ) : null}
                      <span className="shrink-0 text-[12px] text-muted-foreground/55">{item.project.name}</span>
                    </button>
                    <span className="w-14 shrink-0 text-right text-[12px] tabular-nums text-muted-foreground/55">
                      {formatCompactRelativeTime(item.updatedMs, i18n.resolvedLanguage, nowMs)}
                    </span>
                  </li>
                );
              })}
            </ul>
          </section>
        ) : (
          /* Serene Done View */
          <section key="tab-done" className="zen-tab-enter space-y-5">
            <div className="flex items-center justify-between gap-3">
              <div className="relative max-w-xs flex-1">
                <Search className="pointer-events-none absolute left-0 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground/55" aria-hidden />
                <input
                  value={doneFilter}
                  onChange={(event) => setDoneFilter(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Escape" && doneFilter) {
                      event.preventDefault();
                      setDoneFilter("");
                    }
                  }}
                  placeholder={isZh ? "筛选已归档…" : "Filter archived…"}
                  className="h-8 w-full border-b border-border/45 bg-transparent pl-6 pr-6 text-[13px] text-foreground outline-none placeholder:text-muted-foreground/55 focus:border-foreground/40"
                />
                {doneFilter ? (
                  <button
                    type="button"
                    aria-label={isZh ? "清除筛选" : "Clear filter"}
                    onClick={() => setDoneFilter("")}
                    className="absolute right-0 top-1/2 inline-flex h-5 w-5 -translate-y-1/2 items-center justify-center rounded-full text-muted-foreground/55 hover:text-foreground"
                  >
                    <X className="h-3 w-3" aria-hidden />
                  </button>
                ) : null}
              </div>
              {filteredArchived.length > 0 ? (
                <button
                  type="button"
                  onClick={() => onArchiveMany(filteredArchived.map((item) => item.session.key), false)}
                  className="inline-flex shrink-0 items-center gap-1.5 text-[12px] text-muted-foreground/70 transition-colors hover:text-foreground"
                >
                  <ArchiveRestore className="h-3.5 w-3.5" aria-hidden />
                  <span>{isZh ? "全部恢复" : "Restore all"}</span>
                </button>
              ) : null}
            </div>

            {filteredArchived.length === 0 ? (
              <div className="py-16 text-center text-[13.5px] text-muted-foreground/70">
                {doneFilter.trim()
                  ? (isZh ? "没有匹配结果" : "No matches")
                  : (isZh ? "暂无已归档" : "No archived sessions")}
              </div>
            ) : (
              <ul className="space-y-0.5">
                {filteredArchived.map((item) => (
                  <li
                    key={item.session.key}
                    className="group -mx-3 flex items-center gap-3 rounded-xl px-3 py-2.5 transition-colors hover:bg-foreground/[0.032] dark:hover:bg-white/[0.035]"
                  >
                    <button
                      type="button"
                      onClick={() => onSelectSession(item.session.key)}
                      className="flex min-w-0 flex-1 items-center gap-2.5 text-left"
                    >
                      <span className="min-w-0 flex-1 truncate text-[13.5px] text-foreground/75 transition-colors group-hover:text-foreground">
                        {item.title}
                      </span>
                      <span className="shrink-0 text-[12px] text-muted-foreground/50">{item.project.name}</span>
                      <AutomationProtectedBadge count={item.automationCount} />
                    </button>

                    <div className="relative flex shrink-0 items-center gap-1">
                      <span className="text-[12px] tabular-nums text-muted-foreground/55 transition-opacity duration-150 media-hover:group-hover:opacity-0 media-hover:group-focus-within:opacity-0">
                        {formatCompactRelativeTime(item.updatedMs, i18n.resolvedLanguage, nowMs)}
                      </span>
                      <div className="flex items-center gap-0.5 transition-all duration-150 media-hover:pointer-events-none media-hover:absolute media-hover:right-0 media-hover:translate-x-1 media-hover:opacity-0 media-hover:group-hover:pointer-events-auto media-hover:group-hover:translate-x-0 media-hover:group-hover:opacity-100 media-hover:group-focus-within:pointer-events-auto media-hover:group-focus-within:translate-x-0 media-hover:group-focus-within:opacity-100">
                        <button
                          type="button"
                          aria-label={isZh ? `恢复：${item.title}` : `Restore: ${item.title}`}
                          onClick={() => onArchiveMany([item.session.key], false)}
                          className="inline-flex h-7 items-center gap-1 rounded-lg px-1.5 text-[12px] text-muted-foreground hover:bg-foreground/[0.05] hover:text-foreground media-hover:px-2"
                        >
                          <ArchiveRestore className="h-3.5 w-3.5" aria-hidden />
                          <span className="hidden media-hover:inline">{isZh ? "恢复" : "Restore"}</span>
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

/** Ultra-clean 2-line monochrome live tile: dot + project + elapsed on line 1, crisp title on line 2. */
function LiveTile({
  item,
  isActive,
  isFocused,
  isZh,
  nowMs,
  locale,
  onOpen,
}: {
  item: EnrichedSession;
  isActive: boolean;
  isFocused: boolean;
  isZh: boolean;
  nowMs: number;
  locale?: string;
  onOpen: () => void;
}) {
  const relativeTime = formatCompactRelativeTime(item.updatedMs, locale, nowMs);
  return (
    <button
      type="button"
      data-mission-session-row={item.session.key}
      onClick={onOpen}
      className={cn(
        "group flex w-full flex-col gap-2 rounded-2xl bg-foreground/[0.026] px-4 py-3.5 text-left transition-all duration-200 hover:bg-foreground/[0.048] active:scale-[0.995] dark:bg-white/[0.03] dark:hover:bg-white/[0.055]",
        isActive && "ring-1 ring-foreground/20 dark:ring-white/20",
        isFocused && "bg-foreground/[0.045] ring-1 ring-foreground/25 dark:bg-white/[0.06] dark:ring-white/25",
      )}
    >
      <div className="flex w-full items-center justify-between gap-2">
        <span className="inline-flex min-w-0 items-center gap-2 text-[12px] text-muted-foreground/75">
          <SessionStatusDot state={item.attention} />
          <span className="truncate">{item.project.name}</span>
        </span>
        {item.attention === "running" ? (
          <LiveElapsedBadge startedAtSec={item.session.runStartedAt} nowMs={nowMs} />
        ) : (
          <span className="inline-flex shrink-0 items-center gap-1.5 text-[11.5px] tabular-nums text-amber-600/90 dark:text-amber-400/90">
            <span className="font-medium">{isZh ? "待确认" : "Waiting"}</span>
            {relativeTime ? (
              <>
                <span aria-hidden className="opacity-45">·</span>
                <span className="opacity-80">{relativeTime}</span>
              </>
            ) : null}
          </span>
        )}
      </div>
      <p className="line-clamp-1 text-[14px] font-medium text-foreground">
        {item.title}
      </p>
    </button>
  );
}

function SplitChip({
  group,
  onOpen,
  onRename,
  onDissolve,
}: {
  group: DecoupledWorkbenchGroup;
  onOpen: () => void;
  onRename?: () => void;
  onDissolve?: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="group inline-flex items-center gap-1 rounded-full bg-foreground/[0.035] py-1 pl-3 pr-1.5 text-[12px] transition-colors hover:bg-foreground/[0.065]">
      <button
        type="button"
        onClick={onOpen}
        className="inline-flex items-center gap-1.5 text-foreground/85 hover:text-foreground"
      >
        <Columns2 className="h-3.5 w-3.5 text-muted-foreground/65" strokeWidth={1.75} aria-hidden />
        <span className="max-w-[12rem] truncate font-medium">{group.title}</span>
        <span className="text-[11px] tabular-nums text-muted-foreground/60">{group.panes.length}</span>
      </button>
      {onRename || onDissolve ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              aria-label={t("chat.actions", { title: group.title })}
              className="inline-flex h-5 w-5 items-center justify-center rounded-full text-muted-foreground/60 hover:bg-foreground/[0.06] hover:text-foreground"
            >
              <MoreHorizontal className="h-3 w-3" aria-hidden />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-40">
            {onRename ? (
              <DropdownMenuItem onSelect={onRename}>
                <Pencil className="h-3.5 w-3.5" aria-hidden />
                {t("chat.rename")}
              </DropdownMenuItem>
            ) : null}
            {onDissolve ? (
              <DropdownMenuItem onSelect={onDissolve}>
                <Ungroup className="h-3.5 w-3.5" aria-hidden />
                {t("workbench.dissolveTab")}
              </DropdownMenuItem>
            ) : null}
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}
    </div>
  );
}

function ProjectSection({
  group,
  isFilteredProject,
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
  onOpenProjectTidy,
  onRequestDeleteMany,
  onRequestRenameProject,
  onCreateTab,
}: {
  group: ProjectWorkspaceGroup;
  isFilteredProject: boolean;
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
  onOpenProjectTidy: (projectId: string) => void;
  onRequestDeleteMany: (items: SidebarDeleteItem[]) => void;
  onRequestRenameProject: (projectKey: string, label: string) => void;
  onCreateTab?: (paneKey: string) => void;
}) {
  const { t } = useTranslation();
  const { project } = group;

  return (
    <section aria-label={project.name} className="group/section space-y-1">
      {/* Whisper-quiet Project Header — path lives in tooltip, actions appear softly on hover (always reachable on touch) */}
      <div className="flex items-center justify-between gap-2 pb-1">
        <HoverHint enabled={Boolean(!project.isGeneral && project.path)} content={project.path ?? ""} side="top" align="start">
          <h2 className="truncate text-[12px] font-medium tracking-[0.02em] text-muted-foreground/80">
            {project.name}
          </h2>
        </HoverHint>

        <div
          className={cn(
            "flex shrink-0 items-center gap-1 transition-opacity duration-150",
            isFilteredProject
              ? "opacity-80 hover:opacity-100"
              : "media-hover:opacity-0 media-hover:group-hover/section:opacity-100 media-hover:focus-within:opacity-100 media-hover:has-[[data-state=open]]:opacity-100",
          )}
        >
          {group.cleanupCandidates.length > 0 ? (
            <button
              type="button"
              onClick={() => onOpenProjectTidy(project.id)}
              className="px-1.5 text-[11.5px] text-muted-foreground/75 transition-colors hover:text-foreground"
            >
              {isZh ? `整理 (${group.cleanupCandidates.length})` : `Tidy (${group.cleanupCandidates.length})`}
            </button>
          ) : null}
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
            className="inline-flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground/70 hover:bg-foreground/[0.05] hover:text-foreground"
          >
            <Plus className="h-3.5 w-3.5" aria-hidden />
          </button>
          {!project.isGeneral && project.key ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  aria-label={t("chat.actions", { title: project.name })}
                  className="inline-flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground/70 hover:bg-foreground/[0.05] hover:text-foreground"
                >
                  <MoreHorizontal className="h-3.5 w-3.5" aria-hidden />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-40">
                <DropdownMenuItem onSelect={() => onRequestRenameProject(project.key!, project.name)}>
                  <Pencil className="h-3.5 w-3.5" aria-hidden />
                  {t("chat.rename")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null}
        </div>
      </div>

      {/* Pure Single-Line Rows (Things 3 left-circle completion) */}
      <ul>
        {group.openSessions.map((item) => {
          const isCurrent = item.session.key === activeKey;
          const isFocused = item.session.key === focusedKey;
          const isRenaming = renamingKey === item.session.key;
          const completing = completingKeys.has(item.session.key);
          const canArchive = item.session.projectLocked !== false;
          const isLive = item.attention === "running" || item.attention === "recovery";

          return (
            <li key={item.session.key}>
              <div
                data-mission-session-row={item.session.key}
                className={cn(
                  "group relative -mx-3 flex h-11 items-center gap-3 rounded-xl px-3 transition-all duration-150 hover:bg-foreground/[0.032] dark:hover:bg-white/[0.035]",
                  isCurrent && "bg-foreground/[0.038]",
                  isFocused && "bg-foreground/[0.04] ring-1 ring-foreground/20 dark:bg-white/[0.05] dark:ring-white/20",
                  completing && "zen-completing",
                )}
              >
                {/* Left slot: Live dot for running/recovery; tactile Done circle for idle/updated */}
                <div className="flex w-4 shrink-0 items-center justify-center">
                  {isLive ? (
                    <SessionStatusDot state={item.attention} />
                  ) : item.attention === "updated" && canArchive ? (
                    <div className="relative flex items-center justify-center">
                      <span className="transition-opacity duration-150 group-hover:opacity-0 group-focus-within:opacity-0">
                        <SessionStatusDot state="updated" />
                      </span>
                      <div className="pointer-events-none absolute opacity-0 transition-opacity duration-150 group-hover:pointer-events-auto group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:opacity-100">
                        <ZenDoneCircle
                          completed={completing}
                          label={isZh ? `归档：${item.title}` : `Archive: ${item.title}`}
                          onClick={() => onCompleteSession(item.session.key)}
                        />
                      </div>
                    </div>
                  ) : canArchive ? (
                    <ZenDoneCircle
                      completed={completing}
                      label={isZh ? `归档：${item.title}` : `Archive: ${item.title}`}
                      onClick={() => onCompleteSession(item.session.key)}
                      className="border-foreground/25 group-hover:border-foreground/45 dark:border-white/25 dark:group-hover:border-white/45"
                    />
                  ) : (
                    <SessionStatusDot state="idle" />
                  )}
                </div>

                {/* Single Clean Title Line */}
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
                      className="h-7 w-full max-w-md border-b border-foreground/40 bg-transparent text-[14px] text-foreground outline-none"
                    />
                  ) : (
                    <button
                      type="button"
                      onClick={() => onSelectSession(item.session.key)}
                      className="flex w-full min-w-0 items-center gap-2 text-left focus-visible:outline-none"
                    >
                      <span className="min-w-0 truncate text-[14px] font-normal text-foreground/90 group-hover:text-foreground">
                        {item.title}
                      </span>
                      {item.pinned ? <SubtlePinMark /> : null}
                      <AutomationProtectedBadge count={item.automationCount} compact />
                      <SplitGroupBadge title={item.workbenchTabTitle} />
                    </button>
                  )}
                </div>

                {/* Right: Quiet time -> smooth hover overflow menu (inline menu trigger on touch) */}
                {!isRenaming ? (
                  <div className="relative flex h-7 shrink-0 items-center gap-1">
                    <span className="text-[12px] tabular-nums text-muted-foreground/50 transition-opacity duration-150 media-hover:group-hover:opacity-0 media-hover:group-focus-within:opacity-0 media-hover:group-has-[[data-state=open]]:opacity-0">
                      {item.attention === "running" ? (
                        <LiveElapsedBadge startedAtSec={item.session.runStartedAt} nowMs={nowMs} />
                      ) : (
                        formatCompactRelativeTime(item.updatedMs, locale, nowMs)
                      )}
                    </span>

                    <div className="flex items-center gap-0.5 transition-all duration-150 media-hover:pointer-events-none media-hover:absolute media-hover:right-0 media-hover:translate-x-1 media-hover:opacity-0 media-hover:group-hover:pointer-events-auto media-hover:group-hover:translate-x-0 media-hover:group-hover:opacity-100 media-hover:group-focus-within:pointer-events-auto media-hover:group-focus-within:translate-x-0 media-hover:group-focus-within:opacity-100 media-hover:group-has-[[data-state=open]]:pointer-events-auto media-hover:group-has-[[data-state=open]]:translate-x-0 media-hover:group-has-[[data-state=open]]:opacity-100">
                      <HoverHint content={item.pinned ? t("chat.unpin") : t("chat.pin")} side="top">
                        <button
                          type="button"
                          aria-label={item.pinned ? t("chat.unpin") : t("chat.pin")}
                          onClick={() => onTogglePin(item.session.key)}
                          className="hidden h-6 w-6 items-center justify-center rounded-md text-muted-foreground/65 hover:bg-foreground/[0.06] hover:text-foreground media-hover:inline-flex"
                        >
                          {item.pinned ? <PinOff className="h-3.5 w-3.5" aria-hidden /> : <Pin className="h-3.5 w-3.5" aria-hidden />}
                        </button>
                      </HoverHint>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <button
                            type="button"
                            aria-label={t("chat.actions", { title: item.title })}
                            className="inline-flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground/65 hover:bg-foreground/[0.06] hover:text-foreground"
                          >
                            <MoreHorizontal className="h-3.5 w-3.5" aria-hidden />
                          </button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-40">
                          {canArchive && !isLive ? (
                            <DropdownMenuItem onSelect={() => onCompleteSession(item.session.key)}>
                              <Archive className="h-3.5 w-3.5" aria-hidden />
                              {isZh ? "归档" : "Archive"}
                            </DropdownMenuItem>
                          ) : null}
                          <DropdownMenuItem onSelect={() => onTogglePin(item.session.key)}>
                            {item.pinned ? (
                              <PinOff className="h-3.5 w-3.5" aria-hidden />
                            ) : (
                              <Pin className="h-3.5 w-3.5" aria-hidden />
                            )}
                            {item.pinned ? t("chat.unpin") : t("chat.pin")}
                          </DropdownMenuItem>
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
