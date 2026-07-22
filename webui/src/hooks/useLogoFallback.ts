import { useCallback, useEffect, useMemo, useState } from "react";

const loadedLogoUrls = new Set<string>();
const failedLogoUrls = new Set<string>();
const resolvedLogoIndexByKey = new Map<string, number>();

function logoCacheKey(urls: readonly string[]): string {
  return urls.join("\n");
}

function logoUrlsFromKey(key: string): string[] {
  return key ? key.split("\n") : [];
}

function firstUsableLogoIndex(urls: readonly string[]): number {
  const key = logoCacheKey(urls);
  const cachedIndex = resolvedLogoIndexByKey.get(key);
  if (
    typeof cachedIndex === "number" &&
    cachedIndex >= 0 &&
    cachedIndex < urls.length &&
    !failedLogoUrls.has(urls[cachedIndex])
  ) {
    return cachedIndex;
  }

  const loadedIndex = urls.findIndex((url) => loadedLogoUrls.has(url));
  if (loadedIndex >= 0) {
    resolvedLogoIndexByKey.set(key, loadedIndex);
    return loadedIndex;
  }

  const firstUnfailedIndex = urls.findIndex((url) => !failedLogoUrls.has(url));
  if (firstUnfailedIndex >= 0) return firstUnfailedIndex;
  return -1;
}

function nextLogoIndex(urls: readonly string[], afterIndex: number): number {
  for (let index = afterIndex + 1; index < urls.length; index += 1) {
    if (!failedLogoUrls.has(urls[index])) return index;
  }
  return -1;
}

export function useLogoFallback(urls: readonly string[] | undefined) {
  const cacheKey = useMemo(() => logoCacheKey(urls?.filter(Boolean) ?? []), [urls]);
  const safeUrls = useMemo(() => logoUrlsFromKey(cacheKey), [cacheKey]);
  const [logoIndex, setLogoIndex] = useState(() => firstUsableLogoIndex(safeUrls));
  const logoUrl = logoIndex >= 0 ? safeUrls[logoIndex] : undefined;

  useEffect(() => {
    setLogoIndex(firstUsableLogoIndex(safeUrls));
  }, [cacheKey, safeUrls]);

  const onLogoLoad = useCallback(() => {
    if (!logoUrl || logoIndex < 0) return;
    loadedLogoUrls.add(logoUrl);
    failedLogoUrls.delete(logoUrl);
    resolvedLogoIndexByKey.set(cacheKey, logoIndex);
  }, [cacheKey, logoIndex, logoUrl]);

  const onLogoError = useCallback(() => {
    if (!logoUrl || logoIndex < 0) return;
    failedLogoUrls.add(logoUrl);
    if (resolvedLogoIndexByKey.get(cacheKey) === logoIndex) {
      resolvedLogoIndexByKey.delete(cacheKey);
    }
    setLogoIndex(nextLogoIndex(safeUrls, logoIndex));
  }, [cacheKey, logoIndex, logoUrl, safeUrls]);

  return { logoUrl, onLogoLoad, onLogoError };
}

export function __clearLogoFallbackCacheForTests(): void {
  loadedLogoUrls.clear();
  failedLogoUrls.clear();
  resolvedLogoIndexByKey.clear();
}
