import { consumeUrlBootstrapSecret, fetchBootstrap, loadSavedSecret } from "./bootstrap";

export async function requestBootstrap(secret = consumeUrlBootstrapSecret() || loadSavedSecret()) {
  const boot = await fetchBootstrap("", secret);
  // The document can receive the token well before React mounts. Do not extend its TTL.
  const tokenExpiresAt = boot.expires_in ? Date.now() + Math.max(0, boot.expires_in) * 1000 : null;
  return { boot, secret, tokenExpiresAt };
}

export type BootstrapRequest = ReturnType<typeof requestBootstrap>;

/** Hand this document's request to its App, not to a global or persistent cache. */
export function preloadInitialBootstrap() {
  let pending: BootstrapRequest | undefined = requestBootstrap();
  // A fast 401 (or timeout) may arrive before the UI imports. App handles the original rejection.
  void pending.catch(() => {});
  return () => {
    const request = pending;
    pending = undefined;
    return request;
  };
}
