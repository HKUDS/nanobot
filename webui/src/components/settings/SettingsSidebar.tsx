import { useRef } from "react";
import {
  Activity,
  Info,
  Check,
  ChevronDown,
  ChevronLeft,
  LogOut,
  Loader2,
  RotateCcw,
  MessageCircle,
  Blocks,
  Palette,
  Server,
  ShieldCheck,
  SlidersHorizontal,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  SIDEBAR_SELECTION_ITEM_CLASS,
  SidebarSelectionHighlight,
} from "@/components/SidebarSelectionHighlight";
import { isCapabilitySection, type SettingsSectionKey } from "@/components/settings/contracts";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

const SETTINGS_NAV_ITEMS: Array<{ key: SettingsSectionKey; icon: LucideIcon; fallback: string }> = [
  { key: "overview", icon: Activity, fallback: "Overview" },
  { key: "appearance", icon: Palette, fallback: "Appearance" },
  { key: "models", icon: SlidersHorizontal, fallback: "Models" },
  { key: "capabilities", icon: Blocks, fallback: "Capabilities" },
  { key: "channels", icon: MessageCircle, fallback: "Channels" },
  { key: "runtime", icon: Server, fallback: "System" },
  { key: "advanced", icon: ShieldCheck, fallback: "Advanced" },
  { key: "about", icon: Info, fallback: "About" },
];

export function standaloneSectionTitle(section: SettingsSectionKey): string {
  if (section === "apps") return "Apps";
  if (section === "automations") return "Automations";
  if (section === "skills") return "Skills";
  return SETTINGS_NAV_ITEMS.find((item) => item.key === section)?.fallback ?? "Settings";
}

