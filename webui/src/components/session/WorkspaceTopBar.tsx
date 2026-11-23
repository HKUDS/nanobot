import { useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  ArrowUpCircle,
  Check,
  ChevronRight,
  Columns2,
  LayoutGrid,
  PanelLeft,
  Plus,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  AppsIcon,
  AutomationsIcon,
  SearchIcon,
  SettingsIcon,
} from "@/components/icons/product-icons";
import { ThemeToggleIcon } from "@/components/icons/ThemeToggleIcon";
import { HostSwitcher } from "@/components/remote/HostSwitcher";
import {
  LiveElapsedBadge,
  MutedHandleBadge,
  ProjectDot,
  SessionStatusDot,
  useLiveClock,
} from "@/components/session/SessionVisuals";
import { Button } from "@/components/ui/button";
import { HoverHint } from "@/components/ui/hover-hint";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  formatCompactRelativeTime,
  type DecoupledWorkbenchGroup,
  type EnrichedSession,
  type SessionIntelligenceSnapshot,
} from "@/lib/session-intelligence";
import { sidebarShortcutLabel } from "@/lib/sidebar-shortcuts";
import type { UpdateMethod } from "@/lib/api";
import type { ShellView } from "@/shell-route";
import { cn } from "@/lib/utils";

function isApplePlatform(): boolean {
  if (typeof navigator === "undefined") return false;
  const platform = navigator.platform || "";
  return /mac|iphone|ipad|ipod/i.test(platform);
}

export interface WorkspaceTopBarProps {
  view: ShellView;
  intelligence: SessionIntelligenceSnapshot;
  activeSession: EnrichedSession | null;
  activeTemporaryTitle: string | null;
  activeWorkbenchGroup: DecoupledWorkbenchGroup | null;
  drawerOpen: boolean;
  drawerPinned: boolean;
  theme: "light" | "dark";
  hostChromeInset?: boolean;
  availableUpdate?: {
    version: string;
    onDismiss: () => void;
    onRequestUpdate?: () => void;
    installationMethod?: UpdateMethod | null;
  };
  onOpenOverview: (projectId?: string | null) => void;
  onToggleDrawer: () => void;
  onSelectSession: (key: string) => void;
  onNewChat: () => void;
  onDoneSession: (key: string) => void;
  onOpenSearch: () => void;
  onOpenApps: () => void;
  onOpenAutomations: () => void;
  onOpenSettings: () => void;
  onOpenUpdates?: () => void;
  onSettingsIntent?: () => void;
  onToggleTheme: () => void;
}

