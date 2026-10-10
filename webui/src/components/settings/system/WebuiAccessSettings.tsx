import { useTranslation } from "react-i18next";

import { ToggleButton } from "@/components/settings/ToggleButton";
import {
  ReadOnlyRow,
  SettingsGroup,
  SettingsRow,
  SettingsSectionTitle,
} from "@/components/settings/shared/SettingsControls";
import type { SettingsPayload } from "@/lib/types";

export function WebuiAccessSettings({ access, saving, error, onChange }: {
  access: NonNullable<SettingsPayload["webui_access"]>;
  saving: boolean;
  error: string | null;
  onChange: (allowOtherDevices: boolean) => void;
}) {
  const { t } = useTranslation();
  return (
    <section aria-label={t("settings.webuiAccess.title")}>
      <SettingsSectionTitle>{t("settings.webuiAccess.title")}</SettingsSectionTitle>
      <SettingsGroup>
        <SettingsRow
          title={t("settings.webuiAccess.allowOtherDevices")}
          description={t(access.can_change ? "settings.webuiAccess.description" : "settings.webuiAccess.managed")}
        >
          <ToggleButton
            checked={access.allow_other_devices}
            disabled={saving || !access.can_change}
            onChange={onChange}
            label={t("settings.webuiAccess.allowOtherDevices")}
            aria-describedby="webui-access-status"
          />
        </SettingsRow>
        <ReadOnlyRow title={t("settings.webuiAccess.activeHost")} value={access.active_host} />
      </SettingsGroup>
      <div id="webui-access-status" className="mt-3 space-y-2 text-[13px] leading-5 text-muted-foreground">
        <p>{t(access.active_allow_other_devices ? "settings.webuiAccess.networkActive" : "settings.webuiAccess.localActive")}</p>
        {access.requires_restart ? (
          <p role="status" className="text-foreground">
            {t(access.allow_other_devices ? "settings.webuiAccess.pendingEnable" : "settings.webuiAccess.pendingDisable")}
          </p>
        ) : null}
        <p>{t("settings.webuiAccess.networkScope")}</p>
        {error ? <p role="alert" className="text-destructive">{error}</p> : null}
      </div>
    </section>
  );
}
