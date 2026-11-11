import type { Dispatch, SetStateAction } from "react";
import { useTranslation } from "react-i18next";

import { AppearanceSettingsView } from "@/components/settings/overview/AppearanceSettingsView";
import { useReadingTypography } from "@/hooks/useReadingTypography";
import { useLocalPreferences } from "@/hooks/useLocalPreferences";
import { ThemeProvider, useTheme } from "@/hooks/useTheme";
import { readLocalPreferences, writeLocalPreferences, type LocalPreferences } from "@/lib/local-preferences";

export function AppearanceFixture() {
  const { t } = useTranslation();
  const { theme, preference, setTheme } = useTheme();
  const preferences = useLocalPreferences();
  const setPreferences: Dispatch<SetStateAction<LocalPreferences>> = (update) => {
    writeLocalPreferences(typeof update === "function" ? update(readLocalPreferences()) : update);
  };
  useReadingTypography();
  return <ThemeProvider theme={theme}>
    <main className="h-full overflow-y-auto bg-background" data-appearance-fixture>
      <header className="flex items-center gap-2 text-caption text-muted-foreground" style={{ maxWidth: 800, margin: "0 auto", padding: "28px 32px" }}>
        <img src="/brand/nanobot_mark.svg" className="h-5 w-5" alt="" />
        <span className="font-medium text-foreground">nanobot</span><span aria-hidden>/</span><span>{t("settings.nav.appearance")}</span>
      </header>
      <div style={{ containerType: "inline-size", maxWidth: 800, margin: "0 auto", padding: "0 16px 64px" }}>
        <div className="settings-grid" style={{ margin: 0, width: "100%", maxWidth: "none" }}>
          <h1 className="font-semibold tracking-tight" style={{ fontSize: 28, marginBottom: 20, paddingInline: "var(--settings-inset, 16px)" }}>{t("settings.nav.appearance")}</h1>
          <AppearanceSettingsView themePreference={preference} onChangeTheme={setTheme}
            localPrefs={preferences} onChangeLocalPrefs={setPreferences} />
        </div>
      </div>
    </main>
  </ThemeProvider>;
}
