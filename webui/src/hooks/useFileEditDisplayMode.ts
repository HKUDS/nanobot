import { useLocalPreferences } from "@/hooks/useLocalPreferences";
import type { FileEditDisplayMode } from "@/lib/local-preferences";

export function useFileEditDisplayMode(): FileEditDisplayMode {
  return useLocalPreferences().fileEditDisplayMode;
}
