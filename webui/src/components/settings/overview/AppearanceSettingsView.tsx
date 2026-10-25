import { useId, type Dispatch, type SetStateAction } from "react";
import { Check, Monitor, Moon, Sun } from "lucide-react";
import { useTranslation } from "react-i18next";

import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { SettingsGroup, SettingsRow, SettingsSectionTitle } from "@/components/settings/shared/SettingsControls";
import { ToggleButton } from "@/components/ui/toggle-button";
import { SegmentedControl } from "@/components/ui/segmented-control";
import type { ThemePreference } from "@/hooks/useTheme";
import type { FileEditDisplayMode, LocalActivityMode, LocalPreferences } from "@/lib/local-preferences";
import { ReadingSettings } from "./ReadingSettings";
import "./appearance-settings.css";

export function AppearanceSettingsView({ themePreference, onChangeTheme, localPrefs, onChangeLocalPrefs }: {
  themePreference: ThemePreference;
  onChangeTheme: (preference: ThemePreference) => void;
  localPrefs: LocalPreferences;
  onChangeLocalPrefs: Dispatch<SetStateAction<LocalPreferences>>;
}) {
  const { t } = useTranslation();
  const themeId = useId();
  const themes = [
    { value: "system", label: t("settings.appearance.system"), icon: Monitor },
    { value: "light", label: t("settings.values.light"), icon: Sun },
    { value: "dark", label: t("settings.values.dark"), icon: Moon },
  ] as const;
  const editHelp = { summary: "summaryHelp", diff: "diffHelp", collapsed_diff: "collapsedHelp" } as const;

  return <div className="settings-stack appearance-page">
    <section>
      <SettingsSectionTitle>{t("settings.rows.theme")}</SettingsSectionTitle>
      <fieldset>
        <legend className="sr-only">{t("settings.rows.theme")}</legend>
        <div className="appearance-theme-grid">
          {themes.map(({ value, label, icon: Icon }) => <label key={value} className="appearance-theme-option">
            <input className="appearance-theme-input" type="radio" name={themeId} value={value}
              checked={themePreference === value} onChange={() => onChangeTheme(value)} />
            <span className="appearance-theme-card">
              <span className="appearance-theme-miniature" data-mode={value} aria-hidden>
                <span className="appearance-mini-sidebar"><span /><span /><span /></span>
                <span className="appearance-mini-main"><span /><span /><span /><span /></span>
              </span>
              <span className="appearance-theme-label text-ui-label">
                <span className="flex min-w-0 items-center gap-1.5"><Icon className="h-3.5 w-3.5 shrink-0" aria-hidden /><span>{label}</span></span>
                <Check className="appearance-theme-check h-3.5 w-3.5 shrink-0" aria-hidden />
              </span>
            </span>
          </label>)}
        </div>
      </fieldset>
    </section>

    <section>
      <SettingsSectionTitle>{t("settings.appearance.reading")}</SettingsSectionTitle>
      <ReadingSettings preferences={localPrefs} onChange={onChangeLocalPrefs} />
      <div className="mt-2">
        <SettingsGroup>
          <SettingsRow title={t("settings.rows.codeWrap")} description={t("settings.help.codeWrap")}>
            <ToggleButton checked={localPrefs.codeWrap}
              onChange={(codeWrap) => onChangeLocalPrefs((previous) => ({ ...previous, codeWrap }))}
              ariaLabel={t("settings.rows.codeWrap")}
              label={t(localPrefs.codeWrap ? "settings.values.on" : "settings.values.off")} />
          </SettingsRow>
        </SettingsGroup>
      </div>
    </section>

    <section>
      <SettingsSectionTitle>{t("settings.appearance.process")}</SettingsSectionTitle>
      <p className="appearance-setting-help">{t("settings.appearance.processHelp")}</p>
      <SettingsGroup>
        <SettingsRow title={t("settings.rows.activityMode")}>
          <SegmentedControl<LocalActivityMode> value={localPrefs.activityMode}
            ariaLabel={t("settings.rows.activityMode")}
            options={[{ value: "auto", label: t("settings.values.auto") }, { value: "expanded", label: t("settings.values.expanded") }]}
            onChange={(activityMode) => onChangeLocalPrefs((previous) => ({ ...previous, activityMode }))} />
        </SettingsRow>
        <p className="appearance-setting-help">{t(`settings.appearance.${localPrefs.activityMode === "auto" ? "autoHelp" : "expandedHelp"}`)}</p>
        <div className="settings-group-divider">
          <SettingsRow title={t("settings.rows.fileEditDisplay")}>
            <SegmentedControl<FileEditDisplayMode> value={localPrefs.fileEditDisplayMode}
              ariaLabel={t("settings.rows.fileEditDisplay")}
              options={[
                { value: "summary", label: t("settings.values.summary") },
                { value: "diff", label: t("settings.values.diff") },
                { value: "collapsed_diff", label: t("settings.values.collapsedDiff") },
              ]}
              onChange={(fileEditDisplayMode) => onChangeLocalPrefs((previous) => ({ ...previous, fileEditDisplayMode }))} />
          </SettingsRow>
          <p className="appearance-setting-help">{t(`settings.appearance.${editHelp[localPrefs.fileEditDisplayMode]}`)}</p>
        </div>
      </SettingsGroup>
    </section>

    <section>
      <SettingsSectionTitle>{t("settings.sections.interface")}</SettingsSectionTitle>
      <SettingsGroup>
        <SettingsRow title={t("settings.rows.language")}><LanguageSwitcher /></SettingsRow>
        <SettingsRow title={t("settings.rows.brandLogos")} description={t("settings.legal.thirdPartyBrands")}>
          <ToggleButton checked={localPrefs.brandLogos}
            onChange={(brandLogos) => onChangeLocalPrefs((previous) => ({ ...previous, brandLogos }))}
            ariaLabel={t("settings.rows.brandLogos")}
            label={t(localPrefs.brandLogos ? "settings.values.on" : "settings.values.off")} />
        </SettingsRow>
      </SettingsGroup>
    </section>
  </div>;
}
