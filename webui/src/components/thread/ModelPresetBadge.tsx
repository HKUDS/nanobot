import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
} from "react";
import { Check, SlidersHorizontal, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  floatingItemClassName,
  floatingItemFocusClassName,
} from "@/components/ui/floating-surface";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useLogoFallback } from "@/hooks/useLogoFallback";
import { inferProviderFromModelName, providerBrand } from "@/lib/provider-brand";
import { cn } from "@/lib/utils";

const pickerWidthClassName = "w-[min(18rem,calc(100vw-2rem))]";
const LONG_PRESS_MS = 400;
const PRESS_SLOP_PX = 8;
const PILL_GAP_PX = 4;
const PILL_OFFSETS = [-2, -1, 0, 1, 2] as const;
const HANDOFF_THRESHOLD = 0.56;
const DOCK_MAX_SCALE = 1.08;
const DOCK_RADIUS = 1.5;
const SETTLE_MS = 200;

interface PresetGesture {
  active: boolean;
  baseIndex: number;
  latestY: number;
  pointerId: number;
  startY: number;
  step: number;
  target: HTMLElement;
  timer: ReturnType<typeof setTimeout> | null;
}

interface PresetMotion {
  index: number;
  remainder: number;
  settling: boolean;
}

function wrapIndex(index: number, length: number): number {
  return ((index % length) + length) % length;
}

function dockScale(distanceFromFocus: number): number {
  const distance = Math.abs(distanceFromFocus);
  if (distance >= DOCK_RADIUS) return 1;
  const influence = (1 + Math.cos(Math.PI * distance / DOCK_RADIUS)) / 2;
  return 1 + (DOCK_MAX_SCALE - 1) * influence;
}

function stepWithHysteresis(raw: number, current: number): number {
  let next = current;
  while (raw > next + HANDOFF_THRESHOLD) next += 1;
  while (raw < next - HANDOFF_THRESHOLD) next -= 1;
  return next;
}

function preventTouchScroll(event: TouchEvent) {
  if (event.cancelable) event.preventDefault();
}

function compactModelName(model?: string | null): string | null {
  const value = model?.trim();
  if (!value) return null;
  return value.split("/").at(-1) || value;
}

export interface ModelPresetOption {
  name: string;
  model?: string | null;
  provider?: string | null;
}

