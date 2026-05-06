import { Menu, Moon, PanelLeftOpen, Settings, Sun } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ThreadHeaderProps {
  title: string;
  onToggleSidebar: () => void;
  theme: "light" | "dark";
  onToggleTheme: () => void;
  onOpenSettings: () => void;
  hideSidebarToggleOnDesktop?: boolean;
  minimal?: boolean;
}

export function ThreadHeader({
  title,
  onToggleSidebar,
  theme,
  onToggleTheme,
  onOpenSettings,
  hideSidebarToggleOnDesktop = false,
  minimal = false,
}: ThreadHeaderProps) {
  const { t } = useTranslation();
  if (minimal) {
    return (
      <div className="relative z-10 flex h-11 items-center justify-between gap-3 px-3 py-2">
        <Button
          variant="ghost"
          size="icon"
          aria-label={t("thread.header.toggleSidebar")}
          onClick={onToggleSidebar}
          className={cn(
            "h-7 w-7 rounded-md text-muted-foreground hover:bg-accent/35 hover:text-foreground",
            hideSidebarToggleOnDesktop && "lg:pointer-events-none lg:opacity-0",
          )}
        >
          <Menu className="h-3.5 w-3.5" />
        </Button>
        <div className="flex items-center gap-0.5">
          <Button
            variant="ghost"
            size="icon"
            aria-label={t("thread.header.toggleTheme")}
            onClick={onToggleTheme}
            className="h-8 w-8 rounded-full text-muted-foreground/85 hover:bg-accent/40 hover:text-foreground"
          >
            {theme === "dark" ? (
              <Sun className="h-4 w-4" />
            ) : (
              <Moon className="h-4 w-4" />
            )}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label={t("thread.header.settings")}
            onClick={onOpenSettings}
            className="h-8 w-8 rounded-full text-muted-foreground/85 hover:bg-accent/40 hover:text-foreground"
          >
            <Settings className="h-4 w-4" />
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="relative z-10 flex items-center justify-between gap-3 px-3 py-2">
      <div className="relative flex min-w-0 items-center gap-2">
        <Button
          variant="ghost"
          size="icon"
          aria-label={t("thread.header.toggleSidebar")}
          onClick={onToggleSidebar}
          className={cn(
            "h-7 w-7 rounded-md text-muted-foreground hover:bg-accent/35 hover:text-foreground",
            hideSidebarToggleOnDesktop && "lg:pointer-events-none lg:opacity-0",
          )}
        >
          <PanelLeftOpen className="h-3.5 w-3.5" />
        </Button>
        <div className="flex min-w-0 items-center rounded-md px-1.5 py-1 text-[12px] font-medium text-muted-foreground">
          <span className="max-w-[min(60vw,32rem)] truncate">{title}</span>
        </div>
      </div>

      <div className="flex items-center gap-0.5">
        <Button
          variant="ghost"
          size="icon"
          aria-label={t("thread.header.toggleTheme")}
          onClick={onToggleTheme}
          className="h-8 w-8 rounded-full text-muted-foreground/85 hover:bg-accent/40 hover:text-foreground"
        >
          {theme === "dark" ? (
            <Sun className="h-4 w-4" />
          ) : (
            <Moon className="h-4 w-4" />
          )}
        </Button>
        <Button
          variant="ghost"
          size="icon"
          aria-label={t("thread.header.settings")}
          onClick={onOpenSettings}
          className="h-8 w-8 rounded-full text-muted-foreground/85 hover:bg-accent/40 hover:text-foreground"
        >
          <Settings className="h-4 w-4" />
        </Button>
      </div>

      <div aria-hidden className="pointer-events-none absolute inset-x-0 top-full h-4" />
    </div>
  );
}
