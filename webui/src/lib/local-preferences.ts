export type LocalDensity = "comfortable" | "compact";
export type LocalActivityMode = "auto" | "expanded";
export type FileEditDisplayMode = "summary" | "diff" | "collapsed_diff";

export interface LocalPreferences {
  density: LocalDensity;
  activityMode: LocalActivityMode;
  codeWrap: boolean;
  brandLogos: boolean;
  browserNotifications: boolean;
  fileEditDisplayMode: FileEditDisplayMode;
}

export const LOCAL_PREFS_STORAGE_KEY = "nanobot-webui.settings-preferences";
export const LOCAL_PREFS_CHANGED_EVENT = "nanobot-webui.local-preferences-changed";
const LOCAL_PREFS_SCHEMA_VERSION = 1;

type PersistedLocalPreferences = Partial<LocalPreferences> & {
  schemaVersion?: number;
};

export const DEFAULT_LOCAL_PREFS: LocalPreferences = {
  density: "comfortable",
  activityMode: "auto",
  codeWrap: true,
  brandLogos: true,
  browserNotifications: false,
  fileEditDisplayMode: "summary",
};

export function normalizeFileEditDisplayMode(value: unknown): FileEditDisplayMode {
  return value === "diff" || value === "collapsed_diff" ? value : "summary";
}

export function readLocalPreferences(): LocalPreferences {
  try {
    const raw = window.localStorage.getItem(LOCAL_PREFS_STORAGE_KEY);
    if (!raw) return DEFAULT_LOCAL_PREFS;
    const parsed = JSON.parse(raw) as PersistedLocalPreferences;
    return {
      density: parsed.density === "compact" ? "compact" : "comfortable",
      activityMode: parsed.activityMode === "expanded" ? "expanded" : "auto",
      codeWrap: parsed.codeWrap !== false,
      brandLogos: parsed.schemaVersion === LOCAL_PREFS_SCHEMA_VERSION
        ? parsed.brandLogos !== false
        : true,
      browserNotifications: parsed.browserNotifications === true,
      fileEditDisplayMode: normalizeFileEditDisplayMode(parsed.fileEditDisplayMode),
    };
  } catch {
    return DEFAULT_LOCAL_PREFS;
  }
}

export function writeLocalPreferences(preferences: LocalPreferences): void {
  try {
    window.localStorage.setItem(LOCAL_PREFS_STORAGE_KEY, JSON.stringify({
      schemaVersion: LOCAL_PREFS_SCHEMA_VERSION,
      ...preferences,
    }));
  } catch {
    // Browser-only preferences should never block settings.
  }
  window.dispatchEvent(new CustomEvent<LocalPreferences>(
    LOCAL_PREFS_CHANGED_EVENT,
    { detail: preferences },
  ));
}