export function SettingsSidebar({
  activeSection,
  onSelectSection,
  onBackToChat,
  onLogout,
  hostChromeInset,
  onRestart,
  isRestarting,
  restartPending,
  isNativeHost,
}: {
  activeSection: SettingsSectionKey;
  onSelectSection: (section: SettingsSectionKey) => void;
  onBackToChat: () => void;
  onLogout?: () => void;
  hostChromeInset?: boolean;
  onRestart?: () => void;
  isRestarting?: boolean;
  restartPending?: boolean;
  isNativeHost?: boolean;
}) {
  const { t } = useTranslation();
  const restartLabel = isRestarting
    ? t(isNativeHost ? "app.system.restartingEngine" : "app.system.restarting")
    : t("app.system.restartAction");
  const navSection = isCapabilitySection(activeSection) ? "capabilities" : activeSection;
  const activeNavItemRef = useRef<HTMLButtonElement>(null);
  const activeItem = SETTINGS_NAV_ITEMS.find((item) => item.key === navSection)
    ?? SETTINGS_NAV_ITEMS[0];
  const ActiveIcon = activeItem.icon;
  const activeLabel = t(`settings.nav.${activeItem.key}`, {
    defaultValue: activeItem.fallback,
  });

  return (
    <aside
      className={cn(
        "flex w-full shrink-0 select-none flex-col bg-settings-surface px-3 pb-2 lg:w-48 lg:px-3 lg:pb-4",
        hostChromeInset ? "pt-10 lg:pt-10" : "pt-4 lg:pt-4",
      )}
    >
      <button
        type="button"
        onClick={onBackToChat}
        aria-label={t("settings.backToChat")}
        className={cn(
          "touch-target mb-2 inline-flex h-9 w-9 items-center justify-center rounded-full text-[14px] leading-5 font-medium text-muted-foreground transition-colors settings-hover hover:text-foreground lg:mb-3",
          hostChromeInset && "-ml-1",
        )}
      >
        <ChevronLeft className="h-4 w-4" aria-hidden />
      </button>

      <nav
        aria-label={t("settings.sidebar.ariaLabel")}
        className="w-full"
      >
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              aria-label={`${t("settings.sidebar.title")}: ${activeLabel}`}
              className="touch-target flex h-11 w-full items-center gap-2.5 rounded-control bg-sidebar-accent px-3 text-left text-[14px] leading-5 font-medium text-foreground transition-colors settings-hover lg:hidden"
            >
              <ActiveIcon className="h-4 w-4 shrink-0" strokeWidth={2} aria-hidden />
              <span className="min-w-0 flex-1 truncate">{activeLabel}</span>
              <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="start"
            sideOffset={6}
            className="w-[var(--radix-dropdown-menu-trigger-width)] max-w-[calc(100vw-1.5rem)]"
          >
            {SETTINGS_NAV_ITEMS.map(({ key, icon: Icon, fallback }) => {
              const active = key === navSection;
              return (
                <DropdownMenuItem
                  key={key}
                  aria-current={active ? "page" : undefined}
                  onSelect={() => onSelectSection(key)}
                  className={cn(
                    "flex h-10 cursor-default items-center gap-2.5 px-2.5 text-[14px] leading-5 font-medium",
                    active && "bg-sidebar-accent text-foreground focus:bg-sidebar-accent",
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0" strokeWidth={2} aria-hidden />
                  <span className="min-w-0 flex-1 truncate">
                    {t(`settings.nav.${key}`, { defaultValue: fallback })}
                  </span>
                  {active ? <Check className="h-4 w-4 shrink-0" aria-hidden /> : null}
                </DropdownMenuItem>
              );
            })}
          </DropdownMenuContent>
        </DropdownMenu>

        <SidebarSelectionHighlight
          targetRef={activeNavItemRef}
          activeId={navSection}
          scope="settings"
          className="relative hidden space-y-1 lg:block"
        >
          {SETTINGS_NAV_ITEMS.map(({ key, icon: Icon, fallback }) => {
            const active = key === navSection;
            return (
              <button
                ref={active ? activeNavItemRef : undefined}
                key={key}
                type="button"
                aria-current={active ? "page" : undefined}
                onClick={() => onSelectSection(key)}
                className={cn(
                  "touch-target flex h-9 w-full items-center gap-2 rounded-xl px-2.5 text-left text-[14px] leading-5 font-medium",
                  SIDEBAR_SELECTION_ITEM_CLASS,
                  active
                    ? "text-sidebar-accent-foreground"
                    : "text-muted-foreground settings-hover hover:text-foreground",
                )}
              >
                <Icon className="h-4 w-4 shrink-0" strokeWidth={2} aria-hidden />
                <span className="truncate">
                  {t(`settings.nav.${key}`, { defaultValue: fallback })}
                </span>
              </button>
            );
          })}
        </SidebarSelectionHighlight>
      </nav>

      <div className="pt-2 lg:mt-auto lg:pt-4">
        {onRestart ? (
          <div>
            {restartPending ? (
              <p id="settings-restart-status" role="status" className="sr-only">
                {t("settings.status.savedRestartApply")}
              </p>
            ) : null}
            <Button
              type="button"
              variant="ghost"
              onClick={onRestart}
              disabled={isRestarting}
              aria-describedby={restartPending ? "settings-restart-status" : undefined}
              className={cn("h-9 w-full justify-start gap-2 rounded-control px-2.5 text-[14px] leading-5 font-medium settings-hover",
                restartPending && !isRestarting
                  ? "settings-restart-pending text-orange-600 hover:text-orange-700 dark:text-orange-400 dark:hover:text-orange-300"
                  : "text-muted-foreground hover:text-foreground")}
            >
              {isRestarting ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                : <RotateCcw className="h-4 w-4" aria-hidden />}
              <span className="sidebar-action-label [--sidebar-label-width:4em]">{restartLabel}</span>
            </Button>
          </div>
        ) : null}
        {onLogout && !hostChromeInset ? (
          <Button
            type="button"
            variant="ghost"
            onClick={onLogout}
            className="hidden h-9 w-full justify-start gap-2 rounded-control px-2.5 text-[14px] leading-5 font-medium text-muted-foreground hover:bg-destructive/8 hover:text-destructive lg:flex"
          >
            <LogOut className="h-4 w-4" aria-hidden />
            <span className="sidebar-action-label [--sidebar-label-width:4em]">{t("app.account.logout")}</span>
          </Button>
        ) : null}
      </div>
    </aside>
  );
}
