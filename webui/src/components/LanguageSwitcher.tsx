import { useTranslation } from "react-i18next";

import { currentLocale, setAppLanguage } from "@/i18n";
import { persistLocale, supportedLocales, type SupportedLocale } from "@/i18n/config";
import { cn } from "@/lib/utils";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export function LanguageSwitcher({ className }: { className?: string }) {
  const { t } = useTranslation();
  return (
    <Select value={currentLocale()} onValueChange={(value) => { void setAppLanguage(value as SupportedLocale); }}>
      <SelectTrigger
        className={cn("min-w-40 rounded-full", className)}
        aria-label={t("sidebar.language.ariaLabel")}
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {supportedLocales.map((option) => (
          <SelectItem
            key={option.code}
            value={option.code}
            onPointerUp={(event) => {
              if (event.pointerType === "mouse" && option.code === currentLocale()) persistLocale(option.code);
            }}
            onClick={() => {
              if (option.code === currentLocale()) persistLocale(option.code);
            }}
            onKeyDown={(event) => {
              if (option.code !== currentLocale()) return;
              if (event.key === "Enter") persistLocale(option.code);
              if (event.key === " ") {
                // Radix prevents the space key only when it selects, not during typeahead.
                queueMicrotask(() => { if (event.defaultPrevented) persistLocale(option.code); });
              }
            }}
          >{option.nativeLabel}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
