import { Menu, MessageCircleDashed, Moon, Sun } from "lucide-react";
import type { ReactNode, Ref } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

interface ThreadHeaderProps {
  title: string;
  onToggleSidebar: () => void;
  theme: "light" | "dark";
  onToggleTheme: () => void;
  hideSidebarToggleForHostChrome?: boolean;
  hostChromeTitleInset?: boolean;
  hideThemeButton?: boolean;
  minimal?: boolean;
  promptNavigatorAction?: ReactNode;
  sessionInfoAction?: ReactNode;
  temporaryChatEnabled?: boolean;
  temporaryChatDisabled?: boolean;
  onTemporaryChatEnabledChange?: (enabled: boolean) => void;
  temporaryChatButtonRef?: Ref<HTMLButtonElement>;
}

export function ThreadHeader({
  title,
  onToggleSidebar,
  theme,
  onToggleTheme,
  hideSidebarToggleForHostChrome = false,
  hostChromeTitleInset = false,
  hideThemeButton = false,
  minimal = false,
  promptNavigatorAction,
  sessionInfoAction,
  temporaryChatEnabled = false,
  temporaryChatDisabled = false,
  onTemporaryChatEnabledChange,
  temporaryChatButtonRef,
}: ThreadHeaderProps) {
  const { t } = useTranslation();

  return (
    <div
      data-testid="thread-header"
      className={cn(
        "relative z-30 flex items-center justify-between gap-3 px-3 py-2",
        minimal && "h-11",
        !minimal && hostChromeTitleInset && "lg:pl-[128px]",
      )}
    >
      <div className="relative flex min-w-0 items-center gap-2">
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
        {!minimal ? (
          <div className="flex min-w-0 items-center rounded-md px-1.5 py-1 text-[12px] font-medium text-muted-foreground">
            <span className="max-w-[min(60vw,32rem)] truncate">{title}</span>
          </div>
        ) : null}
      </div>

      <div className="ml-auto flex shrink-0 items-center gap-1">
        {sessionInfoAction}
        {promptNavigatorAction}
        {onTemporaryChatEnabledChange ? (
          <TooltipProvider delayDuration={220} skipDelayDuration={80}>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  ref={temporaryChatButtonRef}
                  type="button"
                  variant="ghost"
                  disabled={temporaryChatDisabled}
                  aria-label={t("temporaryChat.title")}
                  aria-pressed={temporaryChatEnabled}
                  onClick={() => onTemporaryChatEnabledChange(!temporaryChatEnabled)}
                  className={cn(
                    "host-no-drag h-8 shrink-0 gap-1.5 rounded-full px-2.5 text-[12px] font-medium transition-[color,background-color,box-shadow] duration-200",
                    temporaryChatEnabled
                      ? "bg-[#F97316]/[0.12] text-[#c65309] shadow-[inset_0_0_0_1px_rgba(249,115,22,0.28)] hover:bg-[#F97316]/[0.16] hover:text-[#c65309] dark:text-[#fb923c] dark:hover:text-[#fb923c]"
                      : "text-muted-foreground hover:bg-accent/45 hover:text-foreground",
                  )}
                >
                  <MessageCircleDashed className="h-4 w-4" aria-hidden />
                  <span className="hidden sm:inline">{t("temporaryChat.title")}</span>
                </Button>
              </TooltipTrigger>
              <TooltipContent
                side="bottom"
                align="end"
                className="max-w-72 rounded-xl border border-border/70 bg-popover px-3 py-2 text-[12px]/[1.4] text-popover-foreground shadow-[0_8px_24px_rgba(15,23,42,0.13)] dark:border-white/10"
              >
                {t("temporaryChat.description")}
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
