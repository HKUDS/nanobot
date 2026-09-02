import { Menu, MessageCircleDashed, Moon, Sun } from "lucide-react";
import { type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { SessionHandleLabel } from "@/components/SessionHandleLabel";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { SessionHandle } from "@/lib/types";

interface ThreadHeaderProps {
  title: string;
  handle?: SessionHandle | null;
  onToggleSidebar: () => void;
  theme: "light" | "dark";
  onToggleTheme: () => void;
  hideSidebarToggleForHostChrome?: boolean;
  hideSidebarToggle?: boolean;
  hideThemeButton?: boolean;
  hideTitle?: boolean;
  actions?: ReactNode;
  minimal?: boolean;
  promptNavigatorAction?: ReactNode;
  sessionInfoAction?: ReactNode;
  temporaryChatEnabled?: boolean;
  temporaryChatDisabled?: boolean;
  onTemporaryChatEnabledChange?: (enabled: boolean) => void;
}

export function ThreadHeader({
  title,
  handle = null,
  onToggleSidebar,
  theme,
  onToggleTheme,
  hideSidebarToggleForHostChrome = false,
  hideSidebarToggle = false,
  hideThemeButton = false,
  hideTitle = false,
  actions,
  minimal = false,
  promptNavigatorAction,
  sessionInfoAction,
  temporaryChatEnabled = false,
  temporaryChatDisabled = false,
  onTemporaryChatEnabledChange,
}: ThreadHeaderProps) {
  const { t } = useTranslation();

  return (
    <div
      data-testid="thread-header"
      className={cn(
        "relative z-30 flex items-center justify-between gap-3 px-3 py-1",
        minimal && "h-11",
      )}
    >
      <div className="relative flex min-w-0 items-center gap-2">
        {!hideSidebarToggle ? (
          <Button
            variant="ghost"
            size="icon"
            aria-label={t("thread.header.toggleSidebar")}
            onClick={onToggleSidebar}
            className={cn(
              "h-7 w-7 rounded-md text-muted-foreground hover:bg-accent/35 hover:text-foreground",
              hideSidebarToggleForHostChrome && "lg:hidden",
            )}
          >
            <Menu className="h-3.5 w-3.5" />
          </Button>
        ) : null}
        {!minimal && !hideTitle ? (
          <div className="flex min-w-0 items-center rounded-md px-1.5 py-1 text-[12px] font-medium text-muted-foreground">
            <span className="max-w-[min(60vw,32rem)] truncate">{title}</span>
          </div>
        ) : null}
        {handle ? (
          <span
            className="flex shrink-0 items-center rounded-md px-1.5 py-1 text-[12px] font-medium"
          >
            <SessionHandleLabel id={handle.id}>
              @{handle.name}
            </SessionHandleLabel>
          </span>
        ) : null}
      </div>

      <div className="ml-auto flex shrink-0 items-center gap-1">
        {sessionInfoAction}
        {promptNavigatorAction}
        {actions}
        {onTemporaryChatEnabledChange ? (
          <TooltipProvider delayDuration={700} skipDelayDuration={0}>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  disabled={temporaryChatDisabled}
                  aria-label={t("temporaryChat.title")}
                  aria-pressed={temporaryChatEnabled}
                  onClick={() => onTemporaryChatEnabledChange(!temporaryChatEnabled)}
                  className={cn(
                    "host-no-drag h-8 w-8 shrink-0 rounded-full bg-transparent text-muted-foreground shadow-none transition-none hover:text-foreground",
                    temporaryChatEnabled ? "hover:bg-transparent" : "hover:bg-accent/45",
                  )}
                >
                  <MessageCircleDashed
                    data-testid="temporary-chat-icon"
                    className={cn(
                      "h-4 w-4 motion-safe:transition-colors",
                      temporaryChatEnabled
                        ? "text-[var(--temporary-control-active)] motion-safe:duration-150"
                        : "text-current motion-safe:duration-75",
                    )}
                    aria-hidden
                  />
                </Button>
              </TooltipTrigger>
              <TooltipContent
                side="bottom"
                align="end"
                className="max-w-72 rounded-xl border border-border/70 bg-popover px-3 py-2 text-[12px]/[1.4] text-popover-foreground shadow-[0_8px_24px_rgba(15,23,42,0.13)] dark:border-white/10"
              >
                <div className="font-medium">{t("temporaryChat.title")}</div>
                <div className="mt-1 text-muted-foreground">
                  {t("temporaryChat.retention")}
                </div>
                <div className="mt-1 font-medium">
                  {t("temporaryChat.expiration")}
                </div>
                <div className="mt-1 text-muted-foreground">
                  {t("temporaryChat.externalEffects")}
                </div>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ) : null}
        {!hideThemeButton ? (
          <ThemeButton
            theme={theme}
            onToggleTheme={onToggleTheme}
            label={t("thread.header.toggleTheme")}
          />
        ) : null}
      </div>

      {!minimal ? (
        <div aria-hidden className="pointer-events-none absolute inset-x-0 top-full h-4" />
      ) : null}
    </div>
  );
}

function ThemeButton({
  theme,
  onToggleTheme,
  label,
  className,
}: {
  theme: "light" | "dark";
  onToggleTheme: () => void;
  label: string;
  className?: string;
}) {
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={label}
      onClick={onToggleTheme}
      className={cn(
        "host-no-drag h-8 w-8 rounded-full text-muted-foreground/85 hover:bg-accent/40 hover:text-foreground",
        className,
      )}
    >
      {theme === "dark" ? (
        <Sun className="h-4 w-4" />
      ) : (
        <Moon className="h-4 w-4" />
      )}
    </Button>
  );
}
