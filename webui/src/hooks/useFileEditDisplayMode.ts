import { useEffect, useState } from "react";

import { readLocalPreferences, type FileEditDisplayMode } from "@/lib/local-preferences";

export function useFileEditDisplayMode(): FileEditDisplayMode {
  const [mode, setMode] = useState<FileEditDisplayMode>(() =>
    readLocalPreferences().fileEditDisplayMode,
  );

  useEffect(() => {
    const refresh = () => setMode(readLocalPreferences().fileEditDisplayMode);
    window.addEventListener("storage", refresh);
    window.addEventListener("focus", refresh);
    return () => {
      window.removeEventListener("storage", refresh);
      window.removeEventListener("focus", refresh);
    };
  }, []);

  return mode;
}
