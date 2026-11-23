import { useEffect, useMemo, useSyncExternalStore } from "react";

import { getProviderModelCatalog, isCatalogAvailable } from "@/lib/provider-model-catalog";

export function useProviderModelCatalog({ revision, token, provider, enabled }: {
  revision: object;
  token: string;
  provider: string;
  enabled: boolean;
}) {
  const catalog = useMemo(
    () => getProviderModelCatalog(revision, token, provider),
    [revision, token, provider],
  );
  const snapshot = useSyncExternalStore(catalog.subscribe, catalog.getSnapshot, catalog.getSnapshot);

  useEffect(() => {
    // The gateway owns freshness TTLs. Each opening revalidates there without
    // hiding the current list, and closing does not discard a pending result.
    if (enabled) void catalog.load();
  }, [catalog, enabled]);

  const needsSignIn = snapshot.payload?.error_kind === "auth_required";
  const available = isCatalogAvailable(snapshot.payload);
  return {
    payload: snapshot.payload,
    needsSignIn,
    failed: snapshot.failed,
    refreshing: snapshot.pending,
    loading: enabled && !available && !needsSignIn
      && (snapshot.pending || (!snapshot.payload && !snapshot.failed)),
    retry: () => catalog.load(true),
  };
}
