import { Globe2 } from "lucide-react";
import { useMemo } from "react";

import { ActivityStep, type ActivityStepTone } from "@/components/thread/activity/ActivityStep";
import { useLogoFallback } from "@/hooks/useLogoFallback";
import { browserSafeFaviconUrls } from "@/lib/provider-brand";

interface WebActivityRowProps {
  title: string;
  href: string;
  host: string;
  displayUrl: string;
  active?: boolean;
  tone?: ActivityStepTone;
}

export function WebActivityRow({
  title,
  href,
  host,
  displayUrl,
  active = false,
  tone = active ? "active" : "neutral",
}: WebActivityRowProps) {
  return (
    <ActivityStep
      marker={<WebFavicon host={host} active={active} />}
      active={active}
      tone={tone}
      label={(
        <a
          href={href}
          target="_blank"
          rel="noreferrer noopener"
          aria-label={`${title} · ${displayUrl}`}
          className="flex min-w-0 items-center gap-2 overflow-hidden text-foreground/82 hover:text-foreground"
        >
          <span className="min-w-0 truncate font-medium">{title}</span>
          <span
            className="max-w-[9rem] shrink truncate rounded-full bg-muted/65 px-2 py-0.5 font-mono text-[10px] leading-4 text-muted-foreground/72 sm:max-w-[18rem]"
            data-testid="activity-web-url"
          >
            {displayUrl}
          </span>
        </a>
      )}
      contentClassName="overflow-hidden"
    />
  );
}

function WebFavicon({ host, active }: { host: string; active: boolean }) {
  const candidates = useMemo(() => browserSafeFaviconUrls(host), [host]);
  const { logoUrl, onLogoError, onLogoLoad } = useLogoFallback(candidates);

  if (!logoUrl) {
    return <Globe2 className="h-4 w-4 shrink-0 text-muted-foreground/52" aria-hidden />;
  }

  return (
    <img
      src={logoUrl}
      alt=""
      className={`h-4 w-4 shrink-0 rounded-[3px] object-contain${active ? " animate-pulse" : ""}`}
      decoding="async"
      loading="lazy"
      referrerPolicy="no-referrer"
      draggable={false}
      onLoad={onLogoLoad}
      onError={onLogoError}
      data-testid={`activity-web-favicon-${host}`}
    />
  );
}
