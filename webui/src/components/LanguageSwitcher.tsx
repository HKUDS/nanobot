import { useTranslation } from "react-i18next";

import { currentLocale, setAppLanguage } from "@/i18n";
import { supportedLocales, type SupportedLocale } from "@/i18n/config";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export function LanguageSwitcher() {
  const { t } = useTranslation();
  return (
    <Select value={currentLocale()} onValueChange={(value) => { void setAppLanguage(value as SupportedLocale); }}>
      <SelectTrigger className="min-w-40" aria-label={t("sidebar.language.ariaLabel")}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {supportedLocales.map((option) => (
          <SelectItem key={option.code} value={option.code}>{option.nativeLabel}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
