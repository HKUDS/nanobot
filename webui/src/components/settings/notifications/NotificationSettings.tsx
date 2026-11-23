import type { Dispatch, SetStateAction } from "react";
import { useTranslation } from "react-i18next";
import { SettingsGroup, SettingsRow, SettingsSectionTitle } from "@/components/settings/shared/SettingsControls";
import { ToggleButton } from "@/components/ui/toggle-button";
import type { LocalPreferences } from "@/lib/local-preferences";
import { BrowserNotificationSettings } from "./BrowserNotificationSettings";

export function NotificationSettings({ localPrefs, onChangeLocalPrefs }: {
  localPrefs: LocalPreferences;
  onChangeLocalPrefs: Dispatch<SetStateAction<LocalPreferences>>;
}) {
  const { t } = useTranslation();
  return (
    <div className="settings-stack">
      <section>
        <SettingsSectionTitle>{t("settings.notifications.scope")}</SettingsSectionTitle>
        <SettingsGroup>
          <BrowserNotificationSettings localPrefs={localPrefs} onChangeLocalPrefs={onChangeLocalPrefs} />
          <div className="settings-list-inset" aria-hidden="true">
            <div className="border-t border-border/40" />
          </div>
          <SettingsRow title={t("settings.rows.notificationSound")} description={t("settings.help.notificationSound")}>
            <ToggleButton checked={localPrefs.notificationSound}
              onChange={(notificationSound) => onChangeLocalPrefs((previous) => ({ ...previous, notificationSound }))}
              ariaLabel={t("settings.rows.notificationSound")}
              label={t(localPrefs.notificationSound ? "settings.values.on" : "settings.values.off")} />
          </SettingsRow>
        </SettingsGroup>
        <p className="settings-list-inset mt-3 text-[12px] leading-5 text-muted-foreground">
          {t("settings.notifications.pageRequired")}
        </p>
      </section>
    </div>
  );
}
