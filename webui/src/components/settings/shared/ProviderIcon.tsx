import { Hexagon } from "lucide-react";
import { useLogoFallback } from "@/hooks/useLogoFallback";
import { providerBrand } from "@/lib/provider-brand";
import { PROVIDER_ICONS } from "@/lib/provider-icons";
import { cn } from "@/lib/utils";

export function ProviderIcon({
  provider,
  showBrandLogos,
  compact = false,
}: {
  provider: string;
  showBrandLogos: boolean;
  compact?: boolean;
}) {
  const brand = providerBrand(provider);
  const Icon = PROVIDER_ICONS[provider] ?? Hexagon;
  const { logoUrl, logoLoaded, onLogoError, onLogoLoad } = useLogoFallback(brand?.logoUrls);
  const showRemoteLogo = showBrandLogos && Boolean(logoUrl);
  const showLoadedLogo = showRemoteLogo && logoLoaded;
  const isLogoTile = brand?.logoLayout === "tile" && logoUrl === brand.logoUrl;

  return (
    <span
      data-testid={`provider-logo-${provider}`}
      className={cn(
        "relative grid shrink-0 place-items-center overflow-hidden font-semibold text-muted-foreground",
        compact ? "h-6 w-6 rounded-[7px] text-[9px]" : "h-8 w-8 rounded-[9px] text-[11px]",
        showLoadedLogo ? (isLogoTile ? "bg-transparent" : "bg-white") : "bg-muted",
      )}
      aria-hidden
    >
      <span
        className={cn(
          "transition-opacity duration-150 motion-reduce:transition-none",
          showLoadedLogo ? "opacity-0" : "opacity-100",
        )}
      >
        {showBrandLogos && brand
          ? brand.initials
          : <Icon className="h-5 w-5" strokeWidth={2} />}
      </span>
      {showRemoteLogo ? (
        <img
          src={logoUrl}
          alt=""
          decoding="async"
          loading="lazy"
          referrerPolicy="no-referrer"
          draggable={false}
          className={cn(
            "absolute object-contain transition-opacity duration-150 motion-reduce:transition-none",
            isLogoTile ? (compact ? "h-6 w-6" : "h-8 w-8") : compact ? "h-[18px] w-[18px]" : "h-6 w-6",
            logoLoaded ? "opacity-100" : "opacity-0",
          )}
          onLoad={onLogoLoad}
          onError={onLogoError}
        />
      ) : null}
    </span>
  );
}
