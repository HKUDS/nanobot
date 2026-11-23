import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArchiveRestore,
  ArrowRight,
  Check,
  ChevronDown,
  Columns2,
  MoreHorizontal,
  PanelsTopLeft,
  Pencil,
  Pin,
  PinOff,
  Plus,
  Search,
  Sparkles,
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
  ProjectDot,
  SessionStatusDot,
  SplitGroupBadge,
  SubtlePinMark,
  useLiveClock,
} from "@/components/session/SessionVisuals";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { HoverHint } from "@/components/ui/hover-hint";
import { SegmentedControl } from "@/components/ui/segmented-control";
import {
  formatCompactRelativeTime,
  type DecoupledWorkbenchGroup,
  type EnrichedSession,
  type ProjectWorkspaceGroup,
  type SessionIntelligenceSnapshot,
} from "@/lib/session-intelligence";
import { cn } from "@/lib/utils";

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

  const activeProjectCount = intelligence.projects.filter((p) => p.openSessions.length > 0).length;

  return (
    <div
      data-testid="mission-control-view"
      className="relative h-full min-h-0 w-full overflow-y-auto overscroll-contain bg-background [background-image:radial-gradient(ellipse_75%_38%_at_50%_-8%,hsl(var(--foreground)/0.032),transparent)]"
    >
      <div className="mx-auto flex w-full max-w-[1060px] flex-col gap-7 px-5 py-7 sm:px-8 sm:py-9">
        {/* Header */}
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-0 space-y-1">
            <h1 className="text-[22px] font-semibold tracking-tight text-foreground">
              {isZh ? "工作台" : "Mission Control"}
            </h1>
            <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-muted-foreground">
              {intelligence.running.length > 0 ? (
                <span className="inline-flex items-center gap-1.5 font-medium text-emerald-700 dark:text-emerald-300">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden />
                  {isZh ? `${intelligence.running.length} 个运行中` : `${intelligence.running.length} running`}
                </span>
              ) : null}
              {intelligence.recovery.length > 0 ? (
                <span className="inline-flex items-center gap-1 font-medium text-amber-600 dark:text-amber-400">
                  <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
                  {isZh ? `${intelligence.recovery.length} 个待确认` : `${intelligence.recovery.length} waiting`}
                </span>
              ) : null}
              <span>
                {isZh
                  ? `${intelligence.open.length} 个在办 · ${activeProjectCount} 个工作区`
                  : `${intelligence.open.length} open · ${activeProjectCount} workspaces`}
              </span>
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            <SegmentedControl<MissionControlTab>
              value={tab}
              onChange={setTab}
              mode="tabs"
              ariaLabel={isZh ? "会话状态切换" : "Session lifecycle view"}
              options={[
                {
                  value: "open",
                  label: (
                    <span className="inline-flex items-center gap-1.5">
                      <span>{isZh ? "在办" : "Open"}</span>
                      <span className="tabular-nums opacity-70">{intelligence.open.length}</span>
                    </span>
                  ),
                },
                {
                  value: "done",
                  label: (
                    <span className="inline-flex items-center gap-1.5">
                      <span>{isZh ? "已结单" : "Done"}</span>
                      <span className="tabular-nums opacity-70">{intelligence.archived.length}</span>
                    </span>
                  ),
                },
              ]}
            />
            <Button
              type="button"
              size="sm"
              onClick={onNewChat}
              className="h-9 gap-1.5 rounded-control px-3.5 text-[13px] font-medium"
            >
              <Plus className="h-4 w-4" aria-hidden />
              <span>{t("sidebar.newChat")}</span>
            </Button>
          </div>
        </header>

        {/* Project Filter Strip */}
        {projectPills.length > 1 ? (
          <div
            role="tablist"
            aria-label={isZh ? "按项目筛选" : "Filter by project"}
            className="-mt-2 flex flex-wrap items-center gap-1.5"
          >
            <button
              type="button"
              role="tab"
              aria-selected={projectFilter === null}
              onClick={() => setProjectFilter(null)}
              className={cn(
                "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[12.5px] font-medium transition-colors",
                projectFilter === null
                  ? "border-foreground/20 bg-foreground text-background"
                  : "border-border/70 bg-card/60 text-muted-foreground hover:bg-accent hover:text-foreground",
              )}
            >
              <span>{isZh ? "全部项目" : "All projects"}</span>
            </button>
            {projectPills.map((group) => {
              const selected = projectFilter === group.project.id;
              const count = tab === "open" ? group.openSessions.length : group.archivedSessions.length;
              return (
                <button
                  key={group.project.id}
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  onClick={() => setProjectFilter(selected ? null : group.project.id)}
                  className={cn(
                    "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[12.5px] font-medium transition-colors",
                    selected
                      ? "border-foreground/20 bg-foreground text-background"
                      : "border-border/70 bg-card/60 text-muted-foreground hover:bg-accent hover:text-foreground",
                  )}
                >
                  <ProjectDot color={group.project.dotColor} className={selected ? "ring-1 ring-background/40" : undefined} />
                  <span className="max-w-[11rem] truncate">{group.project.name}</span>
                  <span className="tabular-nums opacity-70">{count}</span>
                  {tab === "open" && group.recoveryCount > 0 ? (
                    <span className="h-1.5 w-1.5 rounded-full bg-amber-500" aria-hidden />
                  ) : tab === "open" && group.runningCount > 0 ? (
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden />
                  ) : null}
                </button>
              );
            })}
          </div>
        ) : null}

        {tab === "open" ? (
          <>
            {/* Section 1: Cross-Project Attention Deck */}
            {filteredAttention.length > 0 ? (
              <section aria-labelledby="mc-attention-heading" className="space-y-3">
                <div className="flex items-center justify-between">
                  <h2
                    id="mc-attention-heading"
                    className="text-[12px] font-semibold uppercase tracking-[0.04em] text-muted-foreground"
                  >
                    {isZh ? "需要关注 · 跨项目实时状态" : "Needs attention · Live across projects"}
                  </h2>
                  <span className="text-[12px] tabular-nums text-muted-foreground">
                    {filteredAttention.length}
                  </span>
                </div>

                <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
                  {filteredAttention.map((item) => (
                    <AttentionCard
                      key={item.session.key}
                      item={item}
                      isActive={item.session.key === activeKey}
                      nowMs={nowMs}
                      isZh={isZh}
                      locale={i18n.resolvedLanguage}
                      onOpen={() => onSelectSession(item.session.key)}
                      onDone={
                        item.attention === "updated" && item.session.projectLocked !== false
                          ? () => onArchiveMany([item.session.key], true)
                          : undefined
                      }
                    />
                  ))}
                </div>
              </section>
            ) : null}

            {/* Section 2: Decoupled Split Workspaces */}
            {filteredWorkbenchGroups.length > 0 ? (
              <section aria-labelledby="mc-splits-heading" className="space-y-3">
                <div className="flex items-center justify-between">
                  <h2
                    id="mc-splits-heading"
                    className="text-[12px] font-semibold uppercase tracking-[0.04em] text-muted-foreground"
                  >
                    {isZh ? "分屏工作区" : "Split workspaces"}
                  </h2>
                  <span className="text-[12px] text-muted-foreground">
                    {isZh ? "独立于项目树，保留各窗格原项目归属" : "Decoupled from project groups"}
                  </span>
                </div>
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

            {/* Section 3: Smart Hygiene / Cleanup Suggestion Strip */}
            {filteredCleanup.length > 0 ? (
              <section
                aria-label={isZh ? "智能清理建议" : "Smart cleanup suggestions"}
                className="overflow-hidden rounded-2xl border border-border/70 bg-muted/35"
              >
                <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                  <div className="flex min-w-0 items-center gap-2.5">
                    <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-background text-muted-foreground shadow-sm ring-1 ring-border/60">
                      <Sparkles className="h-3.5 w-3.5" aria-hidden />
                    </span>
                    <div className="min-w-0">
                      <p className="text-[13px] font-medium text-foreground">
                        {isZh
                          ? `发现 ${filteredCleanup.length} 条可能不再需要的会话`
                          : `${filteredCleanup.length} sessions look ready to wrap up`}
                      </p>
                      <p className="text-[12px] text-muted-foreground">
                        {isZh
                          ? [
                              staleCount > 0 ? `${staleCount} 条超 7 天未活跃` : null,
                              quickCount > 0 ? `${quickCount} 条一次性短对话` : null,
                              "已自动跳过运行中、钉住和含定时任务的会话",
                            ].filter(Boolean).join(" · ")
                          : [
                              staleCount > 0 ? `${staleCount} inactive 7d+` : null,
                              quickCount > 0 ? `${quickCount} quick one-offs` : null,
                              "Running, pinned & automated sessions are protected",
                            ].filter(Boolean).join(" · ")}
                      </p>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => setCleanupExpanded((open) => !open)}
                      className="h-8 gap-1 rounded-control px-2.5 text-[12.5px] text-muted-foreground hover:text-foreground"
                    >
                      <span>{cleanupExpanded ? (isZh ? "收起明细" : "Hide list") : (isZh ? "预览明细" : "Review")}</span>
                      <ChevronDown
                        className={cn("h-3.5 w-3.5 transition-transform", cleanupExpanded && "rotate-180")}
                        aria-hidden
                      />
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        onArchiveMany(filteredCleanup.map((item) => item.session.key), true);
                        setCleanupExpanded(false);
                      }}
                      className="h-8 gap-1.5 rounded-control px-3 text-[12.5px] font-medium"
                    >
                      <Check className="h-3.5 w-3.5" aria-hidden />
                      <span>{isZh ? "全部结单归档" : "Archive all"}</span>
                    </Button>
                  </div>
                </div>

                {cleanupExpanded ? (
                  <div className="border-t border-border/60 bg-background/60 px-4 py-3">
                    <ul className="max-h-64 divide-y divide-border/40 overflow-y-auto">
                      {filteredCleanup.map((item) => {
                        const checked = selectedCleanupKeys.has(item.session.key);
                        return (
                          <li key={item.session.key} className="flex items-center gap-3 py-2">
                            <button
                              type="button"
                              onClick={() => toggleCleanupKey(item.session.key)}
                              aria-pressed={checked}
                              className="inline-flex h-5 w-5 shrink-0 items-center justify-center text-muted-foreground hover:text-foreground"
                            >
                              {checked ? (
                                <SquareCheckBig className="h-4 w-4 text-primary" aria-hidden />
                              ) : (
                                <Square className="h-4 w-4" aria-hidden />
                              )}
                            </button>
                            <button
                              type="button"
                              onClick={() => onSelectSession(item.session.key)}
                              className="flex min-w-0 flex-1 items-center gap-2 text-left"
                            >
                              <ProjectDot color={item.project.dotColor} />
                              <span className="shrink-0 text-[12px] text-muted-foreground">
                                {item.project.name}
                              </span>
                              <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-foreground">
                                {item.title}
                              </span>
                            </button>
                            <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                              {item.cleanupReason === "stale"
                                ? (isZh ? "7天+未活跃" : "7d+ idle")
                                : (isZh ? "一次性短对话" : "Quick chat")}
                            </span>
                            <span className="w-16 shrink-0 text-right text-[11.5px] tabular-nums text-muted-foreground">
                              {formatCompactRelativeTime(item.updatedMs, i18n.resolvedLanguage, nowMs)}
                            </span>
                          </li>
                        );
                      })}
                    </ul>
                    <div className="mt-3 flex items-center justify-end gap-2 border-t border-border/50 pt-3">
                      <Button
                        type="button"
                        size="sm"
                        disabled={selectedCleanupKeys.size === 0}
                        onClick={() => {
                          onArchiveMany(Array.from(selectedCleanupKeys), true);
                          setCleanupExpanded(false);
                        }}
                        className="h-8 gap-1.5 rounded-control px-3 text-[12.5px]"
                      >
                        <Check className="h-3.5 w-3.5" aria-hidden />
                        <span>
                          {isZh
                            ? `归档所选 (${selectedCleanupKeys.size})`
                            : `Archive selected (${selectedCleanupKeys.size})`}
                        </span>
                      </Button>
                    </div>
                  </div>
                ) : null}
              </section>
            ) : null}

            {/* Section 4: Projects & Open Sessions */}
            {visibleProjects.length === 0 ? (
              <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-border/80 bg-card/30 px-6 py-16 text-center">
                <p className="text-[15px] font-medium text-foreground">
                  {isZh ? "所有在办会话都已清空" : "Inbox zero — all sessions wrapped up"}
                </p>
                <p className="max-w-sm text-[13px] text-muted-foreground">
                  {isZh
                    ? "开启一个新话题，或切换到「已结单」随时回看历史记录。"
                    : "Start a fresh conversation or switch to Done to browse archived history."}
                </p>
                <Button type="button" size="sm" onClick={onNewChat} className="mt-1 gap-1.5 rounded-control">
                  <Plus className="h-4 w-4" aria-hidden />
                  <span>{t("sidebar.newChat")}</span>
                </Button>
              </div>
            ) : (
              <div className="space-y-6 pb-8">
                {visibleProjects.map((group) => (
                  <ProjectSection
                    key={group.project.id}
                    group={group}
                    activeKey={activeKey}
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
          /* Done / Archived Tab */
          <section className="space-y-4 pb-8">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="relative min-w-[14rem] flex-1 max-w-sm">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden />
                <input
                  value={doneFilter}
                  onChange={(event) => setDoneFilter(event.target.value)}
                  placeholder={isZh ? "筛选已结单会话..." : "Filter archived sessions..."}
                  className="h-9 w-full rounded-control border border-border/75 bg-card/70 pl-9 pr-3 text-[13px] text-foreground outline-none placeholder:text-muted-foreground focus:border-foreground/30"
                />
              </div>
              {filteredArchived.length > 0 ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => onArchiveMany(filteredArchived.map((item) => item.session.key), false)}
                  className="h-8 gap-1.5 rounded-control text-[12.5px] text-muted-foreground hover:text-foreground"
                >
                  <ArchiveRestore className="h-3.5 w-3.5" aria-hidden />
                  <span>{isZh ? `全部恢复 (${filteredArchived.length})` : `Restore all (${filteredArchived.length})`}</span>
                </Button>
              ) : null}
            </div>

            {filteredArchived.length === 0 ? (
              <div className="flex flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-border/75 py-14 text-center">
                <p className="text-[14px] font-medium text-foreground/85">
                  {isZh ? "没有已结单的会话" : "No archived sessions"}
                </p>
                <p className="text-[12.5px] text-muted-foreground">
                  {isZh ? "完成任务后点击「结单」，它会安静地收在这里。" : "Mark finished conversations Done to keep your workspace calm."}
                </p>
              </div>
            ) : (
              <div className="overflow-hidden rounded-2xl border border-border/60 bg-card/45 divide-y divide-border/45">
                {filteredArchived.map((item) => (
                  <div
                    key={item.session.key}
                    className="group flex items-center gap-3.5 px-4 py-3 transition-colors hover:bg-accent/45"
                  >
                    <button
                      type="button"
                      onClick={() => onSelectSession(item.session.key)}
                      className="flex min-w-0 flex-1 flex-col gap-0.5 text-left"
                    >
                      <div className="flex min-w-0 items-center gap-2">
                        <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-muted/70 px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground">
                          <ProjectDot color={item.project.dotColor} className="h-1.5 w-1.5" />
                          <span className="max-w-[8rem] truncate">{item.project.name}</span>
                        </span>
                        <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium text-foreground/80">
                          {item.title}
                        </span>
                        <MutedHandleBadge handle={item.session.handle} />
                        <AutomationProtectedBadge count={item.automationCount} />
                      </div>
                      {item.preview ? (
                        <p className="truncate text-[12px] text-muted-foreground/80">{item.preview}</p>
                      ) : null}
                    </button>
                    <span className="shrink-0 text-[12px] tabular-nums text-muted-foreground group-hover:hidden">
                      {formatCompactRelativeTime(item.updatedMs, i18n.resolvedLanguage, nowMs)}
                    </span>
                    <div className="hidden shrink-0 items-center gap-1 group-hover:flex group-focus-within:flex">
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => onArchiveMany([item.session.key], false)}
                        className="h-7 gap-1 rounded-control px-2 text-[12px] text-muted-foreground hover:text-foreground"
                      >
                        <ArchiveRestore className="h-3.5 w-3.5" aria-hidden />
                        <span>{isZh ? "恢复" : "Restore"}</span>
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        aria-label={t("chat.delete")}
                        onClick={() => onRequestDeleteMany([{ key: item.session.key, label: item.title }])}
                        className="h-7 w-7 rounded-control text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                      >
                        <Trash2 className="h-3.5 w-3.5" aria-hidden />
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        )}
      </div>
    </div>
  );
}

function AttentionCard({
  item,
  isActive,
  nowMs,
  isZh,
  locale,
  onOpen,
  onDone,
}: {
  item: EnrichedSession;
  isActive: boolean;
  nowMs: number;
  isZh: boolean;
  locale?: string;
  onOpen: () => void;
  onDone?: () => void;
}) {
  const toneClass = item.attention === "recovery"
    ? "border-amber-500/30 bg-amber-500/[0.045] hover:border-amber-500/50 dark:bg-amber-400/[0.07]"
    : item.attention === "running"
      ? "border-emerald-500/25 bg-emerald-500/[0.035] hover:border-emerald-500/45 dark:bg-emerald-400/[0.06]"
      : "border-orange-400/25 bg-orange-500/[0.03] hover:border-orange-400/45 dark:bg-orange-400/[0.05]";

  const statusText = item.attention === "recovery"
    ? (isZh ? "需要确认" : "Needs attention")
    : item.attention === "running"
      ? (isZh ? "运行中" : "Running")
      : (isZh ? "新结果待验收" : "Ready to review");

  const statusTextClass = item.attention === "recovery"
    ? "text-amber-700 dark:text-amber-300"
    : item.attention === "running"
      ? "text-emerald-700 dark:text-emerald-300"
      : "text-orange-700 dark:text-orange-300";

  return (
    <article
      className={cn(
        "group relative flex flex-col justify-between gap-3 rounded-2xl border p-4 transition-all duration-150 hover:-translate-y-px hover:shadow-[0_6px_20px_rgba(15,23,42,0.06)] dark:hover:shadow-[0_6px_24px_rgba(0,0,0,0.28)]",
        toneClass,
        isActive && "ring-1 ring-foreground/20",
      )}
    >
      <div className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <SessionStatusDot state={item.attention} />
            <span className={cn("text-[11.5px] font-semibold", statusTextClass)}>
              {statusText}
            </span>
          </div>
          <span className="inline-flex max-w-[9.5rem] items-center gap-1.5 rounded-full bg-background/80 px-2 py-0.5 text-[11px] font-medium text-muted-foreground ring-1 ring-border/50">
            <ProjectDot color={item.project.dotColor} className="h-1.5 w-1.5" />
            <span className="truncate">{item.project.name}</span>
          </span>
        </div>

        <button
          type="button"
          onClick={onOpen}
          className="block w-full text-left focus-visible:outline-none"
        >
          <h3 className="line-clamp-2 text-[14px] font-semibold leading-snug text-foreground group-hover:text-foreground">
            {item.title}
          </h3>
          {item.preview ? (
            <p className="mt-1 line-clamp-1 text-[12px] text-muted-foreground">
              {item.preview}
            </p>
          ) : null}
        </button>
      </div>

      <div className="flex items-center justify-between gap-2 pt-1">
        <div className="flex min-w-0 items-center gap-1.5">
          {item.attention === "running" ? (
            <LiveElapsedBadge startedAtSec={item.session.runStartedAt} nowMs={nowMs} />
          ) : (
            <span className="text-[11.5px] tabular-nums text-muted-foreground">
              {formatCompactRelativeTime(item.updatedMs, locale, nowMs)}
            </span>
          )}
          <MutedHandleBadge handle={item.session.handle} />
          <AutomationProtectedBadge count={item.automationCount} compact />
        </div>

        <div className="flex shrink-0 items-center gap-1.5">
          {onDone ? (
            <button
              type="button"
              onClick={onDone}
              className="inline-flex h-7 items-center gap-1 rounded-control border border-border/75 bg-background/90 px-2 text-[11.5px] font-medium text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground"
            >
              <Check className="h-3 w-3" aria-hidden />
              <span>{isZh ? "结单" : "Done"}</span>
            </button>
          ) : null}
          <button
            type="button"
            onClick={onOpen}
            className="inline-flex h-7 items-center gap-1 rounded-control bg-background/85 px-2.5 text-[11.5px] font-medium text-foreground ring-1 ring-border/70 transition-colors hover:bg-background"
          >
            <span>{isZh ? "进入" : "Open"}</span>
            <ArrowRight className="h-3 w-3" aria-hidden />
          </button>
        </div>
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
    <div className="flex flex-col gap-3 rounded-2xl border border-border/65 bg-card/65 p-4 transition-colors hover:border-border">
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={onOpen}
          className="flex min-w-0 items-center gap-2 text-left"
        >
          <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
            <Columns2 className="h-3.5 w-3.5" aria-hidden />
          </span>
          <div className="min-w-0">
            <p className="truncate text-[13.5px] font-semibold text-foreground">{group.title}</p>
            <p className="text-[11.5px] text-muted-foreground">
              {isZh ? `${group.panes.length} 个并排会话` : `${group.panes.length} side-by-side panes`}
            </p>
          </div>
        </button>

        <div className="flex shrink-0 items-center gap-1">
          <Button type="button" variant="ghost" size="sm" onClick={onOpen} className="h-7 rounded-control px-2.5 text-[12px]">
            {isZh ? "打开分屏" : "Open split"}
          </Button>
          {onRename || onDissolve ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button type="button" variant="ghost" size="icon" className="h-7 w-7 rounded-control text-muted-foreground">
                  <MoreHorizontal className="h-3.5 w-3.5" aria-hidden />
                </Button>
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
      </div>

      <div className="flex flex-wrap gap-1.5">
        {group.panes.map((pane) => (
          <button
            key={pane.session.key}
            type="button"
            onClick={() => onSelectPane(pane.session.key)}
            className="inline-flex max-w-full items-center gap-1.5 rounded-lg border border-border/60 bg-background/75 px-2.5 py-1 text-[12px] transition-colors hover:bg-accent"
          >
            {pane.attention !== "idle" ? (
              <SessionStatusDot state={pane.attention} size="sm" />
            ) : (
              <ProjectDot color={pane.project.dotColor} className="h-1.5 w-1.5" />
            )}
            <span className="shrink-0 text-[11px] text-muted-foreground">{pane.project.name}</span>
            <span className="text-muted-foreground/50">/</span>
            <span className="max-w-[12rem] truncate font-medium text-foreground">{pane.title}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function ProjectSection({
  group,
  activeKey,
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
  onArchiveMany,
  onRequestDeleteMany,
  onRequestRenameProject,
  onCreateTab,
}: {
  group: ProjectWorkspaceGroup;
  activeKey: string | null;
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
  onArchiveMany: (keys: string[], archive: boolean) => void;
  onRequestDeleteMany: (items: SidebarDeleteItem[]) => void;
  onRequestRenameProject: (projectKey: string, label: string) => void;
  onCreateTab?: (paneKey: string) => void;
}) {
  const { t } = useTranslation();
  const { project } = group;

  return (
    <section aria-label={project.name} className="space-y-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2 px-1">
        <div className="flex min-w-0 items-center gap-2.5">
          <ProjectDot color={project.dotColor} className="h-2.5 w-2.5" />
          <h2 className="truncate text-[14.5px] font-semibold tracking-tight text-foreground">
            {project.name}
          </h2>
          <span className="text-[12px] tabular-nums text-muted-foreground">
            {group.openSessions.length}
          </span>
          {!project.isGeneral && project.path ? (
            <span className="hidden max-w-[20rem] truncate font-mono text-[11px] text-muted-foreground/65 md:inline">
              {project.path}
            </span>
          ) : null}
          {/* Rollup live status pills on the project header */}
          <div className="flex items-center gap-1.5">
            {group.recoveryCount > 0 ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/12 px-2 py-0.5 text-[11px] font-medium text-amber-700 dark:text-amber-300">
                <AlertTriangle className="h-3 w-3" aria-hidden />
                {group.recoveryCount}
              </span>
            ) : null}
            {group.runningCount > 0 ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/12 px-2 py-0.5 text-[11px] font-medium text-emerald-700 dark:text-emerald-300">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden />
                {group.runningCount}
              </span>
            ) : null}
            {group.updatedCount > 0 ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-orange-500/12 px-2 py-0.5 text-[11px] font-medium text-orange-700 dark:text-orange-300">
                <span className="h-1.5 w-1.5 rounded-full bg-[#ff8a3d]" aria-hidden />
                {group.updatedCount}
              </span>
            ) : null}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-1">
          {group.cleanupCandidates.length > 0 ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => onArchiveMany(group.cleanupCandidates.map((item) => item.session.key), true)}
              className="h-7 gap-1 rounded-control px-2 text-[11.5px] font-medium text-muted-foreground hover:text-foreground"
            >
              <Sparkles className="h-3 w-3" aria-hidden />
              <span>
                {isZh
                  ? `清理空闲 (${group.cleanupCandidates.length})`
                  : `Clean idle (${group.cleanupCandidates.length})`}
              </span>
            </Button>
          ) : null}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => {
              if (!project.isGeneral && project.path) {
                onNewChatInProject(project.path, project.name);
              } else {
                onNewChat();
              }
            }}
            className="h-7 gap-1 rounded-control px-2 text-[12px] text-muted-foreground hover:text-foreground"
          >
            <Plus className="h-3.5 w-3.5" aria-hidden />
            <span>{isZh ? "新建" : "New"}</span>
          </Button>
          {!project.isGeneral && project.key ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={t("chat.actions", { title: project.name })}
                  className="h-7 w-7 rounded-control text-muted-foreground hover:text-foreground"
                >
                  <MoreHorizontal className="h-3.5 w-3.5" aria-hidden />
                </Button>
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
                    <Check className="h-3.5 w-3.5" aria-hidden />
                    {isZh ? "归档本项目全部会话" : "Archive all in project"}
                  </DropdownMenuItem>
                ) : null}
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null}
        </div>
      </div>

      <div className="overflow-hidden rounded-2xl border border-border/60 bg-card/65 divide-y divide-border/45">
        {group.openSessions.map((item) => {
          const isCurrent = item.session.key === activeKey;
          const isRenaming = renamingKey === item.session.key;
          const canArchive = item.session.projectLocked !== false;

          return (
            <div
              key={item.session.key}
              data-mission-session-row={item.session.key}
              className={cn(
                "group relative flex items-center gap-3.5 px-4 py-3 transition-colors hover:bg-accent/50",
                isCurrent && "bg-accent/45",
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
                    className="h-7 w-full max-w-md rounded-md border border-border bg-background px-2 text-[13.5px] font-medium text-foreground outline-none focus:ring-2 focus:ring-ring/40"
                  />
                ) : (
                  <button
                    type="button"
                    onClick={() => onSelectSession(item.session.key)}
                    className="block w-full min-w-0 text-left focus-visible:outline-none"
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="min-w-0 truncate text-[13.5px] font-medium leading-5 text-foreground">
                        {item.title}
                      </span>
                      {item.pinned ? <SubtlePinMark /> : null}
                      <MutedHandleBadge handle={item.session.handle} />
                      <AutomationProtectedBadge count={item.automationCount} />
                      <SplitGroupBadge title={item.workbenchTabTitle} compact />
                      {item.cleanupReason ? (
                        <span className="hidden shrink-0 rounded-full bg-muted/75 px-1.5 py-0.5 text-[10.5px] text-muted-foreground sm:inline">
                          {item.cleanupReason === "stale"
                            ? (isZh ? "久未活跃" : "Idle")
                            : (isZh ? "短对话" : "Quick")}
                        </span>
                      ) : null}
                    </div>
                    {item.preview && item.preview !== item.title ? (
                      <p className="mt-0.5 truncate text-[12px] leading-4 text-muted-foreground">
                        {item.preview}
                      </p>
                    ) : null}
                  </button>
                )}
              </div>

              {/* Right: Time/Elapsed at rest, crisp quick actions on hover */}
              {!isRenaming ? (
                <div className="relative flex shrink-0 items-center gap-1.5">
                  <div className="flex items-center gap-2 group-hover:hidden group-focus-within:hidden">
                    {item.attention === "running" ? (
                      <LiveElapsedBadge startedAtSec={item.session.runStartedAt} nowMs={nowMs} />
                    ) : (
                      <span className="text-[12px] tabular-nums text-muted-foreground">
                        {formatCompactRelativeTime(item.updatedMs, locale, nowMs)}
                      </span>
                    )}
                  </div>

                  <div className="hidden items-center gap-1 group-hover:flex group-focus-within:flex">
                    {canArchive ? (
                      <HoverHint content={isZh ? "结单归档" : "Mark done"} side="top">
                        <button
                          type="button"
                          aria-label={isZh ? `结单：${item.title}` : `Done: ${item.title}`}
                          onClick={() => onArchiveMany([item.session.key], true)}
                          className="inline-flex h-7 items-center gap-1 rounded-control border border-border/75 bg-background px-2 text-[11.5px] font-medium text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground"
                        >
                          <Check className="h-3 w-3" aria-hidden />
                          <span>{isZh ? "结单" : "Done"}</span>
                        </button>
                      </HoverHint>
                    ) : null}

                    <HoverHint content={item.pinned ? t("chat.unpin") : t("chat.pin")} side="top">
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        aria-label={item.pinned ? t("chat.unpin") : t("chat.pin")}
                        onClick={() => onTogglePin(item.session.key)}
                        className="h-7 w-7 rounded-control text-muted-foreground hover:text-foreground"
                      >
                        {item.pinned ? <PinOff className="h-3.5 w-3.5" aria-hidden /> : <Pin className="h-3.5 w-3.5" aria-hidden />}
                      </Button>
                    </HoverHint>

                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          aria-label={t("chat.actions", { title: item.title })}
                          className="h-7 w-7 rounded-control text-muted-foreground hover:text-foreground"
                        >
                          <MoreHorizontal className="h-3.5 w-3.5" aria-hidden />
                        </Button>
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
          );
        })}
      </div>
    </section>
  );
}
