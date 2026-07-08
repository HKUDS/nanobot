export type LocalDensity = "comfortable" | "compact";
export type LocalActivityMode = "auto" | "expanded";
export type FileEditDisplayMode = "summary" | "diff" | "collapsed_diff";

export interface LocalPreferences {
  density: LocalDensity;
  activityMode: LocalActivityMode;
  codeWrap: boolean;
  brandLogos: boolean;
  fileEditDisplayMode: FileEditDisplayMode;
}

export const LOCAL_PREFS_STORAGE_KEY = "nanobot-webui.settings-preferences";

export const DEFAULT_LOCAL_PREFS: LocalPreferences = {
  density: "comfortable",
  activityMode: "auto",
  codeWrap: true,
  brandLogos: false,
  fileEditDisplayMode: "summary",
};

export function normalizeFileEditDisplayMode(value: unknown): FileEditDisplayMode {
  return value === "diff" || value === "collapsed_diff" ? value : "summary";
}

export function readLocalPreferences(): LocalPreferences {
  try {
    const raw = window.localStorage.getItem(LOCAL_PREFS_STORAGE_KEY);
    if (!raw) return DEFAULT_LOCAL_PREFS;
    const parsed = JSON.parse(raw) as Partial<LocalPreferences>;
    return {
      density: parsed.density === "compact" ? "compact" : "comfortable",
      activityMode: parsed.activityMode === "expanded" ? "expanded" : "auto",
      codeWrap: parsed.codeWrap !== false,
      brandLogos: parsed.brandLogos === true,
      fileEditDisplayMode: normalizeFileEditDisplayMode(parsed.fileEditDisplayMode),
    };
  } catch {
    return DEFAULT_LOCAL_PREFS;
  }
}
