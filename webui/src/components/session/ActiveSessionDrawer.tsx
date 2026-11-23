import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight,
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
  type EnrichedSession,
  type SessionIntelligenceSnapshot,
} from "@/lib/session-intelligence";
import { deriveTemporaryChatTitle } from "@/lib/temporary-chat";
import type { ChatSummary } from "@/lib/types";
import { cn } from "@/lib/utils";
import "./session-zen.css";

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
  const [completingKeys, setCompletingKeys] = useState<Set<string>>(() => new Set());
  const timersRef = useRef<number[]>([]);

  useEffect(() => () => {
    for (const id of timersRef.current) window.clearTimeout(id);
  }, []);

  useEffect(() => {
    if (!open || pinned) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose, open, pinned]);

  const completeWithRitual = useCallback((key: string) => {
    if (completingKeys.has(key)) return;
    setCompletingKeys((current) => new Set(current).add(key));
    const timer = window.setTimeout(() => {
      onArchiveSession(key);
      setCompletingKeys((current) => {
        const next = new Set(current);
        next.delete(key);
        return next;
      });
    }, 180);
    timersRef.current.push(timer);
  }, [completingKeys, onArchiveSession]);

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
      aria-hidden={!visible || undefined}
      className={cn(
        "zen-drawer-panel flex h-full w-[min(19rem,calc(100vw-2rem))] shrink-0 flex-col border-r border-border/45 bg-sidebar/94 text-sidebar-content backdrop-blur-xl",
        !pinned && "shadow-[0_24px_60px_rgba(15,23,42,0.14)] dark:shadow-[0_24px_60px_rgba(0,0,0,0.5)]",
        !pinned && (open ? "translate-x-0 opacity-100" : "-translate-x-full opacity-0"),
      )}
    >
      {/* Calm Drawer Header */}
      <div className="flex h-11 shrink-0 items-center justify-between gap-2 px-4">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-medium text-foreground">
            {isZh ? "在办" : "Open"}
          </span>
          <span className="text-[11.5px] tabular-nums text-muted-foreground/60">
            {intelligence.open.length}
          </span>
        </div>
        <div className="flex items-center gap-0.5">
          <HoverHint content={t("sidebar.newChat")} side="bottom">
            <button
              type="button"
              aria-label={t("sidebar.newChat")}
              onClick={() => {
                onNewChat();
                if (!pinned) onClose();
              }}
              className="inline-flex h-7 w-7 items-center justify-center rounded-lg text-muted-foreground/70 transition-colors hover:bg-foreground/[0.05] hover:text-foreground"
            >
              <Plus className="h-3.5 w-3.5" aria-hidden />
            </button>
          </HoverHint>
          <HoverHint content={pinned ? (isZh ? "取消固定" : "Unpin") : (isZh ? "固定抽屉" : "Pin drawer")} side="bottom">
            <button
              type="button"
              data-testid="drawer-pin-button"
              aria-label={pinned ? (isZh ? "取消固定" : "Unpin") : (isZh ? "固定抽屉" : "Pin drawer")}
              aria-pressed={pinned}
              onClick={onTogglePinDrawer}
              className={cn(
                "hidden h-7 w-7 items-center justify-center rounded-lg transition-colors lg:inline-flex",
                pinned
                  ? "bg-foreground/[0.07] text-foreground"
                  : "text-muted-foreground/70 hover:bg-foreground/[0.05] hover:text-foreground",
              )}
            >
              {pinned ? <PinOff className="h-3.5 w-3.5" aria-hidden /> : <Pin className="h-3.5 w-3.5" aria-hidden />}
            </button>
          </HoverHint>
          {!pinned ? (
            <button
              type="button"
              aria-label={t("common.close")}
              onClick={onClose}
              className="inline-flex h-7 w-7 items-center justify-center rounded-lg text-muted-foreground/70 transition-colors hover:bg-foreground/[0.05] hover:text-foreground"
            >
              <X className="h-3.5 w-3.5" aria-hidden />
            </button>
          ) : null}
        </div>
      </div>

      {/* Scrollable Body */}
      <div className="sidebar-scrollbar min-h-0 flex-1 space-y-5 overflow-y-auto overscroll-contain px-3 pb-4 pt-1">
        {/* Pinned Top Section: Active Now across all projects */}
        {intelligence.attention.length > 0 ? (
          <section aria-label={isZh ? "此刻进行" : "Active now"} className="space-y-1">
            <div className="px-2 pb-0.5 text-[11px] font-medium tracking-[0.04em] text-muted-foreground/65">
              {isZh ? "此刻进行" : "Active now"}
            </div>
            <ul className="space-y-0.5">
              {intelligence.attention.map((item) => {
                const isCurrent = item.session.key === activeKey;
                const completing = completingKeys.has(item.session.key);
                return (
                  <li key={`active:${item.session.key}`}>
                    <div
                      className={cn(
                        "group relative flex items-start gap-2.5 rounded-xl px-2 py-2 transition-all duration-150",
                        isCurrent
                          ? "bg-foreground/[0.065] text-foreground"
                          : "hover:bg-foreground/[0.04]",
                        completing && "zen-completing",
                      )}
                    >
                      <div className="mt-[3px] shrink-0">
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
                        <p className="mt-0.5 truncate text-[11px] text-muted-foreground/65">
                          {item.project.name}
                        </p>
                      </button>
                      <div className="shrink-0 pt-0.5">
                        {item.attention === "running" ? (
                          <LiveElapsedBadge startedAtSec={item.session.runStartedAt} nowMs={nowMs} />
                        ) : item.attention === "updated" && item.session.projectLocked !== false ? (
                          <div className="opacity-0 transition-opacity duration-150 group-hover:opacity-100 focus-within:opacity-100">
                            <ZenDoneCircle
                              completed={completing}
                              label={isZh ? `结单：${item.title}` : `Done: ${item.title}`}
                              onClick={() => completeWithRitual(item.session.key)}
                            />
                          </div>
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
            <div className="px-2 text-[11px] font-medium tracking-[0.04em] text-muted-foreground/65">
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
                        "group flex items-center gap-2 rounded-xl px-2 py-1.5 text-[13px]",
                        isCurrent ? "bg-foreground/[0.065] text-foreground" : "hover:bg-foreground/[0.04]",
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
                          className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground/60 hover:text-destructive"
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

        {/* Single-Level Project Groups with Smooth Accordion & Quiet Rollups */}
        <div className="space-y-3.5">
          {openProjects.map((group) => {
            const collapsed = Boolean(collapsedGroups[group.project.id]);
            return (
              <section key={group.project.id} aria-label={group.project.name} className="space-y-0.5">
                <div className="group/proj flex items-center gap-1 px-1">
                  <button
                    type="button"
                    aria-expanded={!collapsed}
                    onClick={() => onToggleGroup(group.project.id)}
                    className="flex min-w-0 flex-1 items-center gap-1.5 rounded-lg px-1 py-1 text-left transition-colors hover:bg-foreground/[0.04]"
                  >
                    <ChevronDown
                      className={cn(
                        "h-3 w-3 shrink-0 text-muted-foreground/55 transition-transform duration-200",
                        collapsed && "-rotate-90",
                      )}
                      aria-hidden
                    />
                    <span className="min-w-0 flex-1 truncate text-[12px] font-medium text-foreground/80">
                      {group.project.name}
                    </span>

                    {/* Ultra-quiet live rollup — stays clear even when collapsed */}
                    <span className="flex shrink-0 items-center gap-2 text-[11px] tabular-nums">
                      {group.recoveryCount > 0 ? (
                        <span
                          data-testid={`drawer-project-recovery-${group.project.id}`}
                          className="inline-flex items-center gap-1 text-amber-600/90 dark:text-amber-400/90"
                        >
                          <span className="h-1.5 w-1.5 rounded-full bg-amber-500" aria-hidden />
                          {group.recoveryCount}
                        </span>
                      ) : null}
                      {group.runningCount > 0 ? (
                        <span
                          data-testid={`drawer-project-running-${group.project.id}`}
                          className="inline-flex items-center gap-1 text-emerald-700/90 dark:text-emerald-300/90"
                        >
                          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden />
                          {group.runningCount}
                        </span>
                      ) : null}
                      {group.updatedCount > 0 ? (
                        <span
                          data-testid={`drawer-project-updated-${group.project.id}`}
                          className="inline-flex items-center gap-1 text-[#d97742] dark:text-[#ea8c55]"
                        >
                          <span className="h-1.5 w-1.5 rounded-full bg-[#d97742]" aria-hidden />
                          {group.updatedCount}
                        </span>
                      ) : null}
                      {group.recoveryCount === 0 && group.runningCount === 0 && group.updatedCount === 0 ? (
                        <span className="text-muted-foreground/50">
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
                      className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground/60 opacity-0 transition-opacity hover:bg-foreground/[0.05] hover:text-foreground group-hover/proj:opacity-100 focus-visible:opacity-100"
                    >
                      <Plus className="h-3 w-3" aria-hidden />
                    </button>
                  </HoverHint>
                </div>

                <div className="zen-disclosure" data-collapsed={collapsed}>
                  <div className="zen-disclosure-inner">
                    <ul className="space-y-0.5 pt-0.5">
                      {group.openSessions.map((item) => (
                        <DrawerSessionRow
                          key={item.session.key}
                          item={item}
                          isCurrent={item.session.key === activeKey}
                          completing={completingKeys.has(item.session.key)}
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
                          onArchive={() => completeWithRitual(item.session.key)}
                          onTogglePin={() => onTogglePinSession(item.session.key)}
                          onCreateTab={onCreateTab ? () => onCreateTab(item.session.key) : undefined}
                          onDelete={() => onRequestDeleteMany([{ key: item.session.key, label: item.title }])}
                        />
                      ))}
                    </ul>
                  </div>
                </div>
              </section>
            );
          })}
        </div>
      </div>

      {/* Quiet Footer */}
      <div className="shrink-0 border-t border-border/35 px-3 py-2.5">
        <button
          type="button"
          onClick={() => {
            onOpenOverviewDone();
            if (!pinned) onClose();
          }}
          className="flex w-full items-center justify-between rounded-lg px-2 py-1 text-[12px] text-muted-foreground/75 transition-colors hover:bg-foreground/[0.04] hover:text-foreground"
        >
          <span>
            {isZh
              ? `已结单 (${intelligence.archived.length})`
              : `Done (${intelligence.archived.length})`}
          </span>
          <ArrowRight className="h-3 w-3 opacity-65" aria-hidden />
        </button>
      </div>
    </aside>
  );

  if (pinned) {
    return drawerPanel;
  }

  return (
    <div
      className={cn(
        "fixed inset-0 top-12 z-40 flex",
        open ? "pointer-events-auto" : "pointer-events-none",
      )}
    >
      {drawerPanel}
      <button
        type="button"
        tabIndex={open ? 0 : -1}
        aria-label={t("common.close")}
        onClick={onClose}
        className={cn(
          "zen-drawer-backdrop flex-1 bg-black/12 backdrop-blur-[1.5px] dark:bg-black/32",
          open ? "opacity-100" : "opacity-0",
        )}
      />
    </div>
  );
}

function DrawerSessionRow({
  item,
  isCurrent,
  completing,
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
  completing: boolean;
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
          "group relative flex items-start gap-2.5 rounded-xl px-2 py-2 transition-all duration-150",
          isCurrent
            ? "bg-foreground/[0.065] text-foreground"
            : "text-sidebar-content hover:bg-foreground/[0.04] hover:text-foreground",
          completing && "zen-completing",
        )}
      >
        <div className="mt-[3px] shrink-0">
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
              className="h-6 w-full border-b border-foreground/40 bg-transparent px-0.5 text-[12.5px] text-foreground outline-none"
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
              <div className="mt-0.5 flex items-center gap-2 text-[11px] text-muted-foreground/60">
                {item.attention === "running" ? (
                  <LiveElapsedBadge startedAtSec={item.session.runStartedAt} nowMs={nowMs} />
                ) : (
                  <span className="shrink-0 tabular-nums">
                    {formatCompactRelativeTime(item.updatedMs, locale, nowMs)}
                  </span>
                )}
                <MutedHandleBadge handle={item.session.handle} className="max-w-20 text-[10.5px]" />
                <AutomationProtectedBadge count={item.automationCount} compact />
                <SplitGroupBadge title={item.workbenchTabTitle} />
              </div>
            </button>
          )}
        </div>

        {/* Gentle hover-slide completion & menu */}
        {!isRenaming ? (
          <div className="pointer-events-none absolute right-1.5 top-2 flex translate-x-1 items-center gap-1 rounded-lg bg-sidebar/95 pl-2 opacity-0 transition-all duration-150 group-hover:pointer-events-auto group-hover:translate-x-0 group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:translate-x-0 group-focus-within:opacity-100">
            {canArchive ? (
              <ZenDoneCircle
                completed={completing}
                label={isZh ? `结单：${item.title}` : `Done: ${item.title}`}
                onClick={onArchive}
              />
            ) : null}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  aria-label={t("chat.actions", { title: item.title })}
                  className="inline-flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground/70 hover:bg-foreground/[0.06] hover:text-foreground"
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
