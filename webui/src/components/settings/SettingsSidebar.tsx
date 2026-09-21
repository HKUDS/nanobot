import { useRef, useState } from "react";
import {
  Activity,
  Info,
  Check,
  ChevronDown,
  ChevronLeft,
  LogOut,
  Loader2,
  RotateCcw,
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
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { cn } from "@/lib/utils";

const SETTINGS_NAV_ITEMS: Array<{ key: SettingsSectionKey; icon: LucideIcon; fallback: string }> = [
  { key: "overview", icon: Activity, fallback: "Overview" },
  { key: "appearance", icon: Palette, fallback: "Appearance" },
  { key: "models", icon: SlidersHorizontal, fallback: "Models" },
  { key: "capabilities", icon: Blocks, fallback: "Capabilities" },
  { key: "runtime", icon: Server, fallback: "System" },
  { key: "advanced", icon: ShieldCheck, fallback: "Advanced" },
  { key: "about", icon: Info, fallback: "About" },
];

export function standaloneSectionTitle(section: SettingsSectionKey): string {
  if (section === "apps") return "Apps";
  if (section === "automations") return "Automations";
  if (section === "skills") return "Skills";
  if (section === "channels") return "Channels";
  return SETTINGS_NAV_ITEMS.find((item) => item.key === section)?.fallback ?? "Settings";
}

interface SettingsSidebarProps {
  activeSection: SettingsSectionKey;
  onSelectSection: (section: SettingsSectionKey) => void;
  onBackToChat: () => void;
  onLogout?: () => void;
  hostChromeInset?: boolean;
  onRestart?: () => void;
  isRestarting?: boolean;
  restartPending?: boolean;
  isNativeHost?: boolean;
}

export function SettingsSidebar(props: SettingsSidebarProps) {
  const {
    activeSection,
    onSelectSection,
    onBackToChat,
    onLogout,
    hostChromeInset,
    onRestart,
    isRestarting,
    restartPending,
    isNativeHost,
  } = props;
  const { t } = useTranslation();
  const mobile = useMediaQuery("(max-width: 1023px)");
  const restartLabel = isRestarting
    ? t(isNativeHost ? "app.system.restartingEngine" : "app.system.restarting")
    : t("app.system.restartAction");
  const navSection = isCapabilitySection(activeSection) ? "capabilities" : activeSection;
  const activeNavItemRef = useRef<HTMLButtonElement>(null);
  const activeItem = SETTINGS_NAV_ITEMS.find((item) => item.key === navSection)
    ?? SETTINGS_NAV_ITEMS[0];
  const activeLabel = t(`settings.nav.${activeItem.key}`, {
    defaultValue: activeItem.fallback,
  });

  if (mobile) {
    return <MobileSettingsNavigation {...props} navSection={navSection}
      activeLabel={activeLabel} restartLabel={restartLabel} />;
  }

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
          "touch-target mb-2 inline-flex h-9 w-9 items-center justify-center rounded-full text-[13px] leading-5 font-normal text-sidebar-content transition-colors settings-hover hover:text-foreground lg:mb-3",
          hostChromeInset && "-ml-1",
        )}
      >
        <ChevronLeft className="h-4 w-4" aria-hidden />
      </button>

      <nav
        aria-label={t("settings.sidebar.ariaLabel")}
        className="w-full"
      >
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
                  "touch-target flex h-9 w-full items-center gap-2 rounded-xl px-2.5 text-left text-[13px] leading-5 font-normal",
                  SIDEBAR_SELECTION_ITEM_CLASS,
                  active
                    ? "text-sidebar-accent-foreground"
                    : "text-sidebar-content settings-hover hover:text-foreground",
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
              className={cn("h-9 w-full justify-start gap-2 rounded-control px-2.5 text-[13px] leading-5 font-normal settings-hover",
                restartPending && !isRestarting
                  ? "settings-restart-pending text-orange-600 hover:text-orange-700 dark:text-orange-400 dark:hover:text-orange-300"
                  : "text-sidebar-content hover:text-foreground")}
            >
              {isRestarting ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                : <RotateCcw className="h-4 w-4" aria-hidden />}
              <span>{restartLabel}</span>
            </Button>
          </div>
        ) : null}
        {onLogout && !hostChromeInset ? (
          <Button
            type="button"
            variant="ghost"
            onClick={onLogout}
            className="hidden h-9 w-full justify-start gap-2 rounded-control px-2.5 text-[13px] leading-5 font-normal text-sidebar-content hover:bg-destructive/8 hover:text-destructive lg:flex"
          >
            <LogOut className="h-4 w-4" aria-hidden />
            <span>{t("app.account.logout")}</span>
          </Button>
        ) : null}
      </div>
    </aside>
  );
}

