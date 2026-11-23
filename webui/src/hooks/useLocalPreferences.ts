import { useEffect, useState } from "react";

import {
  LOCAL_PREFS_CHANGED_EVENT,
  readLocalPreferences,
  type LocalPreferences,
} from "@/lib/local-preferences";

export function useLocalPreferences(): LocalPreferences {
  const [preferences, setPreferences] = useState(readLocalPreferences);

  useEffect(() => {
    const refresh = () => setPreferences(readLocalPreferences());
    const refreshFromEvent = (event: Event) => {
      const detail = (event as CustomEvent<LocalPreferences | undefined>).detail;
      setPreferences(detail ?? readLocalPreferences());
    };
    window.addEventListener("storage", refresh);
    window.addEventListener("focus", refresh);
    window.addEventListener(LOCAL_PREFS_CHANGED_EVENT, refreshFromEvent);
    return () => {
      window.removeEventListener("storage", refresh);
      window.removeEventListener("focus", refresh);
      window.removeEventListener(LOCAL_PREFS_CHANGED_EVENT, refreshFromEvent);
    };
  }, []);

  return preferences;
}
