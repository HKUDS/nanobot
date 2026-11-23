import { useState } from "react";
import {
  ArrowRight,
  ArrowUpCircle,
  Check,
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
  SessionStatusDot,
  ZenDoneCircle,
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
  const inChat = view === "chat";

  // Calm single-line summary for the pulse whisper button
  const pulseSummary = (() => {
    const parts: string[] = [];
    if (runningCount > 0) parts.push(isZh ? `${runningCount} 运行` : `${runningCount} running`);
    if (recoveryCount > 0) parts.push(isZh ? `${recoveryCount} 待确认` : `${recoveryCount} waiting`);
    if (updatedCount > 0) parts.push(isZh ? `${updatedCount} 新结果` : `${updatedCount} ready`);
    return parts.join(" · ");
  })();

  const primaryPulseState = recoveryCount > 0
    ? "recovery"
    : runningCount > 0
      ? "running"
      : updatedCount > 0
        ? "updated"
        : "idle";

  return (
    <header
      data-testid="workspace-top-bar"
      data-theme-surface
      className={cn(
        "group/topbar relative z-30 flex h-12 shrink-0 items-center justify-between gap-3 bg-background/85 px-4 backdrop-blur-md transition-colors",
        !inChat && "border-b border-border/35",
        hostChromeInset && "pl-[4.75rem]",
      )}
    >
      {/* Left: Quiet Brand / Overview + Drawer + Minimal Breadcrumb */}
      <div className="flex min-w-0 flex-1 items-center gap-1.5">
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
              "host-no-drag inline-flex h-8 shrink-0 items-center gap-2 rounded-lg px-1.5 text-[13px] transition-colors",
              view === "overview"
                ? "font-medium text-foreground"
                : "text-muted-foreground/80 hover:bg-foreground/[0.04] hover:text-foreground",
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
              "host-no-drag h-7 w-7 shrink-0 rounded-lg transition-colors",
              drawerOpen || drawerPinned
                ? "bg-foreground/[0.07] text-foreground"
                : "text-muted-foreground/65 hover:bg-foreground/[0.04] hover:text-foreground",
            )}
          >
            <PanelLeft className="h-[15px] w-[15px]" strokeWidth={1.75} aria-hidden />
          </Button>
        </HoverHint>

        {/* Contextual Breadcrumb in Chat — quiet editorial slashes, no pill noise */}
        {inChat && (activeSession || activeTemporaryTitle) ? (
          <nav
            aria-label={isZh ? "当前上下文" : "Current context"}
            className="hidden min-w-0 items-center gap-1.5 pl-1 text-[12.5px] md:flex"
          >
            <span aria-hidden className="text-foreground/18">/</span>
            {activeSession ? (
              <>
                <button
                  type="button"
                  onClick={() => onOpenOverview(activeSession.project.id)}
                  className="host-no-drag max-w-[9rem] shrink-0 truncate rounded-md px-1.5 py-0.5 text-muted-foreground/80 transition-colors hover:bg-foreground/[0.04] hover:text-foreground"
                >
                  {activeSession.project.name}
                </button>
                <span aria-hidden className="text-foreground/18">/</span>
                {activeWorkbenchGroup && activeWorkbenchGroup.panes.length > 1 ? (
                  <div className="flex min-w-0 items-center gap-1">
                    {activeWorkbenchGroup.panes.map((pane, idx) => {
                      const paneActive = pane.session.key === activeSession.session.key;
                      return (
                        <span key={pane.session.key} className="inline-flex min-w-0 items-center gap-1">
                          {idx > 0 ? <span aria-hidden className="text-foreground/15">·</span> : null}
                          <button
                            type="button"
                            onClick={() => onSelectSession(pane.session.key)}
                            className={cn(
                              "host-no-drag inline-flex max-w-[11rem] items-center gap-1.5 rounded-md px-1.5 py-0.5 transition-colors",
                              paneActive
                                ? "font-medium text-foreground"
                                : "text-muted-foreground/70 hover:text-foreground",
                            )}
                          >
                            {pane.attention !== "idle" ? (
                              <SessionStatusDot state={pane.attention} size="sm" />
                            ) : null}
                            <span className="truncate">{pane.title}</span>
                          </button>
                        </span>
                      );
                    })}
                  </div>
                ) : (
                  <div className="flex min-w-0 items-center gap-2 px-1">
                    <span className="max-w-[18rem] truncate font-medium text-foreground/90">
                      {activeSession.title}
                    </span>
                    <MutedHandleBadge handle={activeSession.session.handle} />
                  </div>
                )}
              </>
            ) : (
              <span className="max-w-[16rem] truncate px-1 font-medium text-foreground/90">
                {activeTemporaryTitle}
              </span>
            )}
          </nav>
        ) : (
          <div className="hidden pl-1 sm:flex sm:items-center">
            <HostSwitcher
              menuSide="bottom"
              className="h-7 rounded-lg px-2 text-[12px] text-muted-foreground/70 hover:bg-foreground/[0.04] hover:text-foreground"
            />
          </div>
        )}
      </div>

      {/* Right: Quiet Live Pulse + Subtle Actions (recede during chat focus, awaken on hover) */}
      <div className="flex shrink-0 items-center gap-1">
        <Popover open={pulseOpen} onOpenChange={setPulseOpen}>
          <PopoverTrigger asChild>
            <button
              type="button"
              data-testid="live-pulse-trigger"
              className={cn(
                "host-no-drag inline-flex h-8 items-center gap-2 rounded-full px-2.5 text-[12px] transition-all duration-150",
                attentionCount > 0
                  ? "bg-foreground/[0.035] font-medium text-foreground/85 hover:bg-foreground/[0.065]"
                  : "text-muted-foreground/60 hover:bg-foreground/[0.04] hover:text-foreground",
              )}
            >
              <SessionStatusDot state={primaryPulseState} size="sm" />
              <span className="tabular-nums">
                {attentionCount > 0 ? pulseSummary : (isZh ? "静默" : "Quiet")}
              </span>
            </button>
          </PopoverTrigger>

          <PopoverContent
            align="end"
            sideOffset={10}
            className="w-[min(24rem,calc(100vw-1.5rem))] overflow-hidden rounded-2xl border border-border/60 bg-popover/96 p-0 shadow-[0_16px_48px_rgba(15,23,42,0.12)] backdrop-blur-xl dark:shadow-[0_16px_48px_rgba(0,0,0,0.45)]"
          >
            <div className="flex items-center justify-between px-4 pb-2.5 pt-3.5">
              <span className="text-[12.5px] font-medium text-foreground/85">
                {isZh ? "跨项目实时动态" : "Live across workspaces"}
              </span>
              <button
                type="button"
                onClick={() => {
                  setPulseOpen(false);
                  onOpenOverview(null);
                }}
                className="inline-flex items-center gap-1 text-[11.5px] text-muted-foreground transition-colors hover:text-foreground"
              >
                <span>{isZh ? "全部总览" : "Overview"}</span>
                <ArrowRight className="h-3 w-3" aria-hidden />
              </button>
            </div>

            <div className="max-h-[24rem] overflow-y-auto overscroll-contain px-2 pb-2.5">
              {attentionCount === 0 ? (
                <div className="px-4 py-8 text-center">
                  <p className="text-[13px] text-foreground/80">
                    {isZh ? "此刻风平浪静" : "Everything is quiet"}
                  </p>
                  <p className="mt-1 text-[12px] text-muted-foreground/75">
                    {isZh
                      ? `${intelligence.open.length} 项在办分布在 ${intelligence.projects.filter((p) => p.openSessions.length > 0).length} 个工作区`
                      : `${intelligence.open.length} open across ${intelligence.projects.filter((p) => p.openSessions.length > 0).length} workspaces`}
                  </p>
                </div>
              ) : (
                <ul className="space-y-0.5">
                  {intelligence.attention.map((item) => {
                    const isCurrent = activeSession?.session.key === item.session.key;
                    const canDone = item.attention === "updated" && item.session.projectLocked !== false;
                    return (
                      <li key={item.session.key}>
                        <div
                          className={cn(
                            "group flex items-start gap-2.5 rounded-xl px-2.5 py-2.5 transition-colors hover:bg-foreground/[0.04]",
                            isCurrent && "bg-foreground/[0.045]",
                          )}
                        >
                          <div className="mt-[3px] shrink-0">
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
                            <p className="line-clamp-2 text-[13px] font-medium leading-[1.4] text-foreground">
                              {item.title}
                            </p>
                            <div className="mt-1 flex items-center gap-1.5 text-[11.5px] text-muted-foreground/75">
                              <span className="max-w-[8rem] truncate">{item.project.name}</span>
                              <span aria-hidden className="opacity-45">·</span>
                              <span>
                                {item.attention === "recovery"
                                  ? (isZh ? "等你确认" : "Needs attention")
                                  : item.attention === "running"
                                    ? (isZh ? "推进中" : "Running")
                                    : formatCompactRelativeTime(item.updatedMs, i18n.resolvedLanguage, nowMs)}
                              </span>
                            </div>
                          </button>
                          <div className="flex shrink-0 items-center gap-2 pt-0.5">
                            {item.attention === "running" ? (
                              <LiveElapsedBadge
                                startedAtSec={item.session.runStartedAt}
                                nowMs={nowMs}
                              />
                            ) : null}
                            {canDone ? (
                              <ZenDoneCircle
                                label={isZh ? `结单：${item.title}` : `Done: ${item.title}`}
                                onClick={() => onDoneSession(item.session.key)}
                                className="opacity-65 transition-opacity group-hover:opacity-100"
                              />
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
          <HoverHint content={isZh ? "结单当前会话（归档，可撤销）" : "Mark current session done"} side="bottom">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              data-testid="topbar-done-button"
              onClick={() => onDoneSession(activeSession.session.key)}
              className="host-no-drag h-7 gap-1.5 rounded-lg px-2 text-[12px] font-normal text-muted-foreground/75 transition-colors hover:bg-foreground/[0.045] hover:text-foreground"
            >
              <Check className="h-3.5 w-3.5" strokeWidth={1.9} aria-hidden />
              <span className="hidden lg:inline">{doneLabel}</span>
            </Button>
          </HoverHint>
        ) : null}

        {/* Quiet utility controls — gently recessed during active reading/chat */}
        <div
          className={cn(
            "flex items-center gap-0.5 transition-opacity duration-200",
            inChat && "opacity-60 hover:opacity-100 focus-within:opacity-100 group-hover/topbar:opacity-100",
          )}
        >
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
              className="host-no-drag h-7 w-7 rounded-lg text-muted-foreground hover:bg-foreground/[0.05] hover:text-foreground"
            >
              <Plus className="h-4 w-4" strokeWidth={1.75} aria-hidden />
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
            <Button
              type="button"
              variant="ghost"
              size="icon"
              data-testid="topbar-search-button"
              aria-label={t("sidebar.searchAria")}
              onClick={onOpenSearch}
              className="host-no-drag h-7 w-7 rounded-lg text-muted-foreground hover:bg-foreground/[0.05] hover:text-foreground"
            >
              <SearchIcon className="h-[15px] w-[15px]" />
            </Button>
          </HoverHint>

          {availableUpdate && onOpenUpdates ? (
            <HoverHint
              content={t("update.available", {
                version: availableUpdate.version,
                defaultValue: `Update ${availableUpdate.version}`,
              })}
              side="bottom"
            >
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={t("update.available", {
                  version: availableUpdate.version,
                  defaultValue: `Update ${availableUpdate.version}`,
                })}
                onClick={availableUpdate.onRequestUpdate ?? onOpenUpdates}
                className="host-no-drag h-7 w-7 rounded-lg text-emerald-600 hover:bg-emerald-500/10 dark:text-emerald-400"
              >
                <ArrowUpCircle className="h-[15px] w-[15px]" aria-hidden />
              </Button>
            </HoverHint>
          ) : null}

          <div className="hidden items-center gap-0.5 sm:flex">
            {inChat ? (
              <HostSwitcher
                collapsed
                menuSide="bottom"
                className="h-7 w-7 rounded-lg text-muted-foreground hover:bg-foreground/[0.05] hover:text-foreground"
              />
            ) : null}

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
                  "host-no-drag h-7 w-7 rounded-lg",
                  view === "apps"
                    ? "bg-foreground/[0.07] text-foreground"
                    : "text-muted-foreground hover:bg-foreground/[0.05] hover:text-foreground",
                )}
              >
                <AppsIcon className="h-[15px] w-[15px]" />
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
                  "host-no-drag h-7 w-7 rounded-lg",
                  view === "automations"
                    ? "bg-foreground/[0.07] text-foreground"
                    : "text-muted-foreground hover:bg-foreground/[0.05] hover:text-foreground",
                )}
              >
                <AutomationsIcon className="h-[15px] w-[15px]" />
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
                  "host-no-drag h-7 w-7 rounded-lg",
                  view === "settings"
                    ? "bg-foreground/[0.07] text-foreground"
                    : "text-muted-foreground hover:bg-foreground/[0.05] hover:text-foreground",
                )}
              >
                <SettingsIcon className="h-[15px] w-[15px]" />
              </Button>
            </HoverHint>

            <HoverHint content={t("thread.header.toggleTheme")} side="bottom">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={t("thread.header.toggleTheme")}
                onClick={onToggleTheme}
                className="host-no-drag h-7 w-7 rounded-lg text-muted-foreground hover:bg-foreground/[0.05] hover:text-foreground"
              >
                <ThemeToggleIcon theme={theme} />
              </Button>
            </HoverHint>
          </div>
        </div>
      </div>
    </header>
  );
}
