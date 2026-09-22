import { useState } from "react";
import { ArrowRightLeft, Hexagon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useLogoFallback } from "@/hooks/useLogoFallback";
import { providerBrand } from "@/lib/provider-brand";
import type { ResponseSource } from "@/lib/types";
import { cn } from "@/lib/utils";

/** A persisted invocation identity; deliberately independent of live settings. */
export function ResponseSourceBadge({
  source,
  className,
}: {
  source: ResponseSource;
  className?: string;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const description = t("message.fallbackResponse", { preset: source.preset });
  const brand = providerBrand(source.provider);
  const { logoUrl, logoLoaded, onLogoLoad, onLogoError } = useLogoFallback(brand?.logoUrls);
  const tile = brand?.logoLayout === "tile" && logoUrl === brand.logoUrl;
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Tooltip open={open ? false : undefined}>
        <TooltipTrigger asChild>
          <PopoverTrigger asChild>
            <button type="button" aria-label={description} className={cn(
              "touch-target inline-flex min-h-8 min-w-0 max-w-full items-center gap-1.5 rounded-control px-1.5 text-xs",
              "transition-colors hover:bg-muted/55 hover:text-foreground",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              className,
            )}>
              <ArrowRightLeft aria-hidden className="size-3 shrink-0 opacity-70" />
              <span aria-hidden className={cn(
                "relative grid size-4 shrink-0 place-items-center overflow-hidden rounded-[4px]",
                logoLoaded && !tile ? "bg-white" : "bg-transparent",
              )}>
                {logoUrl ? <img src={logoUrl} alt="" loading="lazy" decoding="async" referrerPolicy="no-referrer"
                  onLoad={onLogoLoad} onError={onLogoError}
                  className={cn("object-contain", tile ? "size-4" : "size-3", !logoLoaded && "opacity-0")} /> : null}
                {!logoLoaded ? <Hexagon className="absolute size-3.5" /> : null}
              </span>
              <span className="min-w-0 max-w-48 truncate">{source.preset}</span>
            </button>
          </PopoverTrigger>
        </TooltipTrigger>
        <TooltipContent side="top" align="end" className="max-w-[min(18rem,calc(100vw-2rem))] break-words">
          {description}
        </TooltipContent>
      </Tooltip>
      <PopoverContent side="top" align="end" aria-label={description}
        onOpenAutoFocus={(event) => event.preventDefault()}
        className="max-w-[min(18rem,calc(100vw-2rem))] rounded-control px-3 py-2 text-xs leading-relaxed break-words">
        {description}
      </PopoverContent>
    </Popover>
  );
}
