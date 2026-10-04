import type { WebUIExtensionSummary } from "@/lib/types";
import { fetchWithTimeout } from "@/lib/http";

const API_READ_TIMEOUT_MS = 20_000;

/** Read one extension's manifest metadata from the gateway. */
export async function fetchExtension(
  token: string,
  extensionId: string,
  base: string = "",
): Promise<WebUIExtensionSummary | null> {
  const res = await fetchWithTimeout(
    `${base}/api/extensions/${encodeURIComponent(extensionId)}`,
    {
      headers: { Authorization: `Bearer ${token}` },
      credentials: "same-origin",
      cache: "no-store",
    },
    API_READ_TIMEOUT_MS,
  );
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as WebUIExtensionSummary;
}

/** Absolute URL for one extension's static entry asset. */
export function extensionAssetUrl(
  extensionId: string,
  entry: string,
  base: string = "",
): string {
  const clean = entry.replace(/^\.?\//, "");
  return `${base}/extensions/${encodeURIComponent(extensionId)}/${clean}`;
}
