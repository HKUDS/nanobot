import { useState } from "react";
import { useTranslation } from "react-i18next";

import { currentLocale, setAppLanguage } from "@/i18n";
import { supportedLocales, type SupportedLocale } from "@/i18n/config";
import { cn } from "@/lib/utils";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export function LanguageSwitcher({ className }: { className?: string }) {
  const { t } = useTranslation();
  const [pointerFocus, setPointerFocus] = useState(false);
  return (
    <Select value={currentLocale()} onValueChange={(value) => { void setAppLanguage(value as SupportedLocale); }}>
      <SelectTrigger
        className={cn("min-w-40 rounded-full", pointerFocus && "focus-visible:ring-0", className)}
        aria-label={t("sidebar.language.ariaLabel")}
        onPointerDown={() => setPointerFocus(true)}
        onKeyDown={() => setPointerFocus(false)}
        onBlur={() => setPointerFocus(false)}
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent
        onPointerUpCapture={() => setPointerFocus(true)}
        onPointerDownOutside={() => setPointerFocus(true)}
        onKeyDownCapture={() => setPointerFocus(false)}
        onEscapeKeyDown={() => setPointerFocus(false)}
      >
        {supportedLocales.map((option) => (
          <SelectItem key={option.code} value={option.code}>{option.nativeLabel}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
