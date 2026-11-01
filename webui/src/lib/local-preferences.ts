export type LocalActivityMode = "auto" | "expanded";
export type ReadingTextSize = "small" | "standard" | "large" | "custom";
export const MIN_READING_SIZE = 14;
export const MAX_READING_SIZE = 28;
export type FileEditDisplayMode = "summary" | "diff" | "collapsed_diff";

export interface LocalPreferences {
  activityMode: LocalActivityMode;
  readingTextSize: ReadingTextSize;
  customReadingTextSize: number;
  codeWrap: boolean;
  brandLogos: boolean;
  browserNotifications: boolean;
  notificationSound: boolean;
  fileEditDisplayMode: FileEditDisplayMode;
}

export const LOCAL_PREFS_STORAGE_KEY = "nanobot-webui.settings-preferences";
export const LOCAL_PREFS_CHANGED_EVENT = "nanobot-webui.local-preferences-changed";
const LOCAL_PREFS_SCHEMA_VERSION = 1;

type PersistedLocalPreferences = Partial<LocalPreferences> & {
  schemaVersion?: number;
};

export const DEFAULT_LOCAL_PREFS: LocalPreferences = {
  activityMode: "auto",
  readingTextSize: "standard",
  customReadingTextSize: 18,
  codeWrap: true,
  brandLogos: true,
  browserNotifications: false,
  notificationSound: false,
  fileEditDisplayMode: "summary",
};

function normalizeFileEditDisplayMode(value: unknown): FileEditDisplayMode {
  return value === "diff" || value === "collapsed_diff" ? value : "summary";
}

export function readLocalPreferences(): LocalPreferences {
  try {
    const raw = window.localStorage.getItem(LOCAL_PREFS_STORAGE_KEY);
    if (!raw) return DEFAULT_LOCAL_PREFS;
    const parsed = JSON.parse(raw) as PersistedLocalPreferences;
    return {
      activityMode: parsed.activityMode === "expanded" ? "expanded" : "auto",
      readingTextSize: parsed.readingTextSize === "small" || parsed.readingTextSize === "large" || parsed.readingTextSize === "custom"
        ? parsed.readingTextSize : "standard",
      customReadingTextSize: typeof parsed.customReadingTextSize === "number" && Number.isFinite(parsed.customReadingTextSize)
        ? Math.min(MAX_READING_SIZE, Math.max(MIN_READING_SIZE, Math.round(parsed.customReadingTextSize)))
        : DEFAULT_LOCAL_PREFS.customReadingTextSize,
      codeWrap: parsed.codeWrap !== false,
      brandLogos: parsed.schemaVersion === LOCAL_PREFS_SCHEMA_VERSION
        ? parsed.brandLogos !== false
        : true,
      browserNotifications: parsed.browserNotifications === true,
      notificationSound: parsed.notificationSound === true,
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
