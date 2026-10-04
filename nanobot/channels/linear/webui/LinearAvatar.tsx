import { useState } from "react";
import { Building2 } from "lucide-react";

import { cn } from "@/lib/utils";

/** Fixed-size, display-only images. Never send admin-page referrers to the CDN. */
export function LinearAvatar({ name, url, workspace = false }: {
  name: string; url?: string | null; workspace?: boolean;
}) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  let source: string | null = null;
  try {
    const parsed = new URL(url ?? "");
    if (parsed.protocol === "https:" && !parsed.username && !parsed.password
      && (!parsed.port || parsed.port === "443")
      && ["public.linear.app", "uploads.linear.app"].includes(parsed.hostname)) {
      source = parsed.href;
    }
  } catch { /* Missing or malformed images use the same fallback. */ }
  const size = workspace ? 28 : 32;
  const showImage = source !== null && source !== failedUrl;
  return <span aria-hidden className={cn(
    "relative flex shrink-0 items-center justify-center text-xs font-medium text-muted-foreground",
    workspace ? "h-7 w-7" : "h-8 w-8 overflow-hidden rounded-full bg-muted",
    workspace && !showImage && "rounded-md bg-muted",
  )}>
    {workspace ? !showImage ? <Building2 className="h-4 w-4" /> : null : name.slice(0, 2).toLocaleUpperCase()}
    {source && showImage ? <img src={source} alt="" width={size} height={size}
      loading="lazy" decoding="async" referrerPolicy="no-referrer"
      className={cn("absolute inset-0 h-full w-full", workspace ? "object-contain" : "bg-muted object-cover")}
      onError={() => setFailedUrl(source)} /> : null}
  </span>;
}