interface ModelPresetBadgeProps {
  label: string;
  modelDetail?: string | null;
  modelPreset?: string | null;
  modelPresets?: ModelPresetOption[];
  onPresetChange?: (name: string) => void;
  onManageModels?: () => void;
  onRequestComposerFocus?: () => void;
  provider?: string | null;
  providerLabel?: string | null;
  needsSetup?: boolean;
  attentionRequest?: number;
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
  onManageModels,
  onRequestComposerFocus,
  provider,
  providerLabel,
  needsSetup = false,
  attentionRequest = 0,
  fallbackModelName,
  isHero,
  onClick,
}: ModelPresetBadgeProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [motion, setMotion] = useState<PresetMotion | null>(null);
  const [motionWidth, setMotionWidth] = useState<number | null>(null);
  const gestureRef = useRef<PresetGesture | null>(null);
  const suppressClickRef = useRef(false);
  const activeName = modelPreset?.trim() || "";
  const listedIndex = modelPresets.findIndex((preset) => preset.name === activeName);
  const activePreset: ModelPresetOption = {
    ...(listedIndex >= 0 ? modelPresets[listedIndex] : undefined),
    name: activeName,
    model: modelDetail ?? modelPresets[listedIndex]?.model,
    provider: provider || modelPresets[listedIndex]?.provider,
  };
  const fallbackPreset = fallbackModelName
    ? modelPresets.find((preset) => preset.model?.trim() === fallbackModelName.trim())
    : undefined;
  const fallbackDisplayLabel = fallbackPreset?.name
    || fallbackModelName?.trim().split(/[/:]/).pop()
    || null;
  const displayLabel = fallbackDisplayLabel || label;
  const displayModelDetail = fallbackPreset
    ? fallbackPreset.model
    : fallbackModelName
      ? null
      : modelDetail;
  const displayProvider = fallbackPreset?.provider
    || (fallbackModelName ? inferProviderFromModelName(fallbackModelName) : provider);
  const presets = !activeName
    ? modelPresets
    : listedIndex < 0
      ? [activePreset, ...modelPresets]
      : modelPresets.map((preset, index) => index === listedIndex ? activePreset : preset);
  const opensSetup = Boolean(onClick);
  const canSwitch = !opensSetup && Boolean(onPresetChange) && activeName !== "" && presets.length > 1;
  const currentIndex = Math.max(0, presets.findIndex((preset) => preset.name === activeName));
  const pillHeight = isHero ? 32 : 36;
  const pillStride = pillHeight + PILL_GAP_PX;
  const switchModelLabel = t("thread.composer.switchModel", {
    defaultValue: "Switch model for this chat",
  });

  const selectPreset = (name: string) => {
    setOpen(false);
    if (name !== activeName) onPresetChange?.(name);
    requestAnimationFrame(() => onRequestComposerFocus?.());
  };

  const openModelSettings = () => {
    setOpen(false);
    onManageModels?.();
  };

  const clearGesture = () => {
    const gesture = gestureRef.current;
    if (gesture?.timer) clearTimeout(gesture.timer);
    if (gesture?.active) gesture.target.removeEventListener("touchmove", preventTouchScroll);
    gestureRef.current = null;
  };

  const clearMotion = () => {
    setMotion(null);
    setMotionWidth(null);
  };

  useEffect(() => {
    if (!canSwitch) {
      clearGesture();
      clearMotion();
    }
    return clearGesture;
  }, [canSwitch]);

  useEffect(() => {
    if (!motion?.settling) return;
    const timer = setTimeout(clearMotion, SETTLE_MS + 80);
    return () => clearTimeout(timer);
  }, [motion?.settling]);

  const updateMotion = (gesture: PresetGesture, clientY: number) => {
    const raw = -(clientY - gesture.startY) / pillStride;
    gesture.step = stepWithHysteresis(raw, gesture.step);
    setMotion({
      index: gesture.baseIndex + gesture.step,
      remainder: raw - gesture.step,
      settling: false,
    });
  };

  const handlePointerDown = (event: PointerEvent<HTMLButtonElement>) => {
    if (!canSwitch || gestureRef.current || motion) return;
    if (event.pointerType === "mouse" && event.button !== 0) return;
    const gesture: PresetGesture = {
      active: false,
      baseIndex: currentIndex,
      latestY: event.clientY,
      pointerId: event.pointerId,
      startY: event.clientY,
      step: 0,
      target: event.currentTarget,
      timer: null,
    };
    gesture.timer = setTimeout(() => {
      if (gestureRef.current !== gesture) return;
      gesture.active = true;
      setMotionWidth(Math.round(gesture.target.getBoundingClientRect().width) || null);
      updateMotion(gesture, gesture.latestY);
      gesture.target.addEventListener("touchmove", preventTouchScroll, { passive: false });
      try {
        gesture.target.setPointerCapture(gesture.pointerId);
      } catch {
        // The pointer may already have ended.
      }
    }, LONG_PRESS_MS);
    gestureRef.current = gesture;
  };

  const handlePointerMove = (event: PointerEvent<HTMLButtonElement>) => {
    const gesture = gestureRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    gesture.latestY = event.clientY;
    if (!gesture.active) {
      if (Math.abs(event.clientY - gesture.startY) > PRESS_SLOP_PX) clearGesture();
      return;
    }
    event.preventDefault();
    updateMotion(gesture, event.clientY);
  };

  const finishGesture = (event: PointerEvent<HTMLButtonElement>, commit: boolean) => {
    const gesture = gestureRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    clearGesture();
    if (event.currentTarget.hasPointerCapture?.(gesture.pointerId)) {
      event.currentTarget.releasePointerCapture?.(gesture.pointerId);
    }
    if (!commit || !gesture.active) {
      clearMotion();
      return;
    }
    suppressClickRef.current = true;
    const selected = presets[wrapIndex(gesture.baseIndex + gesture.step, presets.length)];
    setMotion((current) => current && { ...current, remainder: 0, settling: true });
    if (selected && selected.name !== activeName) selectPreset(selected.name);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const targetByKey: Record<string, number> = {
      ArrowUp: currentIndex - 1,
      ArrowDown: currentIndex + 1,
      Home: 0,
      End: presets.length - 1,
    };
    const target = targetByKey[event.key];
    if (target === undefined) return;
    event.preventDefault();
    const next = presets[wrapIndex(target, presets.length)];
    if (next?.name !== activeName) selectPreset(next.name);
  };

  const pill = (
    <PresetPill
      key={needsSetup ? attentionRequest : undefined}
      label={displayLabel}
      modelDetail={displayModelDetail}
      provider={displayProvider}
      providerLabel={fallbackModelName ? null : providerLabel}
      needsSetup={needsSetup}
      needsAttention={needsSetup && attentionRequest > 0}
      fallbackModelName={fallbackModelName}
      fallbackFromLabel={fallbackModelName ? label : null}
      isHero={isHero}
    />
  );

  if (!canSwitch) {
    const Container = opensSetup ? "button" : "span";
    return (
      <Container
        aria-label={fallbackModelName ? `${displayLabel} (fallback from ${label})` : label}
        type={opensSetup ? "button" : undefined}
        onClick={opensSetup ? onClick : undefined}
        className={cn(
          "thread-composer-model-badge group inline-flex w-fit min-w-0 max-w-[min(18rem,44vw)] appearance-none border-0 bg-transparent p-0 shadow-none",
          opensSetup && "cursor-pointer focus-visible:outline-none",
          isHero ? "h-8" : "h-9",
        )}
      >
        {pill}
      </Container>
    );
  }

  return (
    <Popover
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen);
        if (!nextOpen) requestAnimationFrame(() => onRequestComposerFocus?.());
      }}
    >
      <PopoverTrigger asChild>
        <button
          type="button"
          data-switching={motion ? "true" : undefined}
          aria-label={label}
          aria-expanded={open}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerLeave={(event) => {
            const gesture = gestureRef.current;
            if (gesture && gesture.pointerId === event.pointerId && !gesture.active) clearGesture();
          }}
          onPointerUp={(event) => finishGesture(event, true)}
          onPointerCancel={(event) => finishGesture(event, false)}
          onLostPointerCapture={(event) => finishGesture(event, false)}
          onContextMenu={(event) => {
            if (gestureRef.current?.active) event.preventDefault();
          }}
          onDragStart={(event) => event.preventDefault()}
          onKeyDown={handleKeyDown}
          onClickCapture={(event) => {
            if (!suppressClickRef.current) return;
            suppressClickRef.current = false;
            event.preventDefault();
            event.stopPropagation();
          }}
          style={{
            touchAction: "manipulation",
            width: motionWidth ? `${motionWidth}px` : undefined,
          }}
          className={cn(
            "thread-composer-model-badge group relative inline-flex w-fit min-w-0 max-w-[min(18rem,44vw)] cursor-pointer appearance-none border-0 bg-transparent p-0 shadow-none focus-visible:outline-none",
            motion && "z-10 cursor-grabbing",
            !motion && "cursor-grab",
            isHero ? "h-8" : "h-9",
          )}
        >
          {motion ? (
            <>
              <span data-testid="composer-model-pill-layout" className="invisible inline-flex h-full shrink-0" aria-hidden>
                {pill}
              </span>
              <span
                data-testid="composer-model-pill-viewport"
                className={cn(
                  "composer-model-pill-viewport pointer-events-none absolute -left-2 right-0 overflow-hidden bg-transparent",
                  isHero ? "-bottom-2.5 -top-2.5" : "-bottom-3 -top-3",
                )}
                aria-hidden
              >
                <span
                  data-testid="composer-model-pill-track"
                  data-settling={motion.settling ? "true" : undefined}
                  className="composer-model-pill-track ml-auto flex w-[calc(100%-0.5rem)] flex-col items-end gap-1 will-change-transform"
                  onTransitionEnd={(event) => {
                    if (motion.settling && event.currentTarget === event.target) clearMotion();
                  }}
                  style={{
                    paddingTop: isHero ? "10px" : "12px",
                    transform: `translate3d(0, ${-pillStride * (2 + motion.remainder)}px, 0)`,
                  }}
                >
                  {PILL_OFFSETS.map((offset) => {
                    const preset = presets[wrapIndex(motion.index + offset, presets.length)];
                    return (
                      <PresetPill
                        key={motion.index + offset}
                        label={preset.name}
                        modelDetail={preset.model}
                        provider={preset.provider}
                        isHero={isHero}
                        offset={offset}
                        scale={motion.settling ? 1 : dockScale(offset - motion.remainder)}
                      />
                    );
                  })}
                </span>
              </span>
            </>
          ) : pill}
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        side="top"
        sideOffset={10}
        role="dialog"
        aria-label={switchModelLabel}
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          const content = event.currentTarget;
          if (!(content instanceof HTMLElement)) return;
          const selected = content.querySelector<HTMLElement>(
            '[role="option"][aria-selected="true"]',
          );
          selected?.focus();
        }}
        className={cn(
          pickerWidthClassName,
          "origin-[var(--radix-popover-content-transform-origin)] p-1.5 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[state=closed]:slide-out-to-bottom-1 data-[state=open]:slide-in-from-bottom-1 duration-200 ease-out motion-reduce:animate-none",
        )}
      >
        <div
          role="listbox"
          aria-label={switchModelLabel}
          className="max-h-[min(16rem,var(--radix-popover-content-available-height))] overflow-y-auto py-1 scrollbar-thin scrollbar-track-transparent"
        >
          {presets.map((preset) => (
            <PresetOption
              key={preset.name}
              preset={preset}
              selected={preset.name === activeName}
              onSelect={selectPreset}
            />
          ))}
        </div>
        {onManageModels ? (
          <div className="mt-1 border-t border-border/55 pt-1">
            <button
              type="button"
              onClick={openModelSettings}
              className={cn(
                floatingItemClassName,
                floatingItemFocusClassName,
                "flex min-h-9 w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-sm font-medium text-muted-foreground hover:text-foreground",
              )}
            >
              <SlidersHorizontal className="size-4 shrink-0" strokeWidth={1.75} />
              <span>{t("thread.composer.manageModels")}</span>
            </button>
          </div>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}

function PresetOption({
  preset,
  selected,
  onSelect,
}: {
  preset: ModelPresetOption;
  selected: boolean;
  onSelect: (name: string) => void;
}) {
  const detail = compactModelName(preset.model);
  return (
    <button
      type="button"
      role="option"
      aria-label={preset.name}
      aria-selected={selected}
      onClick={() => onSelect(preset.name)}
      className={cn(
        floatingItemClassName,
        floatingItemFocusClassName,
        "flex min-h-9 w-full cursor-pointer gap-2.5 px-2.5 py-1.5 text-left hover:bg-muted/55",
        selected && "bg-muted/55 text-foreground",
      )}
    >
      <PresetProviderIcon
        label={preset.name}
        modelDetail={detail}
        provider={preset.provider}
        isHero={false}
      />
      <span className="flex min-w-0 flex-1 items-baseline gap-1.5 overflow-hidden whitespace-nowrap">
        <span className="shrink-0 text-[13px] font-medium text-foreground">{preset.name}</span>
        {detail && detail !== preset.name ? (
          <span className="truncate text-[12px] text-muted-foreground">{detail}</span>
        ) : null}
      </span>
      {selected ? <Check className="h-4 w-4 shrink-0 text-foreground/80" aria-hidden /> : null}
    </button>
  );
}

function PresetPill({
  label,
  modelDetail,
  provider,
  providerLabel,
  needsSetup = false,
  needsAttention = false,
  fallbackModelName,
  fallbackFromLabel,
  isHero,
  offset,
  scale,
}: {
  label: string;
  modelDetail?: string | null;
  provider?: string | null;
  providerLabel?: string | null;
  needsSetup?: boolean;
  needsAttention?: boolean;
  fallbackModelName?: string | null;
  fallbackFromLabel?: string | null;
  isHero: boolean;
  offset?: number;
  scale?: number;
}) {
  const labelRef = useRef<HTMLSpanElement | null>(null);
  const [labelOverflows, setLabelOverflows] = useState(false);
  const inferredProvider = needsSetup
    ? null
    : provider || inferProviderFromModelName(modelDetail || label);
  const title = [...new Set([label, modelDetail, providerLabel].filter(Boolean))].join(" · ");
  const fallbackTitle = fallbackModelName
    ? `${fallbackFromLabel || label} · using ${fallbackModelName}`
    : title;

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
      data-needs-setup={needsSetup ? "true" : undefined}
      data-preset-offset={offset}
      title={fallbackTitle || undefined}
      className={cn(
        "composer-model-badge composer-model-pill inline-flex h-full max-w-full min-w-0 shrink-0 items-center rounded-full border border-border/55 bg-card font-medium text-foreground/70",
        "w-fit",
        "transition-[color,background-color,border-color,transform] duration-150 ease-out group-focus-visible:ring-2 group-focus-visible:ring-ring/45",
        isHero ? "gap-1.5 px-2.5 text-[12px]" : "gap-2 px-3 text-[12.5px]",
        needsSetup && "composer-model-pill-setup",
        needsAttention && "composer-model-pill-setup-attention",
        offset !== undefined && "composer-model-pill-dock",
      )}
      style={scale === undefined ? undefined : {
        height: `${isHero ? 32 : 36}px`,
        transform: `scale(${scale.toFixed(4)})`,
        zIndex: Math.round(scale * 100),
      }}
    >
      {!needsSetup ? (
        <PresetProviderIcon
          label={label}
          modelDetail={modelDetail}
          provider={inferredProvider}
          testId={`composer-model-logo${inferredProvider ? `-${inferredProvider}` : ""}`}
          isHero={isHero}
        />
      ) : null}
      <span
        ref={labelRef}
        className={cn(
          "thread-composer-model-label min-w-0 overflow-hidden whitespace-nowrap text-center",
          labelOverflows && "thread-composer-model-label-fade",
        )}
      >
        {needsSetup ? <SetupPromptLabel label={label} /> : label}
      </span>
    </span>
  );
}

