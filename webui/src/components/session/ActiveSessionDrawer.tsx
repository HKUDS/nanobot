import { useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Check,
  ChevronDown,
  MessageCircleDashed,
  MoreHorizontal,
  PanelsTopLeft,
  Pencil,
  Pin,
  PinOff,
  Plus,
  Trash2,
  X,
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
import {
  formatCompactRelativeTime,
  type EnrichedSession,
  type SessionIntelligenceSnapshot,
} from "@/lib/session-intelligence";
import { deriveTemporaryChatTitle } from "@/lib/temporary-chat";
import type { ChatSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface ActiveSessionDrawerProps {
  open: boolean;
  pinned: boolean;
  intelligence: SessionIntelligenceSnapshot;
  temporarySessions: ChatSummary[];
  activeKey: string | null;
  collapsedGroups: Record<string, boolean>;
  onClose: () => void;
  onTogglePinDrawer: () => void;
  onSelectSession: (key: string) => void;
  onCloseTemporaryChat?: (key: string) => void;
  onToggleGroup: (groupId: string) => void;
  onNewChat: () => void;
  onNewChatInProject: (projectPath: string, projectName: string) => void;
  onTogglePinSession: (key: string) => void;
  onArchiveSession: (key: string) => void;
  onRequestRename: (key: string, title: string) => Promise<void>;
  onRequestDeleteMany: (items: SidebarDeleteItem[]) => void;
  onCreateTab?: (paneKey: string) => void;
  onOpenOverviewDone: () => void;
}

export function ActiveSessionDrawer({
  open,
  pinned,
  intelligence,
  temporarySessions,
  activeKey,
  collapsedGroups,
  onClose,
  onTogglePinDrawer,
  onSelectSession,
  onCloseTemporaryChat,
  onToggleGroup,
  onNewChat,
  onNewChatInProject,
  onTogglePinSession,
  onArchiveSession,
  onRequestRename,
  onRequestDeleteMany,
  onCreateTab,
  onOpenOverviewDone,
}: ActiveSessionDrawerProps) {
  const { t, i18n } = useTranslation();
  const isZh = Boolean(i18n.resolvedLanguage?.startsWith("zh"));
  const visible = open || pinned;
  const nowMs = useLiveClock(visible && intelligence.running.length > 0, 1000);
  const [renamingKey, setRenamingKey] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");

  useEffect(() => {
    if (!open || pinned) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose, open, pinned]);

  if (!visible) return null;

  const handleSelect = (key: string) => {
    onSelectSession(key);
    if (!pinned) onClose();
  };

  const openProjects = intelligence.projects.filter((group) => group.openSessions.length > 0);

  const drawerPanel = (
    <aside
      data-testid="active-session-drawer"
      data-pinned={pinned ? "true" : undefined}
      aria-label={isZh ? "在办会话抽屉" : "Active sessions drawer"}
      className={cn(
        "flex h-full w-[min(19.5rem,calc(100vw-2rem))] shrink-0 flex-col border-r border-border/65 bg-sidebar/96 text-sidebar-content backdrop-blur-xl",
        !pinned && "shadow-[0_18px_48px_rgba(15,23,42,0.18)] dark:shadow-[0_18px_48px_rgba(0,0,0,0.48)]",
      )}
    >
      {/* Drawer Header */}
      <div className="flex h-11 shrink-0 items-center justify-between gap-2 border-b border-border/55 px-3.5">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-semibold text-foreground">
            {isZh ? "在办会话" : "Open sessions"}
          </span>
          <span className="rounded-full bg-muted px-1.5 py-0.5 text-[11px] font-medium tabular-nums text-muted-foreground">
            {intelligence.open.length}
          </span>
        </div>
        <div className="flex items-center gap-0.5">
          <HoverHint content={t("sidebar.newChat")} side="bottom">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={t("sidebar.newChat")}
              onClick={() => {
                onNewChat();
                if (!pinned) onClose();
              }}
              className="h-7 w-7 rounded-control text-muted-foreground hover:text-foreground"
            >
              <Plus className="h-3.5 w-3.5" aria-hidden />
            </Button>
          </HoverHint>
          <HoverHint content={pinned ? (isZh ? "取消固定抽屉" : "Unpin drawer") : (isZh ? "固定到左侧" : "Pin drawer")} side="bottom">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              data-testid="drawer-pin-button"
              aria-label={pinned ? (isZh ? "取消固定抽屉" : "Unpin drawer") : (isZh ? "固定到左侧" : "Pin drawer")}
              aria-pressed={pinned}
              onClick={onTogglePinDrawer}
              className={cn(
                "hidden h-7 w-7 rounded-control lg:inline-flex",
                pinned ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {pinned ? <PinOff className="h-3.5 w-3.5" aria-hidden /> : <Pin className="h-3.5 w-3.5" aria-hidden />}
            </Button>
          </HoverHint>
          {!pinned ? (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={t("common.close")}
              onClick={onClose}
              className="h-7 w-7 rounded-control text-muted-foreground hover:text-foreground"
            >
              <X className="h-3.5 w-3.5" aria-hidden />
            </Button>
          ) : null}
        </div>
      </div>

      {/* Scrollable Body */}
      <div className="sidebar-scrollbar min-h-0 flex-1 overflow-y-auto overscroll-contain px-2.5 py-3 space-y-4">
        {/* Pinned Top Section: Active Now across all projects */}
        {intelligence.attention.length > 0 ? (
          <section aria-label={isZh ? "此刻活跃" : "Active now"} className="space-y-1.5">
            <div className="flex items-center justify-between px-1.5">
              <span className="text-[11px] font-semibold uppercase tracking-[0.04em] text-muted-foreground">
                {isZh ? "此刻活跃" : "Active now"}
              </span>
              <span className="text-[11px] tabular-nums text-muted-foreground">
                {intelligence.attention.length}
              </span>
            </div>
            <ul className="space-y-1">
              {intelligence.attention.map((item) => {
                const isCurrent = item.session.key === activeKey;
                return (
                  <li key={`active:${item.session.key}`}>
                    <div
                      className={cn(
                        "group relative flex items-start gap-2 rounded-xl px-2.5 py-2 transition-colors",
                        isCurrent
                          ? "bg-sidebar-selected text-sidebar-foreground"
                          : "bg-background/60 hover:bg-accent/70",
                      )}
                    >
                      <div className="mt-1 shrink-0">
                        <SessionStatusDot state={item.attention} />
                      </div>
                      <button
                        type="button"
                        onClick={() => handleSelect(item.session.key)}
                        className="min-w-0 flex-1 text-left"
                      >
                        <p className="truncate text-[13px] font-medium leading-snug text-foreground">
                          {item.title}
                        </p>
                        <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-muted-foreground">
                          <ProjectDot color={item.project.dotColor} className="h-1.5 w-1.5" />
                          <span className="truncate">{item.project.name}</span>
                        </div>
                      </button>
                      <div className="shrink-0 pt-0.5">
                        {item.attention === "running" ? (
                          <LiveElapsedBadge startedAtSec={item.session.runStartedAt} nowMs={nowMs} className="px-1.5 py-0 text-[10.5px]" />
                        ) : item.attention === "updated" && item.session.projectLocked !== false ? (
                          <button
                            type="button"
                            onClick={() => onArchiveSession(item.session.key)}
                            aria-label={isZh ? `结单：${item.title}` : `Done: ${item.title}`}
                            className="inline-flex h-6 items-center gap-1 rounded-md border border-border/70 bg-background px-1.5 text-[11px] font-medium text-muted-foreground opacity-0 transition-opacity hover:text-foreground group-hover:opacity-100 focus-visible:opacity-100"
                          >
                            <Check className="h-3 w-3" aria-hidden />
                          </button>
                        ) : null}
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>
        ) : null}

        {/* Temporary Chats */}
        {temporarySessions.length > 0 ? (
          <section aria-label={t("temporaryChat.sectionTitle")} className="space-y-1">
            <div className="px-1.5 text-[11px] font-semibold uppercase tracking-[0.04em] text-muted-foreground">
              {t("temporaryChat.sectionTitle")}
            </div>
            <ul className="space-y-0.5">
              {temporarySessions.map((session) => {
                const title = deriveTemporaryChatTitle(session.preview, t("temporaryChat.title"));
                const isCurrent = session.key === activeKey;
                return (
                  <li key={session.key}>
                    <div
                      className={cn(
                        "group flex items-center gap-2 rounded-xl px-2.5 py-1.5 text-[13px]",
                        isCurrent ? "bg-sidebar-selected text-foreground" : "hover:bg-accent/65",
                      )}
                    >
                      <button
                        type="button"
                        onClick={() => handleSelect(session.key)}
                        className="flex min-w-0 flex-1 items-center gap-2 text-left"
                      >
                        <MessageCircleDashed className="h-3.5 w-3.5 shrink-0 text-[hsl(var(--temporary-foreground))]" aria-hidden />
                        <span className="truncate">{title}</span>
                      </button>
                      {onCloseTemporaryChat ? (
                        <button
                          type="button"
                          aria-label={t("temporaryChat.closeAction", { title })}
                          onClick={() => onCloseTemporaryChat(session.key)}
                          className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:text-destructive"
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
        ) : null}

        {/* Single-Level Project Groups (Zero nested tree lines, rollup badges always visible!) */}
        <div className="space-y-3">
          {openProjects.map((group) => {
            const collapsed = Boolean(collapsedGroups[group.project.id]);
            return (
              <section key={group.project.id} aria-label={group.project.name} className="space-y-1">
                <div className="group/proj flex items-center gap-1 px-1">
                  <button
                    type="button"
                    aria-expanded={!collapsed}
                    onClick={() => onToggleGroup(group.project.id)}
                    className="flex min-w-0 flex-1 items-center gap-1.5 rounded-lg px-1 py-1 text-left transition-colors hover:bg-accent/60"
                  >
                    <ChevronDown
                      className={cn(
                        "h-3.5 w-3.5 shrink-0 text-muted-foreground/75 transition-transform duration-150",
                        collapsed && "-rotate-90",
                      )}
                      aria-hidden
                    />
                    <ProjectDot color={group.project.dotColor} />
                    <span className="min-w-0 flex-1 truncate text-[12.5px] font-semibold text-foreground/90">
                      {group.project.name}
                    </span>
                    {/* Rollup badges remain visible even when collapsed! */}
                    <span className="flex shrink-0 items-center gap-1">
                      {group.recoveryCount > 0 ? (
                        <span
                          data-testid={`drawer-project-recovery-${group.project.id}`}
                          className="inline-flex items-center gap-0.5 rounded-full bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold tabular-nums text-amber-700 dark:text-amber-300"
                        >
                          <AlertTriangle className="h-2.5 w-2.5" aria-hidden />
                          {group.recoveryCount}
                        </span>
                      ) : null}
                      {group.runningCount > 0 ? (
                        <span
                          data-testid={`drawer-project-running-${group.project.id}`}
                          className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-semibold tabular-nums text-emerald-700 dark:text-emerald-300"
                        >
                          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden />
                          {group.runningCount}
                        </span>
                      ) : null}
                      {group.updatedCount > 0 ? (
                        <span
                          data-testid={`drawer-project-updated-${group.project.id}`}
                          className="inline-flex items-center gap-1 rounded-full bg-orange-500/15 px-1.5 py-0.5 text-[10px] font-semibold tabular-nums text-orange-700 dark:text-orange-300"
                        >
                          <span className="h-1.5 w-1.5 rounded-full bg-[#ff8a3d]" aria-hidden />
                          {group.updatedCount}
                        </span>
                      ) : null}
                      {group.recoveryCount === 0 && group.runningCount === 0 && group.updatedCount === 0 ? (
                        <span className="text-[11px] tabular-nums text-muted-foreground/70">
                          {group.openSessions.length}
                        </span>
                      ) : null}
                    </span>
                  </button>

                  <HoverHint content={isZh ? "在此项目新建" : "New in project"} side="right">
                    <button
                      type="button"
                      aria-label={isZh ? `在 ${group.project.name} 新建` : `New chat in ${group.project.name}`}
                      onClick={() => {
                        if (!group.project.isGeneral && group.project.path) {
                          onNewChatInProject(group.project.path, group.project.name);
                        } else {
                          onNewChat();
                        }
                        if (!pinned) onClose();
                      }}
                      className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground opacity-0 transition-opacity hover:bg-accent hover:text-foreground group-hover/proj:opacity-100 focus-visible:opacity-100"
                    >
                      <Plus className="h-3.5 w-3.5" aria-hidden />
                    </button>
                  </HoverHint>
                </div>

                {!collapsed ? (
                  <ul className="space-y-0.5">
                    {group.openSessions.map((item) => (
                      <DrawerSessionRow
                        key={item.session.key}
                        item={item}
                        isCurrent={item.session.key === activeKey}
                        isZh={isZh}
                        locale={i18n.resolvedLanguage}
                        nowMs={nowMs}
                        isRenaming={renamingKey === item.session.key}
                        renameDraft={renameDraft}
                        onRenameDraftChange={setRenameDraft}
                        onBeginRename={() => {
                          setRenamingKey(item.session.key);
                          setRenameDraft(item.title);
                        }}
                        onCommitRename={async () => {
                          const trimmed = renameDraft.trim();
                          setRenamingKey(null);
                          if (trimmed) await onRequestRename(item.session.key, trimmed).catch(() => {});
                        }}
                        onCancelRename={() => setRenamingKey(null)}
                        onSelect={() => handleSelect(item.session.key)}
                        onArchive={() => onArchiveSession(item.session.key)}
                        onTogglePin={() => onTogglePinSession(item.session.key)}
                        onCreateTab={onCreateTab ? () => onCreateTab(item.session.key) : undefined}
                        onDelete={() => onRequestDeleteMany([{ key: item.session.key, label: item.title }])}
                      />
                    ))}
                  </ul>
                ) : null}
              </section>
            );
          })}
        </div>
      </div>

      {/* Footer: Archived / Done Escape Hatch */}
      <div className="shrink-0 border-t border-border/55 px-3 py-2">
        <button
          type="button"
          onClick={() => {
            onOpenOverviewDone();
            if (!pinned) onClose();
          }}
          className="flex w-full items-center justify-between rounded-control px-2 py-1.5 text-[12px] font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          <span>
            {isZh
              ? `已结单 (${intelligence.archived.length})`
              : `Done (${intelligence.archived.length})`}
          </span>
          <span className="inline-flex items-center gap-1 text-[11.5px]">
            <span>{isZh ? "总览管理" : "Manage"}</span>
            <ArrowRight className="h-3 w-3" aria-hidden />
          </span>
        </button>
      </div>
    </aside>
  );

  if (pinned) {
    return drawerPanel;
  }

  return (
    <div className="fixed inset-0 top-12 z-40 flex">
      {drawerPanel}
      <button
        type="button"
        aria-label={t("common.close")}
        onClick={onClose}
        className="flex-1 bg-black/15 backdrop-blur-[1px] transition-opacity dark:bg-black/35"
      />
    </div>
  );
}

function DrawerSessionRow({
  item,
  isCurrent,
  isZh,
  locale,
  nowMs,
  isRenaming,
  renameDraft,
  onRenameDraftChange,
  onBeginRename,
  onCommitRename,
  onCancelRename,
  onSelect,
  onArchive,
  onTogglePin,
  onCreateTab,
  onDelete,
}: {
  item: EnrichedSession;
  isCurrent: boolean;
  isZh: boolean;
  locale?: string;
  nowMs: number;
  isRenaming: boolean;
  renameDraft: string;
  onRenameDraftChange: (value: string) => void;
  onBeginRename: () => void;
  onCommitRename: () => Promise<void>;
  onCancelRename: () => void;
  onSelect: () => void;
  onArchive: () => void;
  onTogglePin: () => void;
  onCreateTab?: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  const canArchive = item.session.projectLocked !== false;

  return (
    <li>
      <div
        data-chat-row={item.session.key}
        className={cn(
          "group relative flex items-start gap-2 rounded-xl px-2.5 py-2 transition-colors",
          isCurrent
            ? "bg-sidebar-selected text-sidebar-foreground"
            : "text-sidebar-content hover:bg-accent/65 hover:text-foreground",
        )}
      >
        <div className="mt-1 shrink-0">
          <SessionStatusDot state={item.attention} />
        </div>

        <div className="min-w-0 flex-1">
          {isRenaming ? (
            <input
              value={renameDraft}
              autoFocus
              onChange={(event) => onRenameDraftChange(event.target.value)}
              onBlur={() => { void onCommitRename(); }}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  void onCommitRename();
                } else if (event.key === "Escape") {
                  event.preventDefault();
                  onCancelRename();
                }
              }}
              className="h-6 w-full rounded border border-border bg-background px-1.5 text-[12.5px] text-foreground outline-none"
            />
          ) : (
            <button
              type="button"
              onClick={onSelect}
              aria-current={isCurrent ? "page" : undefined}
              className="block w-full min-w-0 text-left focus-visible:outline-none"
            >
              <div className="flex min-w-0 items-center gap-1.5 pr-1">
                <span className={cn("min-w-0 flex-1 truncate text-[13px] leading-snug", isCurrent ? "font-medium text-foreground" : "font-normal")}>
                  {item.title}
                </span>
                {item.pinned ? <SubtlePinMark /> : null}
              </div>
              <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-muted-foreground/85">
                {item.attention === "running" ? (
                  <LiveElapsedBadge startedAtSec={item.session.runStartedAt} nowMs={nowMs} className="px-1.5 py-0 text-[10px]" />
                ) : (
                  <span className="shrink-0 tabular-nums">
                    {formatCompactRelativeTime(item.updatedMs, locale, nowMs)}
                  </span>
                )}
                <MutedHandleBadge handle={item.session.handle} className="max-w-20 px-1 py-0 text-[10px]" />
                <AutomationProtectedBadge count={item.automationCount} compact />
                <SplitGroupBadge title={item.workbenchTabTitle} compact />
              </div>
            </button>
          )}
        </div>

        {/* Hover-overlay quick actions — zero wasted width when idle! */}
        {!isRenaming ? (
          <div className="pointer-events-none absolute right-1.5 top-1.5 flex items-center gap-0.5 rounded-lg bg-sidebar/95 pl-2 opacity-0 shadow-sm ring-1 ring-border/50 transition-opacity group-hover:pointer-events-auto group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:opacity-100">
            {canArchive ? (
              <HoverHint content={isZh ? "结单归档" : "Mark done"} side="top">
                <button
                  type="button"
                  aria-label={isZh ? `结单：${item.title}` : `Done: ${item.title}`}
                  onClick={onArchive}
                  className="inline-flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
                >
                  <Check className="h-3.5 w-3.5" aria-hidden />
                </button>
              </HoverHint>
            ) : null}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  aria-label={t("chat.actions", { title: item.title })}
                  className="inline-flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
                >
                  <MoreHorizontal className="h-3.5 w-3.5" aria-hidden />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-40">
                <DropdownMenuItem onSelect={onTogglePin}>
                  {item.pinned ? <PinOff className="h-3.5 w-3.5" aria-hidden /> : <Pin className="h-3.5 w-3.5" aria-hidden />}
                  {item.pinned ? t("chat.unpin") : t("chat.pin")}
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={onBeginRename}>
                  <Pencil className="h-3.5 w-3.5" aria-hidden />
                  {t("chat.rename")}
                </DropdownMenuItem>
                {onCreateTab && !item.workbenchTabKey ? (
                  <DropdownMenuItem onSelect={onCreateTab}>
                    <PanelsTopLeft className="h-3.5 w-3.5" aria-hidden />
                    {t("workbench.createGroup")}
                  </DropdownMenuItem>
                ) : null}
                <DropdownMenuSeparator />
                <DropdownMenuItem tone="destructive" onSelect={onDelete}>
                  <Trash2 className="h-3.5 w-3.5" aria-hidden />
                  {t("chat.delete")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        ) : null}
      </div>
    </li>
  );
}
