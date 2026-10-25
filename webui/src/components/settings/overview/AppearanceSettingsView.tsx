import type { Dispatch, SetStateAction } from "react";
import { useTranslation } from "react-i18next";

import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { SettingsGroup, SettingsRow, SettingsSectionTitle } from "@/components/settings/shared/SettingsControls";
import { ToggleButton } from "@/components/ui/toggle-button";
import { SegmentedControl } from "@/components/ui/segmented-control";
import type { FileEditDisplayMode, LocalActivityMode, LocalPreferences } from "@/lib/local-preferences";

export function AppearanceSettingsView({
  theme,
  onToggleTheme,
  localPrefs,
  onChangeLocalPrefs,
}: {
  theme: "light" | "dark";
  onToggleTheme: () => void;
  localPrefs: LocalPreferences;
  onChangeLocalPrefs: Dispatch<SetStateAction<LocalPreferences>>;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  return (
    <div className="settings-stack">
      <section>
        <SettingsSectionTitle>{t("settings.sections.interface")}</SettingsSectionTitle>
        <SettingsGroup>
          <SettingsRow title={t("settings.rows.theme")}>
            <SegmentedControl
              value={theme}
              ariaLabel={t("settings.rows.theme")}
              className="bg-muted p-0.5"
              itemClassName="px-3"
              options={[
                { value: "light", label: t("settings.values.light") },
                { value: "dark", label: t("settings.values.dark") },
              ]}
              onChange={(nextTheme) => {
                if (nextTheme !== theme) onToggleTheme();
              }}
            />
          </SettingsRow>

          <SettingsRow title={t("settings.rows.language")}>
            <LanguageSwitcher />
          </SettingsRow>
        </SettingsGroup>
      </section>

      <section>
        <SettingsSectionTitle>{tx("settings.sections.localPreferences", "Local preferences")}</SettingsSectionTitle>
        <SettingsGroup>
          <SettingsRow title={t("settings.rows.readingTextSize")}>
            <SegmentedControl
              value={localPrefs.readingTextSize}
              mode="radio"
              ariaLabel={t("settings.rows.readingTextSize")}
              className="w-36 [@media(pointer:coarse)]:w-40"
              itemClassName="flex flex-1 basis-0 items-center justify-center !overflow-visible px-0 after:absolute after:inset-x-0 after:top-1/2 after:h-11 after:-translate-y-1/2 after:content-['']"
              options={([
                ["small", "text-[12px]"],
                ["standard", "text-[16px]"],
                ["large", "text-[20px]"],
              ] as const).map(([value, size]) => ({
                value,
                label: <span aria-hidden className={size}>A</span>,
                ariaLabel: t(`settings.readingTextSize.${value}`),
                tooltip: t(`settings.readingTextSize.${value}`),
              }))}
              onChange={(readingTextSize) =>
                onChangeLocalPrefs((prev) => ({ ...prev, readingTextSize }))
              }
            />
          </SettingsRow>
          <SettingsRow title={tx("settings.rows.activityMode", "Activity detail")}>
            <SegmentedControl
              value={localPrefs.activityMode}
              options={[
                { value: "auto", label: tx("settings.values.auto", "Auto") },
                { value: "expanded", label: tx("settings.values.expanded", "Expanded") },
              ]}
              onChange={(activityMode) =>
                onChangeLocalPrefs((prev) => ({ ...prev, activityMode: activityMode as LocalActivityMode }))
              }
            />
          </SettingsRow>
          <SettingsRow title={tx("settings.rows.fileEditDisplay", "File edit display")}>
            <SegmentedControl
              value={localPrefs.fileEditDisplayMode}
              options={[
                { value: "summary", label: tx("settings.values.summary", "Summary") },
                { value: "diff", label: tx("settings.values.diff", "Diff") },
                { value: "collapsed_diff", label: tx("settings.values.collapsedDiff", "Collapsed diff") },
              ]}
              onChange={(fileEditDisplayMode) =>
                onChangeLocalPrefs((prev) => ({
                  ...prev,
                  fileEditDisplayMode: fileEditDisplayMode as FileEditDisplayMode,
                }))
              }
            />
          </SettingsRow>
          <SettingsRow title={tx("settings.rows.codeWrap", "Code wrapping")}>
            <ToggleButton
              checked={localPrefs.codeWrap}
              onChange={(codeWrap) => onChangeLocalPrefs((prev) => ({ ...prev, codeWrap }))}
              ariaLabel={tx("settings.rows.codeWrap", "Code wrapping")}
              label={localPrefs.codeWrap ? tx("settings.values.on", "On") : tx("settings.values.off", "Off")}
            />
          </SettingsRow>
          <SettingsRow
            title={tx("settings.rows.brandLogos", "Brand logos")}
            description={tx(
              "settings.legal.thirdPartyBrands",
              "Product names, logos, and brands are property of their respective owners. Use is for identification only and does not imply endorsement.",
            )}
          >
            <ToggleButton
              checked={localPrefs.brandLogos}
              onChange={(brandLogos) => onChangeLocalPrefs((prev) => ({ ...prev, brandLogos }))}
              ariaLabel={tx("settings.rows.brandLogos", "Brand logos")}
              label={localPrefs.brandLogos ? tx("settings.values.on", "On") : tx("settings.values.off", "Off")}
            />
          </SettingsRow>
        </SettingsGroup>
      </section>
    </div>
  );
}
