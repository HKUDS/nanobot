import { useLayoutEffect, useRef, useState } from "react";
import { ChevronDown, CircleHelp, Sparkles } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useLogoFallback } from "@/hooks/useLogoFallback";
import { inferProviderFromModelName, providerBrand } from "@/lib/provider-brand";
import { cn } from "@/lib/utils";

export interface ModelPresetOption {
  name: string;
  label: string;
  model?: string | null;
  provider?: string | null;
}

interface ModelPresetBadgeProps {
  label: string;
  modelDetail?: string | null;
  modelPreset?: string | null;
  modelPresets?: ModelPresetOption[];
  onPresetChange?: (name: string) => void;
  provider?: string | null;
  providerLabel?: string | null;
  needsSetup?: boolean;
  fallbackModelName?: string | null;
  isHero: boolean;
  onClick?: () => void;
}

export function ModelPresetBadge({
  label,
  modelDetail,
  modelPreset,
  modelPresets = [],
  onPresetChange,
  provider,
  providerLabel,
  needsSetup = false,
  fallbackModelName,
  isHero,
  onClick,
}: ModelPresetBadgeProps) {
  const activeName = modelPreset?.trim() || "";
  const listedIndex = modelPresets.findIndex((preset) => preset.name === activeName);
  const activePreset: ModelPresetOption = {
    ...(listedIndex >= 0 ? modelPresets[listedIndex] : undefined),
    name: activeName,
    label: label || modelPresets[listedIndex]?.label || activeName,
    model: modelDetail ?? modelPresets[listedIndex]?.model,
    provider: provider || modelPresets[listedIndex]?.provider,
  };
  const presets = !activeName
    ? modelPresets
    : listedIndex < 0
      ? [activePreset, ...modelPresets]
      : modelPresets.map((preset, index) => index === listedIndex ? activePreset : preset);
  const interactive = Boolean(onClick);
  const canSwitch = !interactive && Boolean(onPresetChange) && activeName !== "" && presets.length > 1;
  const badgeClassName = cn(
    "thread-composer-model-badge group/model-badge relative inline-flex w-fit min-w-0 max-w-[min(18rem,44vw)] justify-end appearance-none border-0 bg-transparent p-0 shadow-none",
    (interactive || canSwitch) && "cursor-pointer focus-visible:outline-none",
    isHero ? "h-8" : "h-9",
  );
  const badgeContent = (
    <PresetPill
      label={label}
      modelDetail={modelDetail}
      provider={provider}
      providerLabel={providerLabel}
      needsSetup={needsSetup}
      fallbackModelName={fallbackModelName}
      isHero={isHero}
      showPicker={canSwitch}
    />
  );

  if (canSwitch) {
    return (
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <button type="button" aria-label={label} className={badgeClassName}>
            {badgeContent}
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="end"
          side="top"
          sideOffset={8}
          collisionPadding={12}
          className="w-[min(20rem,calc(100vw-2rem))] rounded-[18px]"
        >
          <DropdownMenuRadioGroup
            value={activeName}
            onValueChange={(name) => {
              if (name !== activeName) onPresetChange?.(name);
            }}
          >
            {presets.map((preset) => {
              const detail = [...new Set([preset.model, preset.provider].filter(Boolean))]
                .join(" · ");
              return (
                <DropdownMenuRadioItem
                  key={preset.name}
                  value={preset.name}
                  className="min-h-[46px] items-start rounded-[14px] py-2.5"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-semibold text-foreground">
                      {preset.label || preset.name}
                    </span>
                    {detail ? (
                      <span className="mt-0.5 block truncate text-[11.5px] text-muted-foreground">
                        {detail}
                      </span>
                    ) : null}
                  </span>
                </DropdownMenuRadioItem>
              );
            })}
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    );
  }

  if (interactive) {
    return (
      <button
        type="button"
        aria-label={label}
        onClick={onClick}
        className={badgeClassName}
      >
        {badgeContent}
      </button>
    );
  }

  return (
    <span aria-label={label} className={badgeClassName}>
      {badgeContent}
    </span>
  );
}

