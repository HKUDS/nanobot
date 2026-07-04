import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";

export type LocalDensity = "comfortable" | "compact";
export type LocalActivityMode = "auto" | "expanded";

export interface LocalPreferences {
  density: LocalDensity;
  activityMode: LocalActivityMode;
  codeWrap: boolean;
  brandLogos: boolean;
  streamingNaturalPacing: boolean;
}

export const LOCAL_PREFS_STORAGE_KEY = "nanobot-webui.settings-preferences";
export const LOCAL_PREFS_CHANGED_EVENT = "nanobot-webui.local-preferences-changed";

export const DEFAULT_LOCAL_PREFS: LocalPreferences = {
  density: "comfortable",
  activityMode: "auto",
  codeWrap: true,
  brandLogos: false,
  streamingNaturalPacing: true,
};

function normalizeLocalPreferences(value: Partial<LocalPreferences> | null | undefined): LocalPreferences {
  return {
    density: value?.density === "compact" ? "compact" : "comfortable",
    activityMode: value?.activityMode === "expanded" ? "expanded" : "auto",
    codeWrap: value?.codeWrap !== false,
    brandLogos: value?.brandLogos === true,
    streamingNaturalPacing: value?.streamingNaturalPacing !== false,
  };
}

export function readLocalPreferences(): LocalPreferences {
  if (typeof window === "undefined") return DEFAULT_LOCAL_PREFS;
  try {
    const raw = window.localStorage.getItem(LOCAL_PREFS_STORAGE_KEY);
    if (!raw) return DEFAULT_LOCAL_PREFS;
    return normalizeLocalPreferences(JSON.parse(raw) as Partial<LocalPreferences>);
  } catch {
    return DEFAULT_LOCAL_PREFS;
  }
}

export function writeLocalPreferences(preferences: LocalPreferences): void {
  if (typeof window === "undefined") return;
  const normalized = normalizeLocalPreferences(preferences);
  try {
    window.localStorage.setItem(LOCAL_PREFS_STORAGE_KEY, JSON.stringify(normalized));
  } catch {
    // Browser-only preferences should never block the UI.
  }
  window.dispatchEvent(
    new CustomEvent<LocalPreferences>(LOCAL_PREFS_CHANGED_EVENT, { detail: normalized }),
  );
}

export function useLocalPreferences(): [
  LocalPreferences,
  Dispatch<SetStateAction<LocalPreferences>>,
] {
  const [preferences, setPreferencesState] = useState<LocalPreferences>(() => readLocalPreferences());
  const preferencesRef = useRef(preferences);
  const skipNextLocalEventRef = useRef(false);

  const applyPreferences = useCallback((next: LocalPreferences) => {
    preferencesRef.current = next;
    setPreferencesState(next);
  }, []);

  useEffect(() => {
    const syncFromStorage = () => {
      applyPreferences(readLocalPreferences());
    };
    const syncFromLocalEvent = (event: Event) => {
      if (skipNextLocalEventRef.current) {
        skipNextLocalEventRef.current = false;
        return;
      }
      const detail = (event as CustomEvent<LocalPreferences>).detail;
      applyPreferences(detail ? normalizeLocalPreferences(detail) : readLocalPreferences());
    };
    const syncFromCrossTab = (event: StorageEvent) => {
      if (event.key !== null && event.key !== LOCAL_PREFS_STORAGE_KEY) return;
      syncFromStorage();
    };

    window.addEventListener("storage", syncFromCrossTab);
    window.addEventListener(LOCAL_PREFS_CHANGED_EVENT, syncFromLocalEvent);
    return () => {
      window.removeEventListener("storage", syncFromCrossTab);
      window.removeEventListener(LOCAL_PREFS_CHANGED_EVENT, syncFromLocalEvent);
    };
  }, [applyPreferences]);

  const setPreferences = useCallback<Dispatch<SetStateAction<LocalPreferences>>>((next) => {
    const current = preferencesRef.current;
    const resolved = normalizeLocalPreferences(
      typeof next === "function" ? next(current) : next,
    );
    skipNextLocalEventRef.current = true;
    applyPreferences(resolved);
    writeLocalPreferences(resolved);
  }, [applyPreferences]);

  return [preferences, setPreferences];
}

export function useStreamingNaturalPacing(enabled: boolean): boolean {
  const [naturalPacing, setNaturalPacing] = useState(() => (
    enabled ? readLocalPreferences().streamingNaturalPacing : DEFAULT_LOCAL_PREFS.streamingNaturalPacing
  ));

  useEffect(() => {
    if (!enabled) {
      setNaturalPacing(DEFAULT_LOCAL_PREFS.streamingNaturalPacing);
      return undefined;
    }

    const sync = (preferences?: Partial<LocalPreferences>) => {
      const next = preferences
        ? normalizeLocalPreferences(preferences)
        : readLocalPreferences();
      setNaturalPacing(next.streamingNaturalPacing);
    };
    const syncFromStorage = (event: StorageEvent) => {
      if (event.key !== null && event.key !== LOCAL_PREFS_STORAGE_KEY) return;
      sync();
    };
    const syncFromLocalEvent = (event: Event) => {
      sync((event as CustomEvent<LocalPreferences>).detail);
    };

    sync();
    window.addEventListener("storage", syncFromStorage);
    window.addEventListener(LOCAL_PREFS_CHANGED_EVENT, syncFromLocalEvent);
    return () => {
      window.removeEventListener("storage", syncFromStorage);
      window.removeEventListener(LOCAL_PREFS_CHANGED_EVENT, syncFromLocalEvent);
    };
  }, [enabled]);

  return naturalPacing;
}
