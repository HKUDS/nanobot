import { useTranslation } from "react-i18next";

import { SettingsHint } from "@/components/settings/shared/SettingsHint";
import { Button } from "@/components/ui/button";
import { ToggleButton } from "@/components/ui/toggle-button";
import { cn } from "@/lib/utils";

export function ProxySettingsControl({ checked, disabled, onChange, onConfigure, className }: {
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
  onConfigure?: () => void;
  className?: string;
}) {
  const { t } = useTranslation();
  return (
    <div data-proxy-control className={cn("flex items-center justify-between gap-4", className)}>
      <SettingsHint description={t("settings.network.useProxyHelp")}>
        <span className="block text-[13px] font-medium leading-5 text-foreground">{t("settings.network.useProxy")}</span>
      </SettingsHint>
      {onConfigure ? (
        <Button type="button" variant="outline" size="sm" onClick={onConfigure}
          className="h-7 shrink-0 rounded-full px-3 text-[13px] font-medium leading-5">
          {t("settings.network.configureProxy")}
        </Button>
      ) : (
        <ToggleButton checked={checked} disabled={disabled} onChange={onChange} label={t("settings.network.useProxy")} />
      )}
    </div>
  );
}
