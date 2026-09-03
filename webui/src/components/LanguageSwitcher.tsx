import { Globe } from "lucide-react";
import { useTranslation } from "react-i18next";

import { setAppLanguage } from "@/i18n";
import {
  currentLocale,
} from "@/i18n";
import {
  localeOption,
  supportedLocales,
  type SupportedLocale,
} from "@/i18n/config";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export function LanguageSwitcher() {
  const { t } = useTranslation();
  const locale = currentLocale();
  const selected = localeOption(locale);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          aria-label={t("sidebar.language.ariaLabel")}
          className="h-7 gap-1.5 rounded-md px-2 text-[11px] text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-foreground"
        >
          <Globe className="h-3.5 w-3.5" />
          <span className="max-w-[7rem] truncate">{selected.nativeLabel}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>{t("sidebar.language.label")}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuRadioGroup
          value={locale}
          onValueChange={(value) => {
            void setAppLanguage(value as SupportedLocale);
          }}
        >
          {supportedLocales.map((option) => (
            <DropdownMenuRadioItem key={option.code} value={option.code}>
              {option.nativeLabel}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
