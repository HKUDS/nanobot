import { useEffect, useState } from "react";

import {
  LOCAL_PREFS_CHANGED_EVENT,
  readLocalPreferences,
  type LocalPreferences,
} from "@/lib/local-preferences";

export function useShowTurnUsage(): boolean {
  const [showTurnUsage, setShowTurnUsage] = useState(
    () => readLocalPreferences().showTurnUsage,
  );

  useEffect(() => {
    const refresh = () => setShowTurnUsage(readLocalPreferences().showTurnUsage);
    const refreshFromLocalPreferenceEvent = (event: Event) => {
      const detail = (event as CustomEvent<Partial<LocalPreferences> | undefined>).detail;
      setShowTurnUsage(
        detail ? detail.showTurnUsage === true : readLocalPreferences().showTurnUsage,
      );
    };
    window.addEventListener("storage", refresh);
    window.addEventListener("focus", refresh);
    window.addEventListener(LOCAL_PREFS_CHANGED_EVENT, refreshFromLocalPreferenceEvent);
    return () => {
      window.removeEventListener("storage", refresh);
      window.removeEventListener("focus", refresh);
      window.removeEventListener(LOCAL_PREFS_CHANGED_EVENT, refreshFromLocalPreferenceEvent);
    };
  }, []);

  return showTurnUsage;
}