function SetupPromptLabel({ label }: { label: string }) {
  const separator = label.indexOf(" ");
  if (separator < 0) {
    return <span className="text-foreground/80">{label}</span>;
  }

  return (
    <span data-testid="composer-model-setup-label">
      <span className="text-muted-foreground/90 transition-colors duration-150 group-hover:text-muted-foreground motion-reduce:transition-none">
        {label.slice(0, separator)}
      </span>
      {" "}
      <span className="text-foreground/80 transition-colors duration-150 group-hover:text-foreground/90 motion-reduce:transition-none">
        {label.slice(separator + 1)}
      </span>
    </span>
  );
}

function PresetProviderIcon({
  label,
  modelDetail,
  provider,
  testId,
  isHero,
}: {
  label: string;
  modelDetail?: string | null;
  provider?: string | null;
  testId?: string;
  isHero: boolean;
}) {
  const inferredProvider = provider || inferProviderFromModelName(modelDetail || label);
  const brand = providerBrand(inferredProvider);
  const { logoUrl, onLogoError, onLogoLoad } = useLogoFallback(brand?.logoUrls);
  return (
    <span
      data-testid={testId}
      className={cn(
        "grid shrink-0 place-items-center",
        isHero ? "h-4 w-4" : "h-[18px] w-[18px]",
      )}
      aria-hidden
    >
      {logoUrl ? (
        <img
          src={logoUrl}
          alt=""
          draggable={false}
          decoding="async"
          loading="lazy"
          className={cn("object-contain", isHero ? "h-3.5 w-3.5" : "h-[18px] w-[18px]")}
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
  );
}
