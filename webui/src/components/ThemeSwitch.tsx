import { Menu, Moon, Sun } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "./ui/button";

export default function HostChrome({
  onToggleSidebar,
  theme,
  onToggleTheme,
  showThemeButton = true,
  sidebarCollapsed,
  onSidebarHoverStart,
  onSidebarHoverEnd,
}: {
  onToggleSidebar?: () => void;
  theme: "light" | "dark";
  onToggleTheme: () => void;
  showThemeButton?: boolean;
  sidebarCollapsed?: boolean;
  onSidebarHoverStart?: () => void;
  onSidebarHoverEnd?: () => void;
}) {
  const { t } = useTranslation();

  return (
    <header className="host-drag-region pointer-events-none absolute inset-x-0 top-0 z-40 flex h-11 items-start justify-between bg-transparent px-3 pt-2 text-foreground/90">
      <div className="flex min-w-[8rem] items-center">
        {onToggleSidebar ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            data-testid="host-sidebar-toggle"
            aria-label={t("thread.header.toggleSidebar")}
            onClick={onToggleSidebar}
            onMouseEnter={sidebarCollapsed ? onSidebarHoverStart : undefined}
            onMouseLeave={sidebarCollapsed ? onSidebarHoverEnd : undefined}
            className="host-no-drag pointer-events-auto ml-[88px] h-8 w-8 rounded-xl text-muted-foreground/85 hover:bg-accent/40 hover:text-foreground"
          >
            <Menu className="h-4 w-4" />
          </Button>
        ) : null}
      </div>
      {showThemeButton ? (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={t("thread.header.toggleTheme")}
          onClick={onToggleTheme}
          className="host-no-drag pointer-events-auto h-8 w-8 rounded-full text-muted-foreground/85 hover:bg-accent/40 hover:text-foreground"
        >
          {theme === "dark" ? (
            <Sun className="h-4 w-4" />
          ) : (
            <Moon className="h-4 w-4" />
          )}
        </Button>
      ) : (
        <div aria-hidden className="host-no-drag pointer-events-none h-8 w-8" />
      )}
    </header>
  );
}
