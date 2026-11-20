import { useRef, useState, type CSSProperties, type PointerEvent } from "react";
import { useTranslation } from "react-i18next";

import { CodexSpeedControl } from "@/components/ui/codex-speed-control";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip-primitives";
import type { ModelOptionsCapability, SessionModelOptions } from "@/lib/types";

import "./model-options-control.css";

export interface ModelOptionsControlProps {
  data: { value: SessionModelOptions; capability: ModelOptionsCapability; efforts: string[]; effortsPending: boolean } | null;
  onChange: (value: SessionModelOptions) => void;
}

function ReasoningEffortControl({ options, selected, mode, onChange }: {
  options: (string | null)[];
  selected: number;
  mode: "ordered" | "pending" | "custom";
  onChange: (value: string | null) => void;
}) {
  const { t } = useTranslation();
  const label = t("settings.models.reasoningEffort");
  const auto = t("settings.values.auto");
  const last = options.length - 1;
  const axisRef = useRef<HTMLDivElement>(null);
  const thumbRef = useRef<HTMLSpanElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const drag = useRef<{ start: number; span: number; offset: number } | null>(null);
  const [preview, setPreview] = useState<number | null>(null);
  const position = preview ?? selected / Math.max(last, 1);
  const selectedLabel = options[selected] ?? auto;
  const previewLabel = options[Math.round(position * last)] ?? auto;

  function positionAt(clientX: number) {
    const { start, span, offset } = drag.current!;
    return Math.max(0, Math.min(1, (clientX - start) / span - offset));
  }

  function startDrag(event: PointerEvent<HTMLDivElement>) {
    if (!event.isPrimary || event.button !== 0) return;
    const axis = axisRef.current!;
    const bounds = axis.getBoundingClientRect();
    const radius = thumbRef.current!.offsetWidth / 2;
    const rtl = getComputedStyle(axis).direction === "rtl";
    const start = rtl ? bounds.right : bounds.left;
    const span = rtl ? -bounds.width : bounds.width;
    const delta = (event.clientX - start) / span - position;
    drag.current = { start, span, offset: Math.abs(delta * span) <= radius ? delta : 0 };
    event.preventDefault();
    inputRef.current?.focus({ preventScroll: true });
    event.currentTarget.setPointerCapture(event.pointerId);
    setPreview(positionAt(event.clientX));
  }

  function endDrag() {
    drag.current = null;
    setPreview(null);
  }
  if (mode === "custom" && last > 0) {
    return (
      <div className="reasoning-effort flex-1 justify-between text-xs">
        <span className="min-w-0 truncate" title={label}>{label}</span>
        <Select value={String(selected)} onValueChange={(index) => onChange(options[Number(index)])}>
          <SelectTrigger aria-label={label} className="h-7 min-w-0 max-w-[55%] shrink-0 px-2 text-xs max-sm:h-11">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {options.map((option, index) => (
              <SelectItem key={index} value={String(index)} className="max-sm:min-h-11">{option ?? auto}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    );
  }
  return (
    <div className="reasoning-effort text-xs">
      <span className="min-w-0 truncate" title={label}>{label}</span>
      {mode === "pending" ? (
        <div className="reasoning-effort-slider" data-pending style={{ "--effort-steps": Math.max(last, 1) } as CSSProperties}>
          <div className="reasoning-effort-track col-start-1 row-start-1" aria-hidden="true">
            <div className="reasoning-effort-lane" />
          </div>
          <span className="relative col-start-1 row-start-1 truncate px-2 text-center font-medium text-foreground" title={selectedLabel}>
            {selectedLabel}
          </span>
        </div>
      ) : last > 0 ? (
        <div className="reasoning-effort-slider" data-dragging={preview !== null || undefined}
          data-at-start={position === 0 || undefined}
          style={{ "--effort-progress": position, "--effort-steps": last } as CSSProperties}
          onPointerDown={startDrag}
          onPointerMove={(event) => {
            if (drag.current && event.currentTarget.hasPointerCapture(event.pointerId)) setPreview(positionAt(event.clientX));
          }}
          onPointerUp={(event) => {
            if (!drag.current || !event.currentTarget.hasPointerCapture(event.pointerId)) return;
            const next = Math.round(positionAt(event.clientX) * last);
            endDrag();
            if (next !== selected) onChange(options[next]);
          }}
          onLostPointerCapture={endDrag}>
          <div className="reasoning-effort-track" aria-hidden="true">
            <div className="reasoning-effort-lane"><span className="reasoning-effort-fill" /></div>
            <div ref={axisRef} className="reasoning-effort-axis">
              {options.map((_, index) => (
                <span key={index} className="reasoning-effort-tick" style={{ insetInlineStart: `${index / last * 100}%` }} />
              ))}
              <TooltipProvider>
                <Tooltip open={preview !== null} disableHoverableContent onOpenChange={(open) => { if (!open) endDrag(); }}>
                  <TooltipTrigger asChild>
                    <span ref={thumbRef} className="reasoning-effort-thumb" />
                  </TooltipTrigger>
                  <TooltipContent side="top" sideOffset={6} updatePositionStrategy="always" className="pointer-events-none">
                    {previewLabel}
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </div>
          </div>
          <input ref={inputRef} type="range" min={0} max={last} step={1} value={selected} aria-label={label} aria-valuetext={selectedLabel}
            onChange={(event) => onChange(options[event.currentTarget.valueAsNumber])} />
        </div>
      ) : (
        <span className="ms-auto min-w-0 max-w-[50%] truncate font-medium text-foreground" title={selectedLabel}>{selectedLabel}</span>
      )}
    </div>
  );
}

export function ModelOptionsControl({ data, onChange }: ModelOptionsControlProps) {
  if (!data) return null;
  const { value, capability, efforts, effortsPending } = data;
  const defaultEffort = capability.reasoning_effort.default;
  const effectiveEffort = value.reasoning_effort ?? defaultEffort;
  // Keep preset and session values selectable even if they aren't in the model catalog.
  const values = [...new Set([...efforts, defaultEffort, value.reasoning_effort].filter((effort): effort is string => !!effort))];
  const speed = capability.codex_fast_mode;
  if (!values.length && !speed) return null;
  const options = defaultEffort === null ? [null, ...values] : values;
  const mode = values.every((effort) => efforts.includes(effort)) ? "ordered" : effortsPending ? "pending" : "custom";
  return (
    <div className="model-options-row mt-1 flex shrink-0 items-center gap-1 border-t border-border/55 px-2 py-1">
      {values.length > 0 ? (
        <ReasoningEffortControl options={options} selected={options.indexOf(effectiveEffort)}
          mode={mode}
          onChange={(reasoning_effort) => onChange({ ...value, reasoning_effort })} />
      ) : null}
      {speed ? (
        <div className="flex shrink-0">
          <CodexSpeedControl
            value={value.codex_fast_mode ?? speed.default}
            onChange={(codex_fast_mode) => onChange({ ...value, codex_fast_mode })}
            ultrafastSupported={speed.ultrafast_supported}
          />
        </div>
      ) : null}
    </div>
  );
}
