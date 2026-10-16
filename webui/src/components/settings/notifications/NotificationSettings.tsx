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
        <div className="settings-section-heading flex flex-wrap items-center justify-between gap-2">
          <SettingsSectionTitle>{t("settings.nav.notifications")}</SettingsSectionTitle>
          <span className="text-[12px] text-muted-foreground">{t("settings.notifications.scope")}</span>
        </div>
        <p className="settings-list-inset mb-3 text-[13px] leading-5 text-muted-foreground">{t("settings.notifications.intro")}</p>
        <SettingsGroup>
          <BrowserNotificationSettings localPrefs={localPrefs} onChangeLocalPrefs={onChangeLocalPrefs} />
          <div>
            <SettingsRow title={t("settings.rows.notificationSound")}>
              <ToggleButton checked={localPrefs.notificationSound}
                onChange={(notificationSound) => onChangeLocalPrefs((previous) => ({ ...previous, notificationSound }))}
                ariaLabel={t("settings.rows.notificationSound")}
                label={t(localPrefs.notificationSound ? "settings.values.on" : "settings.values.off")} />
            </SettingsRow>
            <p className="settings-list-inset pb-4 text-[12px] leading-5 text-muted-foreground">{t("settings.help.notificationSound")}</p>
          </div>
        </SettingsGroup>
        <div className="settings-list-inset mt-4 space-y-1 text-[12px] leading-5 text-muted-foreground">
          <p>{t("settings.notifications.pageRequired")}</p>
          <p>{t("settings.notifications.privacy")}</p>
        </div>
      </section>
    </div>
  );
}
