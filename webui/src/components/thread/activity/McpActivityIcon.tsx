import { useContext, useMemo, useReducer } from "react";

import { McpIcon } from "@/components/icons/product-icons";
import { McpCatalogContext } from "@/hooks/useMcpPresetCatalog";
import { useThemeValue } from "@/hooks/useTheme";
import type { McpServerIcon } from "@/lib/types";

// Image bytes stay in the browser's HTTP cache. Only remember broken candidates,
// briefly, so opening the same trace in another row doesn't request them again.
const failedByCatalog = new WeakMap<object, Map<string, number>>();
const standalone = {};
const FAILURE_TTL_MS = 60_000;
const MAX_FAILURES = 128;

function iconSizeRank(sizes: string[] | undefined, pixels: number) {
  if (!sizes?.length || sizes.includes("any")) return 0;
  let rank = Infinity;
  for (const size of sizes ?? []) {
    const match = /^(\d+)x(\d+)$/.exec(size);
    if (!match) continue;
    const side = Math.min(Number(match[1]), Number(match[2]));
    // Prefer the closest size that won't need to be upscaled.
    rank = Math.min(rank, side >= pixels ? side - pixels : 100_000 + pixels - side);
  }
  return rank;
}

export function McpActivityIcon({ name, icons }: { name: string; icons?: McpServerIcon[] }) {
  const scope = useContext(McpCatalogContext) ?? standalone;
  const theme = useThemeValue();
  const [, advance] = useReducer(n => n + 1, 0);
  const candidates = useMemo(() => {
    const pixels = 16 * (window.devicePixelRatio || 1);
    return (icons ?? []).filter(icon => (!icon.theme || icon.theme === theme)
      && /^(?:https:\/\/|data:image\/(?:png|jpe?g|gif|webp);base64,)/i.test(icon.src))
      .sort((a, b) => Number(b.theme === theme) - Number(a.theme === theme)
        || iconSizeRank(a.sizes, pixels) - iconSizeRank(b.sizes, pixels));
  }, [icons, theme]);
  const failures = failedByCatalog.get(scope);
  const src = candidates.find(icon => (failures?.get(icon.src) ?? 0) <= Date.now())?.src;
  const onError = () => {
    if (!src) return;
    const failed = failedByCatalog.get(scope) ?? new Map<string, number>();
    failed.delete(src);
    failed.set(src, Date.now() + FAILURE_TTL_MS);
    if (failed.size > MAX_FAILURES) failed.delete(failed.keys().next().value!);
    failedByCatalog.set(scope, failed);
    advance();
  };
  return (
    <span data-testid={`activity-mcp-logo-${name}`} className="grid h-4 w-4 shrink-0 place-items-center text-muted-foreground" aria-hidden>
      {src ? <img key={src} src={src} alt="" decoding="async" referrerPolicy="no-referrer" onError={onError}
        className="h-full w-full object-contain" /> : <McpIcon className="h-3.5 w-3.5" />}
    </span>
  );
}
