import {
  ArchiveIcon,
  AutomationsIcon,
  SearchIcon,
  SettingsIcon,
  ComposeIcon,
  AppsIcon,
} from "@/components/icons/product-icons";
import { type ReactNode, useLayoutEffect, useMemo, useRef, useState } from "react";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  ChatList,
  type SidebarDeleteItem,
  type SidebarPaneGroup,
} from "@/components/ChatList";
import { HostSwitcher } from "@/components/remote/HostSwitcher";
import { UpdateNotice } from "@/components/UpdateNotice";
import {
  SIDEBAR_SELECTION_ACTION_ITEM_CLASS,
  SidebarSelectionHighlight,
} from "@/components/SidebarSelectionHighlight";
import { Button } from "@/components/ui/button";
import { HoverHint } from "@/components/ui/tooltip";
import type {
  ChatSummary,
  SidebarViewState,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import type { UpdateMethod } from "@/lib/api";
import { sidebarShortcutAria, sidebarShortcutLabel } from "@/lib/sidebar-shortcuts";
import "./sidebar-dock.css";

interface SidebarProps {
  sessions: ChatSummary[];
  temporarySessions?: ChatSummary[];
  activeKey: string | null;
  loading: boolean;
  initialLoading?: boolean;
  onNewChat: () => void;
  onSelect: (key: string) => void;
  onCloseTemporaryChat?: (key: string) => void;
  onRequestDelete: (key: string, label: string) => void;
  onRequestDeleteMany?: (items: SidebarDeleteItem[]) => void;
  onTogglePin: (key: string) => void;
  onRequestRename: (key: string, title: string) => Promise<void>;
  onRequestRenameTab?: (key: string, label: string) => void;
  onToggleArchive: (key: string) => void;
  onArchiveMany?: (keys: string[], archive: boolean) => void;
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
  onOpenUpdates?: () => void;
  availableUpdate?: { version: string; onDismiss: () => void; onRequestUpdate?: () => void; installationMethod?: UpdateMethod | null };
  onOpenApps: () => void;
  onOpenAutomations: () => void;
  onSettingsIntent?: () => void;
  onOpenSearch: () => void;
  activeUtility?: "apps" | "automations" | null;
  onToggleArchived: () => void;
  onCollapse?: () => void;
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
  desktopDock?: boolean;
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
  const canExpand = collapsed && Boolean(props.onExpand);
  const expandButton = useRef<HTMLButtonElement>(null);
  const collapseButton = useRef<HTMLButtonElement>(null);
  const restoreToggleFocus = useRef(false);
  useLayoutEffect(() => {
    if (!restoreToggleFocus.current) return;
    restoreToggleFocus.current = false;
    (collapsed ? expandButton : collapseButton).current?.focus();
  }, [collapsed]);

  const toggleLabel = t("thread.header.toggleSidebar");
  const collapseLabel = t("sidebar.collapse");
  const apple = isApplePlatform();
  const activeUtilityId = props.activeUtility ? `utility:${props.activeUtility}` : null;
  const { archivedCount, desktopDock, onOpenSearch, onToggleArchived, showArchived } = props;
  const footerActionProps = { collapsed, dockLabel: desktopDock, onIntent: props.onSettingsIntent, tooltipSide: "top" } as const;
  const actionInset = desktopDock || collapsed ? "px-3" : "px-2";

  const sessionActions = useMemo(() => (
    <div className={cn("flex shrink-0 flex-col gap-0.5 pb-1 pt-0.5", actionInset)}>
      <SidebarActionButton
        collapsed={collapsed}
        label={t("sidebar.searchAria")}
        shortcut={sidebarShortcutLabel("search", apple)}
        ariaKeyShortcuts={sidebarShortcutAria("search")}
        dockLabel={desktopDock}
        onClick={onOpenSearch}
        icon={<SearchIcon className="h-4 w-4" />}
      />
      {archivedCount ? (
        <SidebarActionButton
          collapsed={collapsed}
          dockLabel={desktopDock}
          label={showArchived ? t("chat.hideArchived") : t("chat.showArchived")}
          onClick={onToggleArchived}
          icon={<ArchiveIcon className="h-4 w-4" />}
        />
      ) : null}
    </div>
  ), [actionInset, apple, archivedCount, collapsed, desktopDock, onOpenSearch, onToggleArchived, showArchived, t]);

  return (
    <nav
      data-theme-surface
      data-theme-ink
      ref={props.containActionMenus ? setMenuPortalContainer : undefined}
      aria-label={t("sidebar.navigation")}
      data-sidebar-collapsed={desktopDock ? collapsed : undefined}
      className={cn(
        "flex h-full w-full min-w-0 flex-col text-sidebar-content",
        desktopDock || collapsed || props.hostChromeInset ? "bg-transparent" : "bg-sidebar",
      )}
    >
      <div
        data-testid="sidebar-brand-row"
        className={cn(
          "flex items-start justify-between gap-1 pb-4 ps-3 pt-3",
          collapsed ? "w-14 pe-3" : "pe-2",
        )}
      >
        <HoverHint enabled={canExpand} content={toggleLabel} side="right">
          <Button
            ref={expandButton}
            data-testid="sidebar-brand-mark"
            type="button"
            size="icon"
            variant={canExpand ? "icon" : null}
            aria-label={canExpand ? toggleLabel : undefined}
            aria-expanded={canExpand ? false : undefined}
            aria-hidden={canExpand ? undefined : true}
            onClick={canExpand ? (event) => {
              restoreToggleFocus.current = event.detail === 0 && Boolean(props.onCollapse);
              props.onExpand?.();
            } : undefined}
            tabIndex={canExpand ? 0 : -1}
            className={cn(
              "host-no-drag group/brand relative h-8 w-8 shrink-0",
              props.hostChromeInset && "mt-5",
              !canExpand && "pointer-events-none",
            )}
          >
            <span className={cn("relative h-8 w-8", canExpand && "media-hover:group-hover/brand:opacity-0 group-focus-visible/brand:opacity-0")}>
              <img
                src="/brand/nanobot_mark.svg"
                alt=""
                className="theme-art h-8 w-8 select-none object-contain dark:opacity-0"
                draggable={false}
              />
              <img
                src="/brand/nanobot_mark_night.svg"
                alt=""
                className="theme-art absolute inset-0 h-8 w-8 select-none object-contain opacity-0 dark:opacity-100"
                draggable={false}
              />
            </span>
            {canExpand && <PanelLeftOpen aria-hidden className="absolute inset-2 h-4 w-4 opacity-0 media-hover:group-hover/brand:opacity-100 group-focus-visible/brand:opacity-100" />}
          </Button>
        </HoverHint>
        {!collapsed && (
          <div className={cn("flex min-w-0 flex-1 items-center justify-end gap-1", props.hostChromeInset && "mt-5")}>
            {props.onCollapse && (
              <HoverHint content={collapseLabel} side="right">
                <Button
                  ref={collapseButton}
                  type="button"
                  size="icon"
                  variant="icon"
                  className="host-no-drag h-8 w-8 shrink-0 text-sidebar-content"
                  aria-label={collapseLabel}
                  aria-expanded={props.onExpand ? true : undefined}
                  onClick={(event) => {
                    restoreToggleFocus.current = event.detail === 0 && Boolean(props.onExpand);
                    props.onCollapse?.();
                  }}
                >
                  <PanelLeftClose aria-hidden className="h-4 w-4" />
                </Button>
              </HoverHint>
            )}
          </div>
        )}
      </div>

      <div className={cn("flex shrink-0 flex-col", actionInset)}>
        <SidebarActionButton
          collapsed={collapsed}
          label={t("sidebar.newChat")}
          dockLabel={desktopDock}
          onClick={props.onNewChat}
          icon={<ComposeIcon className="h-4 w-4" />}
          shortcut={sidebarShortcutLabel("newChat", apple)}
          ariaKeyShortcuts={sidebarShortcutAria("newChat")}
        />
      </div>
      {collapsed && sessionActions}
      <div
        aria-hidden={collapsed || undefined}
        {...(collapsed ? { inert: "" } : {})}
        className={cn(
          "flex min-h-0 flex-1 flex-col overflow-hidden",
          desktopDock ? "sidebar-dock-history" : "min-w-0",
        )}
      >
        {(desktopDock || !collapsed) && (
          <ChatList
            listHeader={collapsed ? undefined : sessionActions}
            sessions={props.sessions}
            temporarySessions={props.temporarySessions}
            activeKey={props.activeKey}
            loading={props.loading}
            initialLoading={props.initialLoading}
            onSelect={props.onSelect}
            onCloseTemporaryChat={props.onCloseTemporaryChat}
            onRequestDelete={props.onRequestDelete}
            onRequestDeleteMany={props.onRequestDeleteMany}
            onTogglePin={props.onTogglePin}
            onRequestRename={props.onRequestRename}
            onRequestRenameTab={props.onRequestRenameTab}
            onToggleArchive={props.onToggleArchive}
            onArchiveMany={props.onArchiveMany}
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
            sort={props.viewState?.sort}
            showArchived={props.showArchived}
            defaultWorkspacePath={props.defaultWorkspacePath}
            actionMenuPortalContainer={
              props.containActionMenus ? menuPortalContainer : undefined
            }
          />
        )}
      </div>
      {props.onOpenUpdates && props.availableUpdate && (
        <UpdateNotice version={props.availableUpdate.version} collapsed={collapsed}
          onOpen={props.onOpenUpdates} onDismiss={props.availableUpdate.onDismiss}
          onRequestUpdate={props.availableUpdate.onRequestUpdate} installationMethod={props.availableUpdate.installationMethod} />
      )}
      <div
        data-testid="sidebar-footer"
        data-theme-surface
        className={cn(
          "flex shrink-0 flex-col gap-0.5 px-2 py-3 text-xs",
          desktopDock && "px-3",
          props.hostChromeInset && !desktopDock && !collapsed && "bg-sidebar/55",
          collapsed && !desktopDock && "w-14 px-0",
        )}
      >
        <SidebarSelectionHighlight
          targetSelector=':scope > button[aria-current="page"]'
          activeId={activeUtilityId}
          scope="actions"
          className={cn("relative flex flex-col gap-0.5", collapsed && !desktopDock && "items-center")}
        >
          <SidebarActionButton
            {...footerActionProps}
            label={t("sidebar.apps")}
            shortcut={sidebarShortcutLabel("apps", apple)}
            ariaKeyShortcuts={sidebarShortcutAria("apps")}
            onClick={props.onOpenApps}
            active={props.activeUtility === "apps"}
            icon={<AppsIcon className="h-4 w-4" />}
          />
          <SidebarActionButton
            {...footerActionProps}
            label={t("sidebar.automations", { defaultValue: "Automations" })}
            shortcut={sidebarShortcutLabel("automations", apple)}
            ariaKeyShortcuts={sidebarShortcutAria("automations")}
            onClick={props.onOpenAutomations}
            active={props.activeUtility === "automations"}
            icon={<AutomationsIcon className="h-4 w-4" />}
          />
        </SidebarSelectionHighlight>
        <div className={cn("flex min-w-0 items-center gap-1", desktopDock ? "sidebar-dock-footer-row" : collapsed && "flex-col")}>
          <SidebarActionButton
            {...footerActionProps}
            className={desktopDock ? "sidebar-dock-settings" : collapsed ? undefined : "w-auto max-w-[60%] shrink-0"}
            label={t("sidebar.settings")}
            shortcut={sidebarShortcutLabel("settings", apple)}
            ariaKeyShortcuts={sidebarShortcutAria("settings")}
            onClick={props.onOpenSettings}
            icon={<SettingsIcon className="h-4 w-4" />}
          />
          {desktopDock ? (
            <div className="sidebar-dock-host flex min-w-0 items-center">
              <HostSwitcher />
            </div>
          ) : <HostSwitcher collapsed={collapsed} portalContainer={props.containActionMenus ? menuPortalContainer : undefined} />}
        </div>
      </div>
    </nav>
  );
}

function SidebarActionButton({
  collapsed,
  dockLabel = false,
  label,
  icon,
  onClick,
  active = false,
  className,
  shortcut,
  ariaKeyShortcuts,
  onIntent,
  tooltipSide,
}: {
  collapsed: boolean;
  dockLabel?: boolean;
  label: string;
  icon: ReactNode;
  onClick: () => void;
  active?: boolean;
  className?: string;
  shortcut?: string;
  ariaKeyShortcuts?: string;
  onIntent?: () => void;
  tooltipSide?: "top" | "bottom";
}) {
  const compact = collapsed;

  const button = (
    <Button
      type="button"
      variant={compact ? "icon" : null}
      aria-label={label}
      aria-current={active ? "page" : undefined}
      aria-keyshortcuts={ariaKeyShortcuts}
      onClick={() => onClick()}
      onFocus={onIntent}
      onPointerEnter={onIntent}
      className={cn(
        "touch-target group h-8 min-w-0 gap-2 overflow-hidden rounded-control font-normal",
        SIDEBAR_SELECTION_ACTION_ITEM_CLASS,
        dockLabel || !compact
          ? "w-full justify-start gap-2 px-2 text-[13px] leading-5 [&_svg]:h-4 [&_svg]:w-4 [&_svg]:stroke-[1.75]"
          : "w-8 shrink-0 justify-center gap-0 rounded-control px-0",
        active
          ? "text-sidebar-accent-foreground"
          : compact
            ? "text-sidebar-content hover:text-sidebar-accent-foreground"
            : "text-sidebar-content settings-hover hover:text-sidebar-accent-foreground",
        className,
      )}
    >
      <span className="flex shrink-0 items-center justify-center" aria-hidden>
        {icon}
      </span>
      {(dockLabel || !compact) && (
        <span aria-hidden={dockLabel || undefined} className={cn("min-w-0 max-w-48 truncate", dockLabel && "sidebar-dock-label")}>
          {label}
        </span>
      )}
    </Button>
  );
  return compact || shortcut ? (
    <HoverHint side={collapsed ? "right" : tooltipSide ?? "bottom"} contentClassName="flex items-center gap-4" content={<>
      <span>{label}</span>
      {shortcut ? <kbd className="whitespace-nowrap font-sans text-muted-foreground">{shortcut}</kbd> : null}
    </>}>
      {button}
    </HoverHint>
  ) : button;
}