function PresetPill({
  label,
  modelDetail,
  provider,
  providerLabel,
  needsSetup = false,
  fallbackModelName,
  isHero,
  showPicker = false,
}: {
  label: string;
  modelDetail?: string | null;
  provider?: string | null;
  providerLabel?: string | null;
  needsSetup?: boolean;
  fallbackModelName?: string | null;
  isHero: boolean;
  showPicker?: boolean;
}) {
  const labelRef = useRef<HTMLSpanElement | null>(null);
  const [labelOverflows, setLabelOverflows] = useState(false);
  const inferredProvider = needsSetup
    ? null
    : provider || inferProviderFromModelName(modelDetail || label);
  const brand = providerBrand(inferredProvider);
  const { logoUrl, onLogoError, onLogoLoad } = useLogoFallback(brand?.logoUrls);
  const title = [...new Set([label, modelDetail, providerLabel].filter(Boolean))].join(" · ");
  const logoTestId = needsSetup
    ? "composer-model-setup-icon"
    : `composer-model-logo${inferredProvider ? `-${inferredProvider}` : ""}`;

  useLayoutEffect(() => {
    const node = labelRef.current;
    if (!node) return;
    const update = () => setLabelOverflows(node.scrollWidth > node.clientWidth + 1);
    update();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    observer?.observe(node);
    return () => observer?.disconnect();
  }, [label]);

  return (
    <span
      data-fallback={fallbackModelName ? "true" : undefined}
      title={fallbackModelName || title || undefined}
      className={cn(
        "composer-model-badge composer-model-pill inline-flex h-full w-fit max-w-full min-w-0 shrink-0 items-center rounded-full border border-border/55 bg-card font-medium text-foreground/70",
        "shadow-[0_2px_8px_rgba(15,23,42,0.045)]",
        "transition-[color,background-color,border-color,transform] duration-150 ease-out group-focus-visible/model-badge:ring-2 group-focus-visible/model-badge:ring-ring/45",
        showPicker && "group-hover/model-badge:border-border group-hover/model-badge:text-foreground/85",
        needsSetup && "border-amber-500/35 bg-amber-50/70 text-amber-900 dark:bg-amber-500/10 dark:text-amber-200",
        isHero ? "gap-1.5 px-2.5 text-[12px]" : "gap-2 px-3 text-[12.5px]",
      )}
    >
      <span
        data-testid={logoTestId}
        className={cn(
          "grid shrink-0 place-items-center overflow-hidden",
          needsSetup ? "text-amber-800 dark:text-amber-200" : "rounded-full border bg-background",
          isHero ? "h-4 w-4" : "h-[18px] w-[18px]",
        )}
        style={{
          borderColor: !needsSetup && brand ? `${brand.color}28` : undefined,
          boxShadow: !needsSetup && brand ? `inset 0 0 0 1px ${brand.color}18` : undefined,
        }}
        aria-hidden
      >
        {needsSetup ? (
          <CircleHelp className={cn(isHero ? "h-3 w-3" : "h-3.5 w-3.5")} strokeWidth={1.8} />
        ) : logoUrl ? (
          <img
            src={logoUrl}
            alt=""
            draggable={false}
            decoding="async"
            loading="lazy"
            className={cn("object-contain", isHero ? "h-3 w-3" : "h-3.5 w-3.5")}
            onLoad={onLogoLoad}
            onError={onLogoError}
          />
        ) : brand ? (
          <span
            className={cn(
              "grid h-full w-full place-items-center rounded-full text-white",
              isHero ? "text-[7.5px]" : "text-[8px]",
            )}
            style={{ backgroundColor: brand.color }}
          >
            {brand.initials.slice(0, 2)}
          </span>
        ) : (
          <Sparkles className="h-3 w-3 text-muted-foreground/65" />
        )}
      </span>
      <span
        ref={labelRef}
        className={cn(
          "thread-composer-model-label min-w-0 overflow-hidden whitespace-nowrap text-center",
          labelOverflows && "thread-composer-model-label-fade",
        )}
      >
        {label}
      </span>
      {showPicker ? (
        <ChevronDown
          className="thread-composer-model-chevron h-3.5 w-3.5 shrink-0 text-muted-foreground/75"
          aria-hidden
        />
      ) : null}
    </span>
  );
}