export function WorkspaceTopBar({
  view,
  intelligence,
  activeSession,
  activeTemporaryTitle,
  activeWorkbenchGroup,
  drawerOpen,
  drawerPinned,
  theme,
  hostChromeInset = false,
  availableUpdate,
  onOpenOverview,
  onToggleDrawer,
  onSelectSession,
  onNewChat,
  onDoneSession,
  onOpenSearch,
  onOpenApps,
  onOpenAutomations,
  onOpenSettings,
  onOpenUpdates,
  onSettingsIntent,
  onToggleTheme,
}: WorkspaceTopBarProps) {
  const { t, i18n } = useTranslation();
  const isZh = Boolean(i18n.resolvedLanguage?.startsWith("zh"));
  const apple = isApplePlatform();
  const [pulseOpen, setPulseOpen] = useState(false);

  const runningCount = intelligence.running.length;
  const recoveryCount = intelligence.recovery.length;
  const updatedCount = intelligence.updated.length;
  const attentionCount = intelligence.attention.length;
  const nowMs = useLiveClock(runningCount > 0 && pulseOpen, 1000);

  const canMarkActiveDone = Boolean(
    view === "chat"
    && activeSession
    && !activeSession.archived
    && activeSession.session.projectLocked !== false,
  );

  const overviewLabel = isZh ? "工作台" : "Overview";
  const drawerLabel = isZh ? "在办抽屉" : "Active drawer";
  const doneLabel = isZh ? "结单" : "Done";

  return (
    <header
      data-testid="workspace-top-bar"
      data-theme-surface
      className={cn(
        "relative z-30 flex h-12 shrink-0 items-center justify-between gap-2 border-b border-border/60 bg-background/92 px-3 backdrop-blur-md",
        hostChromeInset && "pl-[4.75rem]",
      )}
    >
      {/* Left: Brand/Overview + Drawer toggle + Host + Contextual Breadcrumb */}
      <div className="flex min-w-0 flex-1 items-center gap-1">
        <HoverHint
          side="bottom"
          content={
            <span className="flex items-center gap-3">
              <span>{overviewLabel}</span>
              <kbd className="font-sans text-muted-foreground">
                {sidebarShortcutLabel("overview", apple)}
              </kbd>
            </span>
          }
        >
          <button
            type="button"
            data-testid="topbar-overview-button"
            aria-current={view === "overview" ? "page" : undefined}
            onClick={() => onOpenOverview(null)}
            className={cn(
              "host-no-drag inline-flex h-8 shrink-0 items-center gap-2 rounded-control px-2 text-[13px] font-medium transition-colors",
              view === "overview"
                ? "bg-accent text-foreground shadow-[inset_0_0_0_1px_hsl(var(--border)/0.7)]"
                : "text-muted-foreground hover:bg-accent/65 hover:text-foreground",
            )}
          >
            <span className="relative h-5 w-5 shrink-0">
              <img
                src="/brand/nanobot_mark.svg"
                alt=""
                className="h-5 w-5 select-none object-contain dark:opacity-0"
                draggable={false}
              />
              <img
                src="/brand/nanobot_mark_night.svg"
                alt=""
                className="absolute inset-0 h-5 w-5 select-none object-contain opacity-0 dark:opacity-100"
                draggable={false}
              />
            </span>
            <span className="hidden sm:inline">{overviewLabel}</span>
          </button>
        </HoverHint>

        <HoverHint
          side="bottom"
          content={
            <span className="flex items-center gap-3">
              <span>{drawerLabel}</span>
              <kbd className="font-sans text-muted-foreground">
                {sidebarShortcutLabel("drawer", apple)}
              </kbd>
            </span>
          }
        >
          <Button
            type="button"
            variant="ghost"
            size="icon"
            data-testid="topbar-drawer-toggle"
            aria-label={drawerLabel}
            aria-pressed={drawerOpen || drawerPinned}
            onClick={onToggleDrawer}
            className={cn(
              "host-no-drag h-8 w-8 shrink-0 rounded-control",
              drawerOpen || drawerPinned
                ? "bg-accent text-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <PanelLeft className="h-4 w-4" aria-hidden />
          </Button>
        </HoverHint>

        <span aria-hidden className="mx-0.5 hidden h-4 w-px shrink-0 bg-border/75 sm:block" />

        <div className="hidden shrink-0 sm:flex sm:items-center">
          <HostSwitcher menuSide="bottom" className="h-7 rounded-control px-2 text-[12px] text-muted-foreground hover:bg-accent/65 hover:text-foreground" />
        </div>

        {/* Contextual Breadcrumb when viewing a chat or split workbench */}
        {view === "chat" && (activeSession || activeTemporaryTitle) ? (
          <nav
            aria-label={isZh ? "当前上下文" : "Current context"}
            className="hidden min-w-0 items-center gap-1 md:flex"
          >
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/50" aria-hidden />
            {activeSession ? (
              <>
                <button
                  type="button"
                  onClick={() => onOpenOverview(activeSession.project.id)}
                  className="host-no-drag inline-flex max-w-[10rem] shrink-0 items-center gap-1.5 rounded-control px-2 py-1 text-[12.5px] font-medium text-muted-foreground transition-colors hover:bg-accent/65 hover:text-foreground"
                >
                  <ProjectDot color={activeSession.project.dotColor} />
                  <span className="truncate">{activeSession.project.name}</span>
                </button>
                <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/50" aria-hidden />
                {activeWorkbenchGroup && activeWorkbenchGroup.panes.length > 1 ? (
                  <div className="flex min-w-0 items-center gap-1">
                    <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-muted/75 px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground">
                      <Columns2 className="h-3 w-3" aria-hidden />
                      <span className="max-w-[7rem] truncate">{activeWorkbenchGroup.title}</span>
                    </span>
                    <div className="hidden items-center gap-1 xl:flex">
                      {activeWorkbenchGroup.panes.map((pane) => {
                        const paneActive = pane.session.key === activeSession.session.key;
                        return (
                          <button
                            key={pane.session.key}
                            type="button"
                            onClick={() => onSelectSession(pane.session.key)}
                            className={cn(
                              "host-no-drag inline-flex max-w-[10rem] items-center gap-1.5 rounded-control px-2 py-0.5 text-[12px] transition-colors",
                              paneActive
                                ? "bg-accent font-medium text-foreground"
                                : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
                            )}
                          >
                            {pane.attention !== "idle" ? (
                              <SessionStatusDot state={pane.attention} size="sm" />
                            ) : (
                              <ProjectDot color={pane.project.dotColor} className="h-1.5 w-1.5" />
                            )}
                            <span className="truncate">{pane.title}</span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                ) : (
                  <div className="flex min-w-0 items-center gap-2 px-1">
                    <span className="max-w-[15rem] truncate text-[13px] font-medium text-foreground">
                      {activeSession.title}
                    </span>
                    <MutedHandleBadge handle={activeSession.session.handle} />
                  </div>
                )}
              </>
            ) : (
              <span className="max-w-[14rem] truncate px-1.5 text-[13px] font-medium text-foreground">
                {activeTemporaryTitle}
              </span>
            )}
          </nav>
        ) : null}
      </div>

      {/* Right: Cross-Project Live Pulse + Quick Done + New + Search + System Controls */}
      <div className="flex shrink-0 items-center gap-1.5">
        <Popover open={pulseOpen} onOpenChange={setPulseOpen}>
          <PopoverTrigger asChild>
            <button
              type="button"
              data-testid="live-pulse-trigger"
              className={cn(
                "host-no-drag inline-flex h-8 items-center gap-2 rounded-full border px-2.5 text-[12px] font-medium transition-all",
                attentionCount > 0
                  ? "border-border/80 bg-card text-foreground shadow-[0_1px_2px_rgba(15,23,42,0.05)] hover:bg-accent/70"
                  : "border-transparent bg-muted/55 text-muted-foreground hover:bg-accent/70 hover:text-foreground",
              )}
            >
              {recoveryCount > 0 ? (
                <span className="inline-flex items-center gap-1 text-amber-600 dark:text-amber-400">
                  <AlertTriangle className="h-3.5 w-3.5" strokeWidth={2.1} aria-hidden />
                  <span className="tabular-nums">
                    {isZh ? `${recoveryCount} 待确认` : `${recoveryCount} waiting`}
                  </span>
                </span>
              ) : null}
              {runningCount > 0 ? (
                <span className="inline-flex items-center gap-1.5 text-emerald-700 dark:text-emerald-300">
                  <span className="relative flex h-2 w-2">
                    <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-500/45 motion-safe:animate-ping" />
                    <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
                  </span>
                  <span className="tabular-nums">
                    {isZh ? `${runningCount} 运行中` : `${runningCount} running`}
                  </span>
                </span>
              ) : null}
              {updatedCount > 0 ? (
                <span className="inline-flex items-center gap-1.5 text-foreground/85">
                  <span className="h-2 w-2 rounded-full bg-[#ff8a3d]" aria-hidden />
                  <span className="tabular-nums">
                    {isZh ? `${updatedCount} 新结果` : `${updatedCount} ready`}
                  </span>
                </span>
              ) : null}
              {attentionCount === 0 ? (
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/45" aria-hidden />
                  <span>{isZh ? "全部就绪" : "All quiet"}</span>
                </span>
              ) : null}
            </button>
          </PopoverTrigger>

          <PopoverContent
            align="end"
            sideOffset={8}
            className="w-[min(25rem,calc(100vw-1.5rem))] overflow-hidden p-0"
          >
            <div className="flex items-center justify-between border-b border-border/60 px-3.5 py-2.5">
              <div className="flex items-center gap-2">
                <span className="text-[13px] font-semibold text-foreground">
                  {isZh ? "跨项目实时动态" : "Live across projects"}
                </span>
                {attentionCount > 0 ? (
                  <span className="rounded-full bg-muted px-1.5 py-0.5 text-[11px] font-medium tabular-nums text-muted-foreground">
                    {attentionCount}
                  </span>
                ) : null}
              </div>
              <button
                type="button"
                onClick={() => {
                  setPulseOpen(false);
                  onOpenOverview(null);
                }}
                className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[11.5px] font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              >
                <span>{isZh ? "打开工作台" : "Overview"}</span>
                <ArrowRight className="h-3 w-3" aria-hidden />
              </button>
            </div>

            <div className="max-h-[24rem] overflow-y-auto overscroll-contain p-2">
              {attentionCount === 0 ? (
                <div className="flex flex-col items-center justify-center gap-1.5 py-8 text-center">
                  <LayoutGrid className="h-5 w-5 text-muted-foreground/50" aria-hidden />
                  <p className="text-[13px] font-medium text-foreground/85">
                    {isZh ? "当前没有运行中或待处理的会话" : "No running or pending sessions"}
                  </p>
                  <p className="text-[12px] text-muted-foreground">
                    {isZh
                      ? `共有 ${intelligence.open.length} 个在办会话分布在 ${intelligence.projects.filter((p) => p.openSessions.length > 0).length} 个工作区`
                      : `${intelligence.open.length} open sessions across ${intelligence.projects.filter((p) => p.openSessions.length > 0).length} workspaces`}
                  </p>
                </div>
              ) : (
                <ul className="space-y-1">
                  {intelligence.attention.map((item) => {
                    const isCurrent = activeSession?.session.key === item.session.key;
                    const canDone = item.attention === "updated" && item.session.projectLocked !== false;
                    return (
                      <li key={item.session.key}>
                        <div
                          className={cn(
                            "group flex items-start gap-2.5 rounded-xl px-2.5 py-2 transition-colors hover:bg-accent/70",
                            isCurrent && "bg-accent/60",
                          )}
                        >
                          <div className="mt-1 shrink-0">
                            <SessionStatusDot state={item.attention} />
                          </div>
                          <button
                            type="button"
                            onClick={() => {
                              setPulseOpen(false);
                              onSelectSession(item.session.key);
                            }}
                            className="min-w-0 flex-1 text-left"
                          >
                            <div className="flex items-center gap-1.5">
                              <span className="inline-flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
                                <ProjectDot color={item.project.dotColor} className="h-1.5 w-1.5" />
                                <span className="max-w-[8rem] truncate">{item.project.name}</span>
                              </span>
                              <span className="text-[10.5px] text-muted-foreground/60">·</span>
                              <span className="text-[11px] text-muted-foreground">
                                {item.attention === "recovery"
                                  ? (isZh ? "等待你确认" : "Needs attention")
                                  : item.attention === "running"
                                    ? (isZh ? "运行中" : "Running")
                                    : formatCompactRelativeTime(item.updatedMs, i18n.resolvedLanguage, nowMs)}
                              </span>
                            </div>
                            <p className="mt-0.5 line-clamp-2 text-[13px] font-medium leading-snug text-foreground">
                              {item.title}
                            </p>
                            {item.preview ? (
                              <p className="mt-0.5 truncate text-[11.5px] text-muted-foreground">
                                {item.preview}
                              </p>
                            ) : null}
                          </button>
                          <div className="flex shrink-0 flex-col items-end gap-1 pt-0.5">
                            {item.attention === "running" ? (
                              <LiveElapsedBadge
                                startedAtSec={item.session.runStartedAt}
                                nowMs={nowMs}
                              />
                            ) : null}
                            {canDone ? (
                              <HoverHint content={isZh ? "标记结单并归档" : "Mark done & archive"} side="left">
                                <button
                                  type="button"
                                  aria-label={isZh ? `结单：${item.title}` : `Done: ${item.title}`}
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    onDoneSession(item.session.key);
                                  }}
                                  className="inline-flex h-6 items-center gap-1 rounded-md border border-border/70 bg-background px-1.5 text-[11px] font-medium text-muted-foreground transition-colors hover:border-foreground/25 hover:text-foreground"
                                >
                                  <Check className="h-3 w-3" aria-hidden />
                                  <span>{doneLabel}</span>
                                </button>
                              </HoverHint>
                            ) : null}
                          </div>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </PopoverContent>
        </Popover>

        {canMarkActiveDone && activeSession ? (
          <HoverHint content={isZh ? "结单当前会话（归档，可撤销）" : "Mark current session done (archive)"} side="bottom">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              data-testid="topbar-done-button"
              onClick={() => onDoneSession(activeSession.session.key)}
              className="host-no-drag h-8 gap-1.5 rounded-control px-2.5 text-[12.5px] font-medium text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              <Check className="h-3.5 w-3.5" aria-hidden />
              <span className="hidden lg:inline">{doneLabel}</span>
            </Button>
          </HoverHint>
        ) : null}

        <HoverHint
          side="bottom"
          content={
            <span className="flex items-center gap-3">
              <span>{t("sidebar.newChat")}</span>
              <kbd className="font-sans text-muted-foreground">
                {sidebarShortcutLabel("newChat", apple)}
              </kbd>
            </span>
          }
        >
          <Button
            type="button"
            variant="ghost"
            size="icon"
            data-testid="topbar-new-chat-button"
            aria-label={t("sidebar.newChat")}
            onClick={onNewChat}
            className="host-no-drag h-8 w-8 rounded-control text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <Plus className="h-4 w-4" aria-hidden />
          </Button>
        </HoverHint>

        <HoverHint
          side="bottom"
          content={
            <span className="flex items-center gap-3">
              <span>{t("sidebar.searchAria")}</span>
              <kbd className="font-sans text-muted-foreground">
                {sidebarShortcutLabel("search", apple)}
              </kbd>
            </span>
          }
        >
          <button
            type="button"
            data-testid="topbar-search-button"
            aria-label={t("sidebar.searchAria")}
            onClick={onOpenSearch}
            className="host-no-drag inline-flex h-8 items-center gap-1.5 rounded-control border border-border/65 bg-muted/40 px-2 text-[12px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <SearchIcon className="h-3.5 w-3.5" />
            <kbd className="hidden font-sans text-[11px] sm:inline">
              {sidebarShortcutLabel("search", apple)}
            </kbd>
          </button>
        </HoverHint>

        <span aria-hidden className="mx-0.5 hidden h-4 w-px shrink-0 bg-border/75 sm:block" />

        {availableUpdate && onOpenUpdates ? (
          <HoverHint content={t("update.available", { version: availableUpdate.version, defaultValue: `Update ${availableUpdate.version}` })} side="bottom">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={t("update.available", { version: availableUpdate.version, defaultValue: `Update ${availableUpdate.version}` })}
              onClick={availableUpdate.onRequestUpdate ?? onOpenUpdates}
              className="host-no-drag h-8 w-8 rounded-control text-emerald-600 hover:bg-emerald-500/10 dark:text-emerald-400"
            >
              <ArrowUpCircle className="h-4 w-4" aria-hidden />
            </Button>
          </HoverHint>
        ) : null}

        <div className="hidden items-center gap-0.5 sm:flex">
          <HoverHint
            side="bottom"
            content={
              <span className="flex items-center gap-3">
                <span>{t("sidebar.apps")}</span>
                <kbd className="font-sans text-muted-foreground">
                  {sidebarShortcutLabel("apps", apple)}
                </kbd>
              </span>
            }
          >
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={t("sidebar.apps")}
              aria-current={view === "apps" ? "page" : undefined}
              onClick={onOpenApps}
              className={cn(
                "host-no-drag h-8 w-8 rounded-control",
                view === "apps"
                  ? "bg-accent text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              <AppsIcon className="h-4 w-4" />
            </Button>
          </HoverHint>

          <HoverHint
            side="bottom"
            content={
              <span className="flex items-center gap-3">
                <span>{t("sidebar.automations", { defaultValue: "Automations" })}</span>
                <kbd className="font-sans text-muted-foreground">
                  {sidebarShortcutLabel("automations", apple)}
                </kbd>
              </span>
            }
          >
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={t("sidebar.automations", { defaultValue: "Automations" })}
              aria-current={view === "automations" ? "page" : undefined}
              onClick={onOpenAutomations}
              className={cn(
                "host-no-drag h-8 w-8 rounded-control",
                view === "automations"
                  ? "bg-accent text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              <AutomationsIcon className="h-4 w-4" />
            </Button>
          </HoverHint>

          <HoverHint
            side="bottom"
            content={
              <span className="flex items-center gap-3">
                <span>{t("sidebar.settings")}</span>
                <kbd className="font-sans text-muted-foreground">
                  {sidebarShortcutLabel("settings", apple)}
                </kbd>
              </span>
            }
          >
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={t("sidebar.settings")}
              aria-current={view === "settings" ? "page" : undefined}
              onClick={onOpenSettings}
              onPointerEnter={onSettingsIntent}
              onFocus={onSettingsIntent}
              className={cn(
                "host-no-drag h-8 w-8 rounded-control",
                view === "settings"
                  ? "bg-accent text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              <SettingsIcon className="h-4 w-4" />
            </Button>
          </HoverHint>

          <HoverHint content={t("thread.header.toggleTheme")} side="bottom">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={t("thread.header.toggleTheme")}
              onClick={onToggleTheme}
              className="host-no-drag h-8 w-8 rounded-control text-muted-foreground hover:text-foreground"
            >
              <ThemeToggleIcon theme={theme} />
            </Button>
          </HoverHint>
        </div>
      </div>
    </header>
  );
}
