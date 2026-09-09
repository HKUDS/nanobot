import {
  type ReactNode,
  type RefObject,
  useRef,
  useState,
} from "react";
import {
  Archive,
  Brain,
  CalendarClock,
  Menu,
  Search,
  Settings,
  SquarePen,
  Blocks,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  ChatList,
  type SidebarDeleteItem,
  type SidebarPaneGroup,
} from "@/components/ChatList";
import { ConnectionBadge } from "@/components/ConnectionBadge";
import {
  SIDEBAR_SELECTION_ACTION_ITEM_CLASS,
  SidebarSelectionHighlight,
} from "@/components/SidebarSelectionHighlight";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import type {
  ChatSummary,
  SidebarViewState,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { sidebarShortcutAria, sidebarShortcutLabel } from "@/lib/sidebar-shortcuts";

interface SidebarProps {
  sessions: ChatSummary[];
  temporarySessions?: ChatSummary[];
  activeKey: string | null;
  loading: boolean;
  newChatActive: boolean;
  onNewChat: () => void;
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
  onToggleGroup: (groupId: string) => void;
  onRequestRenameProject: (projectKey: string, label: string) => void;
  onNewChatInProject: (projectPath: string, projectName: string) => void;
  onOpenSettings: () => void;
  onOpenApps: () => void;
  onOpenSkills: () => void;
  onOpenAutomations: () => void;
  onSettingsIntent?: () => void;
  onOpenSearch: () => void;
  activeUtility?: "apps" | "skills" | "automations" | null;
  onToggleArchived: () => void;
  onCollapse: () => void;
  onExpand?: () => void;
  containActionMenus?: boolean;
  collapsed?: boolean;
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
  viewState?: SidebarViewState;
  showArchived?: boolean;
  archivedCount?: number;
  defaultWorkspacePath?: string | null;
  hostChromeInset?: boolean;
}

type NavigatorWithUserAgentData = Navigator & {
  userAgentData?: { platform?: string };
};

function isApplePlatform(): boolean {
  if (typeof navigator === "undefined") return false;
  const platform = navigator.platform || "";
  const userAgentPlatform =
    (navigator as NavigatorWithUserAgentData).userAgentData?.platform || "";
  return /mac|iphone|ipad|ipod/i.test(`${platform} ${userAgentPlatform}`);
}

export function Sidebar(props: SidebarProps) {
  const { t } = useTranslation();
  const [menuPortalContainer, setMenuPortalContainer] =
    useState<HTMLElement | null>(null);
  const collapsed = Boolean(props.collapsed);
  const toggleLabel = t("thread.header.toggleSidebar");
  const apple = isApplePlatform();
  const activeActionRef = useRef<HTMLButtonElement>(null);
  const activeActionId = props.newChatActive
    ? "new-chat"
    : props.activeUtility
      ? `utility:${props.activeUtility}`
      : null;

  return (
    <TooltipProvider delayDuration={300}>
    <nav
      ref={props.containActionMenus ? setMenuPortalContainer : undefined}
      aria-label={t("sidebar.navigation")}
      className={cn(
        "flex h-full w-full min-w-0 flex-col text-sidebar-foreground",
        props.hostChromeInset ? "bg-transparent" : "bg-sidebar",
      )}
    >
      <div
        data-testid="sidebar-brand-row"
        className={cn(
          "flex items-start px-3 pb-2.5 pt-3",
          collapsed ? "w-14 justify-start" : "justify-between",
        )}
      >
        <button
          data-testid="sidebar-brand-mark"
          type="button"
          aria-label={collapsed ? toggleLabel : undefined}
          aria-hidden={collapsed ? undefined : true}
          title={collapsed ? toggleLabel : undefined}
          onClick={collapsed ? props.onExpand : undefined}
          tabIndex={collapsed ? 0 : -1}
          className={cn(
            "host-no-drag flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-xl transition-colors",
            props.hostChromeInset && "mt-5",
            collapsed
              ? "-ml-0.5 hover:bg-sidebar-accent/75"
              : "pointer-events-none -ml-0.5",
          )}
        >
          <img
            src="/brand/nanobot_mark.svg"
            alt=""
            className="h-6 w-6 select-none object-contain"
            draggable={false}
          />
        </button>
        {!collapsed && (
          <Button
            variant="ghost"
            size="icon"
            aria-label={t("sidebar.collapse")}
            onClick={props.onCollapse}
            className="host-no-drag mt-1 h-7 w-7 rounded-lg text-muted-foreground/85 hover:bg-sidebar-accent/75 hover:text-sidebar-foreground"
          >
            <Menu className="h-3.5 w-3.5" />
          </Button>
        )}
      </div>

      <SidebarSelectionHighlight
        targetRef={activeActionRef}
        activeId={activeActionId}
        scope="actions"
        className={cn(
          "relative gap-1 pb-2",
          collapsed ? "flex w-14 flex-col items-center px-0" : "grid auto-cols-fr grid-flow-col px-2",
        )}
      >
        <SidebarActionButton
          collapsed={collapsed}
          label={t("sidebar.newChat")}
          iconOnly
          onClick={props.onNewChat}
          active={props.newChatActive}
          selectionRef={activeActionRef}
          icon={<SquarePen className="h-4 w-4" />}
          shortcut={sidebarShortcutLabel("newChat", apple)}
          ariaKeyShortcuts={sidebarShortcutAria("newChat")}
        />
        <SidebarActionButton
          collapsed={collapsed}
          label={t("sidebar.searchAria")}
          shortcut={sidebarShortcutLabel("search", apple)}
          ariaKeyShortcuts={sidebarShortcutAria("search")}
          iconOnly
          onClick={props.onOpenSearch}
          icon={<Search className="h-4 w-4" />}
        />
        <SidebarActionButton
          collapsed={collapsed}
          label={t("sidebar.apps")}
          shortcut={sidebarShortcutLabel("apps", apple)}
          ariaKeyShortcuts={sidebarShortcutAria("apps")}
          iconOnly
          onClick={props.onOpenApps}
          onIntent={props.onSettingsIntent}
          active={props.activeUtility === "apps"}
          selectionRef={activeActionRef}
          icon={<Blocks className="h-4 w-4" />}
        />
        <SidebarActionButton
          collapsed={collapsed}
          label={t("sidebar.skills.title")}
          shortcut={sidebarShortcutLabel("skills", apple)}
          ariaKeyShortcuts={sidebarShortcutAria("skills")}
          iconOnly
          onClick={props.onOpenSkills}
          onIntent={props.onSettingsIntent}
          active={props.activeUtility === "skills"}
          selectionRef={activeActionRef}
          icon={<Brain className="h-4 w-4" />}
        />
        <SidebarActionButton
          collapsed={collapsed}
          label={t("sidebar.automations", { defaultValue: "Automations" })}
          shortcut={sidebarShortcutLabel("automations", apple)}
          ariaKeyShortcuts={sidebarShortcutAria("automations")}
          iconOnly
          onClick={props.onOpenAutomations}
          onIntent={props.onSettingsIntent}
          active={props.activeUtility === "automations"}
          selectionRef={activeActionRef}
          icon={<CalendarClock className="h-4 w-4" />}
        />
        {props.archivedCount ? (
          <SidebarActionButton
            collapsed={collapsed}
            label={props.showArchived ? t("chat.hideArchived") : t("chat.showArchived")}
            iconOnly
            onClick={props.onToggleArchived}
            icon={<Archive className="h-4 w-4" />}
          />
        ) : null}
      </SidebarSelectionHighlight>
      <div
        className={cn(
          "flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden transition-opacity duration-200",
          collapsed && "pointer-events-none opacity-0",
        )}
      >
        {!collapsed && (
          <ChatList
            sessions={props.sessions}
            temporarySessions={props.temporarySessions}
            activeKey={props.activeKey}
            loading={props.loading}
            emptyLabel={t("chat.noSessions")}
            onSelect={props.onSelect}
            onCloseTemporaryChat={props.onCloseTemporaryChat}
            onRequestDelete={props.onRequestDelete}
            onRequestDeleteMany={props.onRequestDeleteMany}
            onTogglePin={props.onTogglePin}
            onRequestRename={props.onRequestRename}
            onRequestRenameTab={props.onRequestRenameTab}
            onToggleArchive={props.onToggleArchive}
            paneGroups={props.paneGroups}
            onSelectPane={props.onSelectPane}
            onCreateTab={props.onCreateTab}
            onDetachPane={props.onDetachPane}
            onDissolveTab={props.onDissolveTab}
            onAttachPane={props.onAttachPane}
            onToggleGroup={props.onToggleGroup}
            onRequestRenameProject={props.onRequestRenameProject}
            onNewChatInProject={props.onNewChatInProject}
            pinnedKeys={props.pinnedKeys}
            archivedKeys={props.archivedKeys}
            pinnedPaneKeys={props.pinnedPaneKeys}
            archivedPaneKeys={props.archivedPaneKeys}
            sessionOrder={props.sessionOrder}
            titleOverrides={props.titleOverrides}
            projectNameOverrides={props.projectNameOverrides}
            collapsedGroups={props.collapsedGroups}
            runningChatIds={props.runningChatIds}
            updatedChatIds={props.updatedChatIds}
            recoveryChatIds={props.recoveryChatIds}
            density={props.viewState?.density}
            showPreviews={props.viewState?.show_previews}
            showTimestamps={props.viewState?.show_timestamps}
            sort={props.viewState?.sort}
            showArchived={props.showArchived}
            defaultWorkspacePath={props.defaultWorkspacePath}
            actionMenuPortalContainer={
              props.containActionMenus ? menuPortalContainer : undefined
            }
          />
        )}
      </div>
      <div
        className={cn(
          "flex items-center justify-between gap-1 bg-sidebar/55 px-2.5 py-3 text-xs",
          collapsed && "w-14 flex-col px-0",
        )}
      >
        <SidebarActionButton
          collapsed={collapsed}
          label={t("sidebar.settings")}
          iconOnly
          shortcut={sidebarShortcutLabel("settings", apple)}
          ariaKeyShortcuts={sidebarShortcutAria("settings")}
          onClick={props.onOpenSettings}
          onIntent={props.onSettingsIntent}
          className="w-9"
          icon={<Settings className="h-4 w-4" />}
        />
        <ConnectionBadge />
      </div>
    </nav>
    </TooltipProvider>
  );
}

function SidebarActionButton({
  collapsed,
  iconOnly = false,
  label,
  icon,
  onClick,
  active = false,
  className,
  shortcut,
  ariaKeyShortcuts,
  onIntent,
  selectionRef,
}: {
  collapsed: boolean;
  iconOnly?: boolean;
  label: string;
  icon: ReactNode;
  onClick: () => void;
  active?: boolean;
  className?: string;
  shortcut?: string;
  ariaKeyShortcuts?: string;
  onIntent?: () => void;
  selectionRef?: RefObject<HTMLButtonElement>;
}) {
  const compact = collapsed || iconOnly;

  const button = (
    <Button
      ref={active ? selectionRef : undefined}
      type="button"
      variant={null}
      aria-label={label}
      aria-current={active ? "page" : undefined}
      aria-keyshortcuts={ariaKeyShortcuts}
      onClick={() => onClick()}
      onFocus={onIntent}
      onPointerEnter={onIntent}
      className={cn(
        "touch-target group h-8 min-w-0 gap-2 overflow-hidden rounded-xl font-medium",
        SIDEBAR_SELECTION_ACTION_ITEM_CLASS,
        collapsed
          ? "w-9 justify-center gap-0 px-0"
          : iconOnly ? "w-full justify-center gap-0 px-0"
          : "w-full justify-start gap-2 px-3 text-[14px] leading-5",
        active
          ? "text-sidebar-accent-foreground"
          : "text-muted-foreground settings-hover hover:text-foreground",
        className,
      )}
    >
      <span className="flex shrink-0 items-center justify-center" aria-hidden>
        {icon}
      </span>
      {!compact && <span className="sidebar-action-label min-w-0 max-w-[12rem] truncate whitespace-nowrap">
        {label}
      </span>}
    </Button>
  );
  return compact ? (
    <Tooltip>
      <TooltipTrigger asChild>{button}</TooltipTrigger>
      <TooltipContent side={collapsed ? "right" : "bottom"} className="flex items-center gap-4">
        <span>{label}</span>
        {shortcut ? <kbd className="whitespace-nowrap font-sans text-muted-foreground">{shortcut}</kbd> : null}
      </TooltipContent>
    </Tooltip>
  ) : button;
}
