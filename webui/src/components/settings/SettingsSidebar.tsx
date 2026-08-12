import { useRef } from "react";
import {
  Activity,
  Check,
  ChevronDown,
  ChevronLeft,
  Globe2,
  ImageIcon,
  LogOut,
  MessageCircle,
  Mic,
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
import type { SettingsSectionKey } from "@/components/settings/contracts";
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
  { key: "image", icon: ImageIcon, fallback: "Image" },
  { key: "voice", icon: Mic, fallback: "Voice" },
  { key: "browser", icon: Globe2, fallback: "Web" },
  { key: "channels", icon: MessageCircle, fallback: "Channels" },
  { key: "runtime", icon: Server, fallback: "System" },
  { key: "advanced", icon: ShieldCheck, fallback: "Security" },
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
}: {
  activeSection: SettingsSectionKey;
  onSelectSection: (section: SettingsSectionKey) => void;
  onBackToChat: () => void;
  onLogout?: () => void;
  hostChromeInset?: boolean;
}) {
  const { t } = useTranslation();
  const activeNavItemRef = useRef<HTMLButtonElement>(null);
  const activeItem = SETTINGS_NAV_ITEMS.find((item) => item.key === activeSection)
    ?? SETTINGS_NAV_ITEMS[0];
  const ActiveIcon = activeItem.icon;
  const activeLabel = t(`settings.nav.${activeItem.key}`, {
    defaultValue: activeItem.fallback,
  });

  return (
    <aside
      className={cn(
        "flex w-full shrink-0 flex-col bg-settings-surface px-3 pb-2 lg:w-[17rem] lg:px-3 lg:pb-4",
        hostChromeInset ? "pt-[4.25rem] lg:pt-[4.25rem]" : "pt-4 lg:pt-4",
      )}
    >
      <button
        type="button"
        onClick={onBackToChat}
        className="touch-target mb-2 inline-flex w-fit items-center gap-1.5 rounded-full px-2.5 py-1.5 text-[12px] font-medium text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground lg:mb-3"
      >
        <ChevronLeft className="h-3.5 w-3.5" aria-hidden />
        {t("settings.backToChat")}
      </button>
      <div className="mb-3 px-1 lg:mb-4 lg:px-2">
        <h1 className="text-[18px] font-normal tracking-normal text-foreground">
          {t("settings.sidebar.title")}
        </h1>
      </div>

      <nav
        aria-label={t("settings.sidebar.ariaLabel")}
        className="w-full"
      >
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              aria-label={`${t("settings.sidebar.title")}: ${activeLabel}`}
              className="touch-target flex h-11 w-full items-center gap-2.5 rounded-[14px] bg-sidebar-accent px-3 text-left text-[13px] font-medium text-foreground transition-colors hover:bg-sidebar-accent/80 lg:hidden"
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
              const active = key === activeSection;
              return (
                <DropdownMenuItem
                  key={key}
                  aria-current={active ? "page" : undefined}
                  onSelect={() => onSelectSection(key)}
                  className={cn(
                    "flex h-10 cursor-default items-center gap-2.5 px-2.5 text-[13px] font-medium",
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
          activeId={activeSection}
          scope="settings"
          className="relative hidden space-y-1 lg:block"
        >
          {SETTINGS_NAV_ITEMS.map(({ key, icon: Icon, fallback }) => {
            const active = key === activeSection;
            return (
              <button
                ref={active ? activeNavItemRef : undefined}
                key={key}
                type="button"
                aria-current={active ? "page" : undefined}
                onClick={() => onSelectSection(key)}
                className={cn(
                  "touch-target flex h-9 w-full items-center gap-2 rounded-xl px-2.5 text-left text-[13px] font-medium",
                  SIDEBAR_SELECTION_ITEM_CLASS,
                  active
                    ? "text-sidebar-accent-foreground"
                    : "text-muted-foreground/78 hover:bg-muted/45 hover:text-foreground",
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

      <div className="hidden lg:mt-auto lg:block lg:pt-4">
        {onLogout && !hostChromeInset ? (
          <Button
            type="button"
            variant="ghost"
            onClick={onLogout}
            className="h-9 w-full justify-start gap-2 rounded-[10px] px-2.5 text-[13px] font-medium text-muted-foreground hover:bg-destructive/8 hover:text-destructive"
          >
            <LogOut className="h-4 w-4" aria-hidden />
            {t("app.account.logout")}
          </Button>
        ) : null}
      </div>
    </aside>
  );
}
