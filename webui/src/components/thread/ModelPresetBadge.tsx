import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
} from "react";
import { CircleHelp, Sparkles } from "lucide-react";

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

const LONG_PRESS_MS = 400;
const PRESS_SLOP_PX = 8;
const PILL_GAP_PX = 4;
const PILL_OFFSETS = [-2, -1, 0, 1, 2] as const;
const HANDOFF_THRESHOLD = 0.56;
const DOCK_MAX_SCALE = 1.08;
const DOCK_RADIUS = 1.5;
const SETTLE_MS = 180;

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
  const currentIndex = Math.max(0, presets.findIndex((preset) => preset.name === activeName));
  const pillHeight = isHero ? 32 : 36;
  const pillStride = pillHeight + PILL_GAP_PX;
  const [motion, setMotion] = useState<PresetMotion | null>(null);
  const gestureRef = useRef<PresetGesture | null>(null);

  function clearGesture() {
    const gesture = gestureRef.current;
    if (gesture?.timer) clearTimeout(gesture.timer);
    if (gesture?.active) gesture.target.removeEventListener("touchmove", preventTouchScroll);
    gestureRef.current = null;
  }

  useEffect(() => {
    if (!canSwitch) {
      clearGesture();
      setMotion(null);
    }
    return clearGesture;
  }, [canSwitch]);

  useEffect(() => {
    if (!motion?.settling) return;
    const timer = setTimeout(() => setMotion(null), SETTLE_MS + 80);
    return () => clearTimeout(timer);
  }, [motion?.settling]);

  function updateMotion(gesture: PresetGesture, clientY: number) {
    const raw = -(clientY - gesture.startY) / pillStride;
    gesture.step = stepWithHysteresis(raw, gesture.step);
    setMotion({ index: gesture.baseIndex + gesture.step, remainder: raw - gesture.step, settling: false });
  }

  function handlePointerDown(event: PointerEvent<HTMLElement>) {
    if (!canSwitch || gestureRef.current || motion || event.isPrimary === false) return;
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
      updateMotion(gesture, gesture.latestY);
      gesture.target.addEventListener("touchmove", preventTouchScroll, { passive: false });
      try {
        gesture.target.setPointerCapture(gesture.pointerId);
      } catch { /* The pointer may already have ended. */ }
    }, LONG_PRESS_MS);
    gestureRef.current = gesture;
  }

  function handlePointerMove(event: PointerEvent<HTMLElement>) {
    const gesture = gestureRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    gesture.latestY = event.clientY;
    if (!gesture.active) {
      if (Math.abs(event.clientY - gesture.startY) > PRESS_SLOP_PX) clearGesture();
      return;
    }
    event.preventDefault();
    updateMotion(gesture, event.clientY);
  }

  function finishGesture(event: PointerEvent<HTMLElement>, commit: boolean) {
    const gesture = gestureRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    clearGesture();
    if (event.currentTarget.hasPointerCapture?.(gesture.pointerId)) {
      event.currentTarget.releasePointerCapture?.(gesture.pointerId);
    }
    if (!commit || !gesture.active) {
      setMotion(null);
      return;
    }
    const selected = presets[wrapIndex(gesture.baseIndex + gesture.step, presets.length)];
    setMotion((current) => current && { ...current, remainder: 0, settling: true });
    if (selected && selected.name !== activeName) onPresetChange?.(selected.name);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (!canSwitch) return;
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
    if (next?.name !== activeName) onPresetChange?.(next.name);
  }

  const previewIndex = wrapIndex(motion?.index ?? currentIndex, presets.length);
  const previewPreset = presets[previewIndex];
  const Container = interactive || canSwitch ? "button" : "span";
  const trackOffset = motion ? -pillStride * (2 + motion.remainder) : 0;

  return (
    <Container
      data-switching={motion ? "true" : undefined}
      data-settling={motion?.settling ? "true" : undefined}
      aria-label={label}
      aria-orientation={canSwitch ? "vertical" : undefined}
      aria-valuemax={canSwitch ? presets.length - 1 : undefined}
      aria-valuemin={canSwitch ? 0 : undefined}
      aria-valuenow={canSwitch ? previewIndex : undefined}
      aria-valuetext={canSwitch ? previewPreset?.label || label : undefined}
      role={canSwitch ? "spinbutton" : undefined}
      type={interactive || canSwitch ? "button" : undefined}
      onClick={interactive ? onClick : undefined}
      onKeyDown={handleKeyDown}
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
      style={{ touchAction: canSwitch ? "manipulation" : undefined }}
      className={cn(
        "thread-composer-model-badge group/model-badge relative inline-flex w-[5.75rem] min-w-0 justify-end appearance-none border-0 bg-transparent p-0 shadow-none",
        interactive && "cursor-pointer",
        canSwitch && "cursor-grab select-none focus-visible:outline-none",
        motion && "z-10 cursor-grabbing",
        isHero ? "h-8 max-w-[44vw]" : "h-9 max-w-[44vw]",
      )}
    >
      {motion ? (
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
              if (motion.settling && event.currentTarget === event.target) setMotion(null);
            }}
            style={{
              paddingTop: isHero ? "10px" : "12px",
              transform: `translate3d(0, ${trackOffset}px, 0)`,
            }}
          >
            {PILL_OFFSETS.map((offset) => {
              const virtualIndex = motion.index + offset;
              const preset = presets[wrapIndex(virtualIndex, presets.length)];
              const scale = motion.settling ? 1 : dockScale(offset - motion.remainder);
              return (
                <PresetPill
                  key={virtualIndex}
                  label={preset.label || preset.name}
                  modelDetail={preset.model}
                  provider={preset.provider}
                  isHero={isHero}
                  offset={offset}
                  scale={scale}
                />
              );
            })}
          </span>
        </span>
      ) : (
        <PresetPill
          label={label}
          modelDetail={modelDetail}
          provider={provider}
          providerLabel={providerLabel}
          needsSetup={needsSetup}
          fallbackModelName={fallbackModelName}
          isHero={isHero}
        />
      )}
    </Container>
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
  offset,
  scale,
}: {
  label: string;
  modelDetail?: string | null;
  provider?: string | null;
  providerLabel?: string | null;
  needsSetup?: boolean;
  fallbackModelName?: string | null;
  isHero: boolean;
  offset?: number;
  scale?: number;
}) {
  const labelRef = useRef<HTMLSpanElement | null>(null);
  const [labelOverflows, setLabelOverflows] = useState(false);
  const inferredProvider = needsSetup
    ? null
    : provider || inferProviderFromModelName(modelDetail || label);
  const brand = providerBrand(inferredProvider);
  const { logoUrl, onLogoError, onLogoLoad } = useLogoFallback(brand?.logoUrls);
  const title = [...new Set([label, modelDetail, providerLabel].filter(Boolean))].join(" · ");
  const logoTestId = offset !== undefined
    ? undefined
    : needsSetup
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
      data-preset-offset={offset}
      title={fallbackModelName || title || undefined}
      className={cn(
        "composer-model-badge composer-model-pill inline-flex h-full w-fit max-w-full min-w-0 shrink-0 items-center rounded-full border border-border/55 bg-card font-semibold text-foreground/58",
        offset === undefined && "shadow-[0_2px_8px_rgba(15,23,42,0.045)]",
        "transition-[color,background-color,border-color,transform] duration-150 ease-out group-focus-visible/model-badge:ring-2 group-focus-visible/model-badge:ring-ring/45",
        needsSetup && "border-amber-500/35 bg-amber-50/70 text-amber-900 dark:bg-amber-500/10 dark:text-amber-200",
        isHero ? "gap-1.5 px-2.5 text-[12px]" : "gap-2 px-3 text-[12.5px]",
        offset !== undefined && "composer-model-pill-dock",
      )}
      style={scale === undefined ? undefined : {
        height: `${isHero ? 32 : 36}px`,
        transform: `scale(${scale.toFixed(4)})`,
        zIndex: Math.round(scale * 100),
      }}
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
    </span>
  );
}