// Mount only on narrow screens so an open menu cannot survive a switch to desktop.
function MobileSettingsNavigation({
  navSection,
  activeLabel,
  restartLabel,
  onSelectSection,
  onBackToChat,
  hostChromeInset,
  onRestart,
  isRestarting,
  restartPending,
}: SettingsSidebarProps & {
  navSection: SettingsSectionKey;
  activeLabel: string;
  restartLabel: string;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const restart = () => { setOpen(false); onRestart?.(); };
  const restartTone = restartPending && !isRestarting
    ? "text-orange-600 hover:text-orange-700 dark:text-orange-400 dark:hover:text-orange-300"
    : "text-muted-foreground hover:text-foreground";
  const restartIcon = isRestarting ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
    : <RotateCcw className="h-4 w-4" aria-hidden />;
  const restartAction = onRestart ? (
    <Button type="button" variant="ghost" disabled={isRestarting}
      onClick={restart}
      className={cn("h-11 shrink-0 gap-2 px-3 text-sm font-normal", restartTone)}
    >
      {restartIcon}
      {restartLabel}
    </Button>
  ) : null;

  return (
    <aside className={cn("shrink-0 border-b border-border/50 bg-settings-canvas",
      hostChromeInset ? "pt-10" : "pt-[env(safe-area-inset-top)]")}
    >
      <div className="grid h-14 grid-cols-[2.75rem_minmax(0,1fr)_2.75rem] items-center px-3">
        <Button type="button" variant="ghost" onClick={onBackToChat}
          aria-label={t("settings.backToChat")}
          className="h-11 w-11 rounded-full p-0 text-sidebar-content"
        >
          <ChevronLeft className="h-5 w-5" aria-hidden />
        </Button>
        <DropdownMenu open={open} onOpenChange={setOpen} modal={false}>
          <DropdownMenuTrigger asChild>
            <Button type="button" variant="ghost"
              aria-label={`${t("settings.sidebar.title")}: ${activeLabel}`}
              className="h-11 min-w-0 max-w-full justify-self-center gap-1.5 px-2 text-base font-medium"
            >
              <span className="truncate">{activeLabel}</span>
              <ChevronDown className={cn("h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform duration-150 motion-reduce:transition-none", open && "rotate-180")} aria-hidden />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="bottom" align="center" sideOffset={6} collisionPadding={12}
            aria-label={t("settings.sidebar.ariaLabel")} aria-labelledby={undefined}
            className="w-60 max-w-[calc(100vw-1.5rem)] data-[state=open]:slide-in-from-top-1 data-[state=closed]:slide-out-to-top-1 data-[state=open]:duration-150 data-[state=closed]:duration-100 motion-reduce:data-[state=open]:animate-none motion-reduce:data-[state=closed]:animate-none"
          >
            {SETTINGS_NAV_ITEMS.map(({ key, icon: Icon, fallback }) => {
              const active = key === navSection;
              return (
                <DropdownMenuItem key={key}
                  aria-current={active ? "page" : undefined}
                  onSelect={() => onSelectSection(key)}
                  className={cn("min-h-11 gap-3 text-sm font-normal",
                    active ? "bg-sidebar-accent text-foreground" : "text-sidebar-content")}
                >
                  <Icon aria-hidden />
                  <span className="min-w-0 flex-1 truncate">
                    {t(`settings.nav.${key}`, { defaultValue: fallback })}
                  </span>
                  {active ? <Check aria-hidden /> : null}
                </DropdownMenuItem>
              );
            })}
            {onRestart ? <>
              <DropdownMenuSeparator />
              <DropdownMenuItem disabled={isRestarting} onSelect={restart}
                className={cn("min-h-11 gap-3 text-sm font-normal", restartTone)}
              >{restartIcon}{restartLabel}</DropdownMenuItem>
            </> : null}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      {onRestart && (restartPending || isRestarting) ? (
        <div className="flex min-h-11 items-center justify-between gap-2 px-4 pb-1">
          <p role="status" className="text-xs leading-5 text-muted-foreground">
            {isRestarting ? restartLabel : t("settings.status.savedRestartApply")}
          </p>
          {restartAction}
        </div>
      ) : null}
    </aside>
  );
}
