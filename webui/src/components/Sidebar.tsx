import { useState } from "react";
import {
  Archive,
  ListFilter,
  Menu,
  Search,
  Settings,
  SquarePen,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { ChatList } from "@/components/ChatList";
import { ConnectionBadge } from "@/components/ConnectionBadge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Separator } from "@/components/ui/separator";
import type {
  ChatSummary,
  SidebarSortMode,
  SidebarViewState,
} from "@/lib/types";

interface SidebarProps {
  sessions: ChatSummary[];
  activeKey: string | null;
  loading: boolean;
  onNewChat: () => void;
  onSelect: (key: string) => void;
  onRequestDelete: (key: string, label: string) => void;
  onTogglePin: (key: string) => void;
  onRequestRename: (key: string, label: string) => void;
  onToggleArchive: (key: string) => void;
  onOpenSettings: () => void;
  onOpenSearch: () => void;
  onToggleArchived: () => void;
  onUpdateView: (view: Partial<SidebarViewState>) => void;
  onCollapse: () => void;
  containActionMenus?: boolean;
  pinnedKeys?: string[];
  archivedKeys?: string[];
  titleOverrides?: Record<string, string>;
  runningChatIds?: string[];
  completedChatIds?: string[];
  viewState?: SidebarViewState;
  showArchived?: boolean;
  archivedCount?: number;
}

export function Sidebar(props: SidebarProps) {
  const { t } = useTranslation();
  const [menuPortalContainer, setMenuPortalContainer] =
    useState<HTMLElement | null>(null);

  return (
    <nav
      ref={props.containActionMenus ? setMenuPortalContainer : undefined}
      aria-label={t("sidebar.navigation")}
      className="flex h-full w-full min-w-0 flex-col border-r border-sidebar-border/60 bg-sidebar text-sidebar-foreground"
    >
      <div className="flex items-center justify-between px-3 pb-2.5 pt-3">
        <picture className="block min-w-0">
          <source srcSet="/brand/nanobot_logo.webp" type="image/webp" />
          <img
            src="/brand/nanobot_logo.png"
            alt="nanobot"
            className="h-6 w-auto select-none object-contain opacity-95"
            draggable={false}
          />
        </picture>
        <Button
          variant="ghost"
          size="icon"
          aria-label={t("sidebar.collapse")}
          onClick={props.onCollapse}
          className="h-7 w-7 rounded-lg text-muted-foreground/85 hover:bg-sidebar-accent/75 hover:text-sidebar-foreground"
        >
          <Menu className="h-3.5 w-3.5" />
        </Button>
      </div>

      <div className="space-y-1.5 px-2 pb-2">
        <Button
          onClick={props.onNewChat}
          className="h-8 w-full justify-start gap-2 rounded-full px-3 text-[12.5px] font-medium text-sidebar-foreground/92 hover:bg-sidebar-accent/75 hover:text-sidebar-foreground"
          variant="ghost"
        >
          <SquarePen className="h-3.5 w-3.5" />
          {t("sidebar.newChat")}
        </Button>
        <Button
          type="button"
          onClick={props.onOpenSearch}
          className="h-8 w-full justify-start gap-2 rounded-full px-3 text-[12.5px] font-medium text-sidebar-foreground/85 hover:bg-sidebar-accent/75 hover:text-sidebar-foreground"
          variant="ghost"
        >
          <Search className="h-3.5 w-3.5" aria-hidden />
          {t("sidebar.searchAria")}
        </Button>
        <SidebarViewMenu
          view={props.viewState}
          onUpdateView={props.onUpdateView}
        />
        {props.archivedCount ? (
          <Button
            type="button"
            onClick={props.onToggleArchived}
            className="h-8 w-full justify-start gap-2 rounded-full px-3 text-[12.5px] font-medium text-sidebar-foreground/75 hover:bg-sidebar-accent/75 hover:text-sidebar-foreground"
            variant="ghost"
          >
            <Archive className="h-3.5 w-3.5" aria-hidden />
            {props.showArchived ? t("chat.hideArchived") : t("chat.showArchived")}
          </Button>
        ) : null}
      </div>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        <ChatList
          sessions={props.sessions}
          activeKey={props.activeKey}
          loading={props.loading}
          emptyLabel={t("chat.noSessions")}
          onSelect={props.onSelect}
          onRequestDelete={props.onRequestDelete}
          onTogglePin={props.onTogglePin}
          onRequestRename={props.onRequestRename}
          onToggleArchive={props.onToggleArchive}
          pinnedKeys={props.pinnedKeys}
          archivedKeys={props.archivedKeys}
          titleOverrides={props.titleOverrides}
          runningChatIds={props.runningChatIds}
          completedChatIds={props.completedChatIds}
          density={props.viewState?.density}
          showPreviews={props.viewState?.show_previews}
          showTimestamps={props.viewState?.show_timestamps}
          sort={props.viewState?.sort}
          showArchived={props.showArchived}
          actionMenuPortalContainer={
            props.containActionMenus ? menuPortalContainer : undefined
          }
        />
      </div>
      <Separator className="bg-sidebar-border/50" />
      <div className="flex items-center gap-1 px-2.5 py-2.5 text-xs">
        <Button
          type="button"
          variant="ghost"
          onClick={props.onOpenSettings}
          className="h-8 min-w-0 flex-1 justify-start gap-2 rounded-full px-2.5 text-[12.5px] font-medium text-sidebar-foreground/85 hover:bg-sidebar-accent/75 hover:text-sidebar-foreground"
        >
          <Settings className="h-3.5 w-3.5" aria-hidden />
          {t("sidebar.settings")}
        </Button>
        <ConnectionBadge />
      </div>
    </nav>
  );
}

function SidebarViewMenu({
  view,
  onUpdateView,
}: {
  view?: SidebarViewState;
  onUpdateView: (view: Partial<SidebarViewState>) => void;
}) {
  const { t } = useTranslation();
  const sort = view?.sort ?? "updated_desc";
  const setSort = (value: string) => {
    if (isSidebarSortMode(value)) onUpdateView({ sort: value });
  };

  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          className="h-8 w-full justify-start gap-2 rounded-full px-3 text-[12.5px] font-medium text-sidebar-foreground/75 hover:bg-sidebar-accent/75 hover:text-sidebar-foreground"
          variant="ghost"
        >
          <ListFilter className="h-3.5 w-3.5" aria-hidden />
          {t("sidebar.viewOptions")}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-52">
        <DropdownMenuLabel className="text-xs text-muted-foreground">
          {t("sidebar.viewOptions")}
        </DropdownMenuLabel>
        <DropdownMenuCheckboxItem
          checked={view?.density === "compact"}
          onCheckedChange={(checked) =>
            onUpdateView({ density: checked ? "compact" : "comfortable" })
          }
          onSelect={(event) => event.preventDefault()}
        >
          {t("sidebar.compactList")}
        </DropdownMenuCheckboxItem>
        <DropdownMenuCheckboxItem
          checked={Boolean(view?.show_previews)}
          onCheckedChange={(checked) =>
            onUpdateView({ show_previews: Boolean(checked) })
          }
          onSelect={(event) => event.preventDefault()}
        >
          {t("sidebar.showPreviews")}
        </DropdownMenuCheckboxItem>
        <DropdownMenuCheckboxItem
          checked={Boolean(view?.show_timestamps)}
          onCheckedChange={(checked) =>
            onUpdateView({ show_timestamps: Boolean(checked) })
          }
          onSelect={(event) => event.preventDefault()}
        >
          {t("sidebar.showTimestamps")}
        </DropdownMenuCheckboxItem>
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="text-xs text-muted-foreground">
          {t("sidebar.sortLabel")}
        </DropdownMenuLabel>
        <DropdownMenuRadioGroup value={sort} onValueChange={setSort}>
          <DropdownMenuRadioItem value="updated_desc">
            {t("sidebar.sortUpdated")}
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="created_desc">
            {t("sidebar.sortCreated")}
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="title_asc">
            {t("sidebar.sortTitle")}
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function isSidebarSortMode(value: string): value is SidebarSortMode {
  return value === "updated_desc" || value === "created_desc" || value === "title_asc";
}
