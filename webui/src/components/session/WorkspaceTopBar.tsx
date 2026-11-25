import { useState } from "react";
import {
  ArrowRight,
  ArrowUpCircle,
  MoreHorizontal,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  AppsIcon,
  ArchiveIcon,
  AutomationsIcon,
  ComposeIcon,
  SearchIcon,
  SettingsIcon,
} from "@/components/icons/product-icons";
import { ThemeToggleIcon } from "@/components/icons/ThemeToggleIcon";
import { HostSwitcher } from "@/components/remote/HostSwitcher";
import {
  LiveElapsedBadge,
  MutedHandleBadge,
  SessionStatusDot,
  SidebarDrawerIcon,
  ZenDoneCircle,
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
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  formatCompactRelativeTime,
  type DecoupledWorkbenchGroup,
  type EnrichedSession,
  type SessionIntelligenceSnapshot,
} from "@/lib/session-intelligence";
import { sidebarShortcutAria, sidebarShortcutLabel } from "@/lib/sidebar-shortcuts";
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
  onThreadActionsHostChange?: (element: HTMLDivElement | null) => void;
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
  onThreadActionsHostChange,
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

  const brandLabel = "nanobot";
  const homeHintLabel = isZh ? "主页" : "Home";
  const drawerLabel = drawerOpen || drawerPinned
    ? (isZh ? "收起侧边栏" : "Hide sidebar")
    : (isZh ? "展开侧边栏" : "Show sidebar");
  const themeToggleLabel = theme === "dark"
    ? (isZh ? "切换浅色模式" : "Switch to light mode")
    : (isZh ? "切换深色模式" : "Switch to dark mode");
  const inChat = view === "chat";
  const isSplitChat = inChat && Boolean(activeWorkbenchGroup && activeWorkbenchGroup.panes.length > 1);

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
      data-workspace-topbar=""
      data-theme-surface
      className={cn(
        "group/topbar relative z-30 flex h-12 shrink-0 items-center justify-between gap-2 bg-background/85 px-3 backdrop-blur-md transition-colors sm:gap-3 sm:px-4",
        (!inChat || isSplitChat) && "border-b border-border/35 dark:border-white/[0.07]",
        hostChromeInset && "host-drag-region pl-[4.75rem]",
      )}
    >
      {/* Left: Quiet Brand / Overview + Drawer + Minimal Breadcrumb */}
      <div className="flex min-w-0 flex-1 items-center gap-1.5">
        <HoverHint
          side="bottom"
          content={
            <span className="flex items-center gap-3">
              <span>{homeHintLabel}</span>
              <kbd className="font-sans text-muted-foreground">
                {sidebarShortcutLabel("overview", apple)}
              </kbd>
            </span>
          }
        >
          <button
            type="button"
            data-testid="topbar-overview-button"
            aria-label={homeHintLabel}
            aria-keyshortcuts={sidebarShortcutAria("overview")}
            aria-current={view === "overview" ? "page" : undefined}
            onClick={() => onOpenOverview(null)}
            className={cn(
              "host-no-drag inline-flex h-7 shrink-0 items-center gap-2 rounded-lg px-1.5 text-[13.5px] leading-none tracking-[-0.01em] transition-colors",
              view === "overview"
                ? "font-medium text-foreground"
                : "text-muted-foreground/85 hover:bg-foreground/[0.04] hover:text-foreground",
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
            <span className="hidden sm:inline">{brandLabel}</span>
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
          <button
            type="button"
            data-testid="topbar-drawer-toggle"
            aria-label={drawerLabel}
            aria-keyshortcuts={sidebarShortcutAria("drawer")}
            aria-pressed={drawerOpen || drawerPinned}
            onClick={onToggleDrawer}
            className={cn(
              "host-no-drag inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg transition-colors hover:bg-foreground/[0.05] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40",
              drawerOpen || drawerPinned
                ? "text-foreground"
                : "text-muted-foreground/70",
            )}
          >
            <SidebarDrawerIcon open={drawerOpen || drawerPinned} />
          </button>
        </HoverHint>

        {/* Compact mobile session title when in chat (< md) */}
        {inChat && (activeSession || activeTemporaryTitle) ? (
          <div className="flex min-w-0 flex-1 items-center gap-1 pl-0.5 text-[13px] md:hidden">
            <span
              title={activeSession ? activeSession.title : (activeTemporaryTitle ?? undefined)}
              className="truncate font-medium text-foreground/90"
            >
              {activeSession ? activeSession.title : activeTemporaryTitle}
            </span>
          </div>
        ) : null}

        {/* Contextual surface breadcrumb for Settings / Apps / Automations */}
        {(view === "settings" || view === "apps" || view === "automations") ? (
          <nav
            aria-label={isZh ? "当前上下文" : "Current context"}
            className="flex min-w-0 items-center gap-1.5 pl-1 text-[12.5px]"
          >
            <span aria-hidden className="text-foreground/20">/</span>
            <span className="truncate font-medium text-foreground/90">
              {view === "settings"
                ? t("sidebar.settings")
                : view === "apps"
                  ? t("sidebar.apps")
                  : t("sidebar.automations", { defaultValue: "Automations" })}
            </span>
          </nav>
        ) : null}

        {/* Contextual Breadcrumb in Chat — quiet editorial slashes, no pill noise */}
        {inChat && (activeSession || activeTemporaryTitle) ? (
          <nav
            aria-label={isZh ? "当前上下文" : "Current context"}
            className="hidden min-w-0 flex-1 items-center gap-1.5 overflow-hidden pl-1 text-[12.5px] md:flex"
          >
            <span aria-hidden className="shrink-0 text-foreground/20">/</span>
            {activeSession ? (
              <>
                <button
                  type="button"
                  title={activeSession.project.name}
                  onClick={() => onOpenOverview(activeSession.project.id)}
                  className="host-no-drag inline-flex h-7 max-w-[6.5rem] shrink-0 items-center truncate rounded-md px-1.5 text-muted-foreground/80 transition-colors hover:bg-foreground/[0.04] hover:text-foreground xl:max-w-[9rem]"
                >
                  <span className="truncate">{activeSession.project.name}</span>
                </button>
                <span aria-hidden className="shrink-0 text-foreground/20">/</span>
                {activeWorkbenchGroup && activeWorkbenchGroup.panes.length > 1 ? (
                  <div className="flex min-w-0 flex-1 items-center gap-1 overflow-hidden">
                    {activeWorkbenchGroup.panes.map((pane, idx) => {
                      const paneActive = pane.session.key === activeSession.session.key;
                      return (
                        <span key={pane.session.key} className="inline-flex min-w-0 shrink items-center gap-1">
                          {idx > 0 ? <span aria-hidden className="shrink-0 text-foreground/15">·</span> : null}
                          <button
                            type="button"
                            title={pane.title}
                            aria-current={paneActive ? "page" : undefined}
                            onClick={() => onSelectSession(pane.session.key)}
                            className={cn(
                              "host-no-drag inline-flex h-7 min-w-0 max-w-[7.5rem] shrink items-center gap-1.5 overflow-hidden rounded-md px-2 transition-colors xl:max-w-[11rem]",
                              paneActive
                                ? "bg-foreground/[0.055] font-medium text-foreground dark:bg-white/[0.08]"
                                : "text-muted-foreground/70 hover:bg-foreground/[0.035] hover:text-foreground",
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
                  <div className="flex min-w-0 flex-1 items-center gap-2 overflow-hidden px-1">
                    <span
                      title={activeSession.title}
                      className="min-w-0 truncate font-medium text-foreground/90"
                    >
                      {activeSession.title}
                    </span>
                    <MutedHandleBadge handle={activeSession.session.handle} className="hidden lg:inline" />
                  </div>
                )}
              </>
            ) : (
              <span
                title={activeTemporaryTitle ?? undefined}
                className="min-w-0 max-w-[16rem] truncate px-1 font-medium text-foreground/90"
              >
                {activeTemporaryTitle}
              </span>
            )}
          </nav>
        ) : null}
      </div>

      {/* Right: Quiet Live Pulse (shown outside Overview so Overview stays uncluttered) + Optically Aligned Action Groups */}
      <div className="flex h-7 shrink-0 items-center">
        {view !== "overview" ? (
        <Popover open={pulseOpen} onOpenChange={setPulseOpen}>
          <PopoverTrigger asChild>
            <button
              type="button"
              data-testid="live-pulse-trigger"
              aria-label={attentionCount > 0 ? pulseSummary : (isZh ? "空闲" : "Idle")}
              className={cn(
                "host-no-drag mr-1 inline-flex h-7 items-center gap-1.5 rounded-full px-2 text-[12px] leading-none transition-all duration-150 sm:mr-1.5 sm:gap-2 sm:px-2.5",
                attentionCount > 0
                  ? "bg-foreground/[0.035] font-medium text-foreground/85 hover:bg-foreground/[0.065] dark:bg-white/[0.05] dark:hover:bg-white/[0.09]"
                  : "text-muted-foreground/60 hover:bg-foreground/[0.04] hover:text-foreground",
              )}
            >
              <SessionStatusDot state={primaryPulseState} size="sm" />
              {attentionCount > 0 ? (
                <>
                  <span className={cn("tabular-nums", isSplitChat ? "xl:hidden" : "sm:hidden")}>
                    {attentionCount}
                  </span>
                  <span
                    className={cn(
                      "hidden max-w-[14rem] truncate tabular-nums",
                      isSplitChat ? "xl:inline" : "sm:inline",
                    )}
                  >
                    {pulseSummary}
                  </span>
                </>
              ) : (
                <span className={cn("hidden tabular-nums", isSplitChat ? "xl:inline" : "sm:inline")}>
                  {isZh ? "空闲" : "Idle"}
                </span>
              )}
            </button>
          </PopoverTrigger>

          <PopoverContent
            align="end"
            sideOffset={10}
            className="w-[min(24rem,calc(100vw-1.5rem))] overflow-hidden rounded-2xl border border-border/60 bg-popover/95 p-0 shadow-[0_16px_48px_rgba(15,23,42,0.12)] backdrop-blur-xl dark:border-white/[0.08] dark:shadow-[0_16px_48px_rgba(0,0,0,0.45)]"
          >
            <div className="flex items-center justify-between border-b border-border/35 px-4 py-3 dark:border-white/[0.06]">
              <span className="text-[12.5px] font-medium text-foreground/85">
                {isZh ? "运行状态" : "Activity"}
              </span>
              <button
                type="button"
                onClick={() => {
                  setPulseOpen(false);
                  onOpenOverview(null);
                }}
                className="inline-flex items-center gap-1 text-[11.5px] text-muted-foreground transition-colors hover:text-foreground"
              >
                <span>{isZh ? "查看全部" : "View all"}</span>
                <ArrowRight className="h-3 w-3" aria-hidden />
              </button>
            </div>

            <div
              className={cn(
                "max-h-[22rem] overflow-y-auto overscroll-contain px-2 py-1.5",
                attentionCount > 5 && "pb-4 [mask-image:linear-gradient(to_bottom,black_calc(100%-16px),transparent)]",
              )}
            >
              {attentionCount === 0 ? (
                <div className="px-4 py-8 text-center">
                  <p className="text-[13px] text-foreground/80">
                    {isZh ? "暂无运行中的任务" : "No active tasks"}
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
                              {item.attention !== "running" ? (
                                <>
                                  <span aria-hidden className="opacity-45">·</span>
                                  <span>
                                    {item.attention === "recovery"
                                      ? (isZh ? "待确认" : "Waiting")
                                      : formatCompactRelativeTime(item.updatedMs, i18n.resolvedLanguage, nowMs)}
                                  </span>
                                </>
                              ) : null}
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
                                label={isZh ? `归档：${item.title}` : `Archive: ${item.title}`}
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
        ) : null}

        {/* Active thread actions (Session automations, prompt search, pane layout, add pane, archive) */}
        <div className="flex h-7 shrink-0 items-center gap-0.5">
          <div
            ref={onThreadActionsHostChange}
            data-testid="topbar-thread-actions"
            className="host-no-drag flex h-7 shrink-0 items-center gap-0.5 empty:hidden [&_button]:inline-flex [&_button]:h-7 [&_button]:w-7 [&_button]:items-center [&_button]:justify-center [&_button]:rounded-lg [&_button]:p-0 [&_button]:text-muted-foreground/80 [&_button:hover]:bg-foreground/[0.05] [&_button:hover]:text-foreground [&_svg]:h-4 [&_svg]:w-4"
          />

          {canMarkActiveDone && activeSession ? (
            <HoverHint content={isZh ? "归档会话" : "Archive session"} side="bottom">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                data-testid="topbar-done-button"
                aria-label={isZh ? "归档会话" : "Archive session"}
                onClick={() => onDoneSession(activeSession.session.key)}
                className="host-no-drag hidden h-7 w-7 rounded-lg p-0 text-muted-foreground/80 transition-colors hover:bg-foreground/[0.05] hover:text-foreground sm:inline-flex"
              >
                <ArchiveIcon className="h-4 w-4" />
              </Button>
            </HoverHint>
          ) : null}
        </div>

        {inChat ? (
          <span aria-hidden className="mx-1.5 hidden h-3.5 w-px shrink-0 bg-border/55 sm:inline-block" />
        ) : null}

        {/* Quiet utility controls — gently recessed during active reading/chat on hover-capable devices */}
        <div
          className={cn(
            "flex h-7 items-center gap-0.5 transition-opacity duration-200",
            inChat && "media-hover:opacity-60 hover:opacity-100 focus-within:opacity-100 group-hover/topbar:opacity-100",
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
              aria-keyshortcuts={sidebarShortcutAria("newChat")}
              onClick={onNewChat}
              className={cn(
                "host-no-drag h-7 w-7 rounded-lg p-0 text-muted-foreground hover:bg-foreground/[0.05] hover:text-foreground",
                inChat && "hidden sm:inline-flex",
              )}
            >
              <ComposeIcon className="h-4 w-4" />
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
              aria-keyshortcuts={sidebarShortcutAria("search")}
              onClick={onOpenSearch}
              className="host-no-drag h-7 w-7 rounded-lg p-0 text-muted-foreground hover:bg-foreground/[0.05] hover:text-foreground"
            >
              <SearchIcon className="h-4 w-4" />
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
                className="host-no-drag h-7 w-7 rounded-lg p-0 text-emerald-600 hover:bg-emerald-500/10 dark:text-emerald-400"
              >
                <ArrowUpCircle className="h-4 w-4" aria-hidden />
              </Button>
            </HoverHint>
          ) : null}

          {/* Mobile (< sm) overflow menu so Chat actions + Apps, Automations, Settings & Theme stay uncluttered */}
          <div className="flex items-center sm:hidden">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  data-testid="topbar-mobile-menu"
                  aria-label={isZh ? "更多" : "More"}
                  className="host-no-drag inline-flex h-7 w-7 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-foreground/[0.05] hover:text-foreground data-[state=open]:bg-foreground/[0.08] data-[state=open]:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 dark:data-[state=open]:bg-white/[0.10]"
                >
                  <MoreHorizontal className="h-4 w-4" aria-hidden />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-44">
                {inChat ? (
                  <>
                    <DropdownMenuItem onSelect={onNewChat}>
                      <ComposeIcon className="h-3.5 w-3.5" />
                      {t("sidebar.newChat")}
                    </DropdownMenuItem>
                    {canMarkActiveDone && activeSession ? (
                      <DropdownMenuItem onSelect={() => onDoneSession(activeSession.session.key)}>
                        <ArchiveIcon className="h-3.5 w-3.5" />
                        {isZh ? "归档会话" : "Archive session"}
                      </DropdownMenuItem>
                    ) : null}
                    <DropdownMenuSeparator />
                  </>
                ) : null}
                <DropdownMenuItem onSelect={onOpenApps}>
                  <AppsIcon className="h-3.5 w-3.5" />
                  {t("sidebar.apps")}
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={onOpenAutomations}>
                  <AutomationsIcon className="h-3.5 w-3.5" />
                  {t("sidebar.automations", { defaultValue: "Automations" })}
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={onOpenSettings}>
                  <SettingsIcon className="h-3.5 w-3.5" />
                  {t("sidebar.settings")}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={onToggleTheme}>
                  <ThemeToggleIcon theme={theme} className="h-3.5 w-3.5" />
                  {themeToggleLabel}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>

          <div className="hidden h-7 items-center gap-0.5 sm:flex">
            <HostSwitcher
              collapsed
              menuSide="bottom"
              className="h-7 w-7 rounded-lg p-0 text-muted-foreground hover:bg-foreground/[0.05] hover:text-foreground [&_span[aria-hidden]]:ring-background"
            />

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
                aria-keyshortcuts={sidebarShortcutAria("apps")}
                aria-current={view === "apps" ? "page" : undefined}
                onClick={onOpenApps}
                onPointerEnter={onSettingsIntent}
                onFocus={onSettingsIntent}
                className={cn(
                  "host-no-drag h-7 w-7 rounded-lg p-0",
                  view === "apps"
                    ? "bg-foreground/[0.07] text-foreground dark:bg-white/[0.10]"
                    : "text-muted-foreground hover:bg-foreground/[0.05] hover:text-foreground",
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
                aria-keyshortcuts={sidebarShortcutAria("automations")}
                aria-current={view === "automations" ? "page" : undefined}
                onClick={onOpenAutomations}
                onPointerEnter={onSettingsIntent}
                onFocus={onSettingsIntent}
                className={cn(
                  "host-no-drag h-7 w-7 rounded-lg p-0",
                  view === "automations"
                    ? "bg-foreground/[0.07] text-foreground dark:bg-white/[0.10]"
                    : "text-muted-foreground hover:bg-foreground/[0.05] hover:text-foreground",
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
                aria-keyshortcuts={sidebarShortcutAria("settings")}
                aria-current={view === "settings" ? "page" : undefined}
                onClick={onOpenSettings}
                onPointerEnter={onSettingsIntent}
                onFocus={onSettingsIntent}
                className={cn(
                  "host-no-drag h-7 w-7 rounded-lg p-0",
                  view === "settings"
                    ? "bg-foreground/[0.07] text-foreground dark:bg-white/[0.10]"
                    : "text-muted-foreground hover:bg-foreground/[0.05] hover:text-foreground",
                )}
              >
                <SettingsIcon className="h-4 w-4" />
              </Button>
            </HoverHint>

            <HoverHint content={themeToggleLabel} side="bottom">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={themeToggleLabel}
                onClick={onToggleTheme}
                className="host-no-drag h-7 w-7 rounded-lg p-0 text-muted-foreground hover:bg-foreground/[0.05] hover:text-foreground"
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
