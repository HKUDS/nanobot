import { useLayoutEffect } from "react";

import { useLocalPreferences } from "@/hooks/useLocalPreferences";

/** Project browser preferences onto text tokens, without scaling the UI or rem. */
export function useReadingTypography(): void {
  const { readingTextSize } = useLocalPreferences();
  useLayoutEffect(() => {
    document.documentElement.dataset.readingTextSize = readingTextSize;
  }, [readingTextSize]);
}
