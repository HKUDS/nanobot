import {
  Menu,
  Search,
  Settings,
  SquarePen,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { ChatList } from "@/components/ChatList";
import { ConnectionBadge } from "@/components/ConnectionBadge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import type { ChatSummary } from "@/lib/types";

interface SidebarProps {
  sessions: ChatSummary[];
  activeKey: string | null;
  loading: boolean;
  onNewChat: () => void;
  onSelect: (key: string) => void;
  onRequestDelete: (key: string, label: string) => void;
  onOpenSettings: () => void;
  onOpenSearch: () => void;
  onCollapse: () => void;
}

export function Sidebar(props: SidebarProps) {
  const { t } = useTranslation();

  return (
    <nav
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
      </div>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        <ChatList
          sessions={props.sessions}
          activeKey={props.activeKey}
          loading={props.loading}
          emptyLabel={t("chat.noSessions")}
          onSelect={props.onSelect}
          onRequestDelete={props.onRequestDelete}
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
