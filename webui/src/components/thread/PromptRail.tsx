import { type RefObject, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import type { UIMessage } from "@/lib/types";
import {
  findPromptElement,
  jumpToPrompt,
  type PromptAnchor,
  promptTop,
  userPromptAnchors,
} from "@/components/thread/promptNavigation";

interface PromptRailProps {
  bottomOffset: number;
  contentRef: RefObject<HTMLElement>;
  messages: UIMessage[];
  scrollRef: RefObject<HTMLDivElement>;
}

interface MeasuredPrompt extends PromptAnchor {
  top: number;
  topPercent: number;
}

interface PromptMarker {
  answerPreview: string;
  count: number;
  ids: string[];
  label: string;
  preview: string;
  topPercent: number;
}

const MIN_PROMPTS_FOR_RAIL = 3;
const RAIL_MIN_SCROLL_RANGE_PX = 80;
const DENSE_PROMPT_THRESHOLD = 30;
const DENSE_BUCKET_HEIGHT_PX = 12;
const DENSE_BUCKET_FALLBACK_COUNT = 32;
const DENSE_BUCKET_MAX_COUNT = 42;
const MARKER_MIN_GAP_PX = 9;
const MARKER_BASE_WIDTH_PX = 9;
const MARKER_STACK_GAP_PX = 16;
const RAIL_FALLBACK_HEIGHT_PX = 300;
const MEASURE_RETRY_FRAMES = 4;
const HOVER_MARKER_WIDTHS_PX = [28, 22, 16, 11];
const RAIL_WIDTH_PX = 36;
const RAIL_MIN_EDGE_GAP_PX = 12;
const RAIL_COLUMN_GAP_PX = 20;
const RAIL_REQUIRED_GUTTER_PX = RAIL_MIN_EDGE_GAP_PX + RAIL_WIDTH_PX + RAIL_COLUMN_GAP_PX;

interface RailLayout {
  visible: boolean;
  left: number | null;
}

export function PromptRail({
  bottomOffset,
  contentRef,
  messages,
  scrollRef,
}: PromptRailProps) {
  const railRef = useRef<HTMLDivElement>(null);
  const promptAnchors = useMemo(() => userPromptAnchors(messages), [messages]);
  const [markers, setMarkers] = useState<PromptMarker[]>([]);
  const [activePromptId, setActivePromptId] = useState<string | null>(null);
  const [focusedMarkerIndex, setFocusedMarkerIndex] = useState<number | null>(null);
  const [railLayout, setRailLayout] = useState<RailLayout>({ visible: true, left: null });

  const measureRailLayout = useCallback((): RailLayout => {
    const scrollEl = scrollRef.current;
    const contentEl = contentRef.current;
    if (!scrollEl || !contentEl) return { visible: true, left: null };

    const scrollRect = scrollEl.getBoundingClientRect();
    const contentRect = contentEl.getBoundingClientRect();
    if (scrollRect.width <= 0 || contentRect.width <= 0) {
      return { visible: true, left: null };
    }

    const leftGutter = contentRect.left - scrollRect.left;
    if (leftGutter < RAIL_REQUIRED_GUTTER_PX) {
      return { visible: false, left: null };
    }

    return {
      visible: true,
      left: Math.round(leftGutter - RAIL_WIDTH_PX - RAIL_COLUMN_GAP_PX),
    };
  }, [contentRef, scrollRef]);

  const updateMarkers = useCallback(() => {
    const scrollEl = scrollRef.current;
    const nextRailHeight = railRef.current?.clientHeight ?? 0;
    const nextRailLayout = measureRailLayout();
    setRailLayout((current) =>
      current.visible === nextRailLayout.visible && current.left === nextRailLayout.left
        ? current
        : nextRailLayout,
    );

    if (!nextRailLayout.visible || !scrollEl || promptAnchors.length < MIN_PROMPTS_FOR_RAIL) {
      setMarkers([]);
      setActivePromptId(null);
      return;
    }

    const scrollRange = scrollEl.scrollHeight - scrollEl.clientHeight;
    if (scrollRange < RAIL_MIN_SCROLL_RANGE_PX) {
      setMarkers([]);
      setActivePromptId(null);
      return;
    }

    const measured = measurePrompts(scrollEl, promptAnchors, scrollRange);
    const grouped = groupPromptMarkers(measured, nextRailHeight);
    setMarkers(distributeMarkerPositions(grouped, nextRailHeight));
    setActivePromptId(activePromptForScroll(measured, scrollEl.scrollTop));
  }, [measureRailLayout, promptAnchors, scrollRef]);

  useEffect(() => {
    let frame = 0;
    let remainingFrames = MEASURE_RETRY_FRAMES;
    const measure = () => {
      updateMarkers();
      remainingFrames -= 1;
      if (remainingFrames > 0) {
        frame = window.requestAnimationFrame(measure);
      }
    };
    measure();
    return () => window.cancelAnimationFrame(frame);
  }, [bottomOffset, updateMarkers]);

  useEffect(() => {
    const scrollEl = scrollRef.current;
    if (!scrollEl) return undefined;

    let frame = 0;
    const schedule = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(updateMarkers);
    };

    scrollEl.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      window.cancelAnimationFrame(frame);
      scrollEl.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
    };
  }, [scrollRef, updateMarkers]);

  useEffect(() => {
    const scrollEl = scrollRef.current;
    if (!scrollEl || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(() => updateMarkers());
    observer.observe(scrollEl);
    if (scrollEl.firstElementChild) observer.observe(scrollEl.firstElementChild);
    if (contentRef.current) observer.observe(contentRef.current);
    return () => observer.disconnect();
  }, [contentRef, scrollRef, updateMarkers]);

  if (!railLayout.visible || markers.length === 0) return null;

  return (
    <div
      ref={railRef}
      aria-label="User prompt navigation"
      className={cn(
        "group pointer-events-auto absolute left-7 top-3 z-20 hidden w-9 opacity-100 md:block",
        "transition-opacity duration-200",
        "motion-safe:animate-in motion-safe:fade-in-0 motion-safe:duration-200",
      )}
      onPointerLeave={() => setFocusedMarkerIndex(null)}
      style={{
        bottom: Math.max(80, bottomOffset),
        ...(railLayout.left == null ? {} : { left: railLayout.left }),
      }}
    >
      {markers.map((marker, index) => {
        const active = marker.ids.includes(activePromptId ?? "");
        const hoverDistance =
          focusedMarkerIndex === null ? null : Math.abs(index - focusedMarkerIndex);
        return (
          <button
            key={marker.ids.join("|")}
            type="button"
            aria-label={`Jump to prompt: ${marker.label}`}
            onClick={() => jumpToPrompt(scrollRef.current, marker.ids[marker.ids.length - 1])}
            onBlur={() => setFocusedMarkerIndex(null)}
            onFocus={() => setFocusedMarkerIndex(index)}
            onPointerEnter={() => setFocusedMarkerIndex(index)}
            onPointerLeave={() => setFocusedMarkerIndex(null)}
            className={cn(
              "group/marker absolute left-0 h-4 w-9 -translate-y-1/2 overflow-visible rounded-sm",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/60",
            )}
            style={{ top: `${marker.topPercent}%` }}
          >
            <span
              aria-hidden
              data-testid="prompt-rail-marker"
              className={cn(
                "absolute left-0 top-1/2 h-0.5 -translate-y-1/2 rounded-full",
                "transition-[width,background-color,opacity,height] duration-150",
                railMarkerTone(hoverDistance, active),
              )}
              style={{
                height: markerHeight(hoverDistance),
                width: markerWidth(hoverDistance),
              }}
            />
            <span
              aria-hidden
              className={cn(
                "pointer-events-none absolute left-10 top-1/2 z-30 w-[34rem] max-w-[calc(100vw-4rem)] -translate-y-1/2 rounded-[20px] px-4 py-3 text-left",
                "border border-border/70 bg-popover/95 text-popover-foreground shadow-[0_18px_45px_rgba(0,0,0,0.12)] backdrop-blur-xl",
                "dark:border-white/10 dark:bg-[#2f2f2f]/95 dark:text-white dark:shadow-[0_18px_45px_rgba(0,0,0,0.45)]",
                "-translate-x-2 scale-[0.98] opacity-0 transition-[opacity,transform] duration-150",
                "group-hover/marker:translate-x-0 group-hover/marker:scale-100 group-hover/marker:opacity-100",
                "group-focus-visible/marker:translate-x-0 group-focus-visible/marker:scale-100 group-focus-visible/marker:opacity-100",
              )}
            >
              <span className="line-clamp-2 whitespace-pre-wrap break-words text-[15px] font-semibold leading-6">
                {marker.preview}
              </span>
              {marker.answerPreview ? (
                <span className="mt-1.5 line-clamp-3 whitespace-pre-wrap break-words text-[14px] leading-6 text-muted-foreground dark:text-white/55">
                  {marker.answerPreview}
                </span>
              ) : null}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function measurePrompts(
  scrollEl: HTMLElement,
  anchors: PromptAnchor[],
  scrollRange: number,
): MeasuredPrompt[] {
  return anchors.flatMap((anchor) => {
    const target = findPromptElement(scrollEl, anchor.id);
    if (!target) return [];
    const top = Math.max(0, Math.min(scrollRange, promptTop(scrollEl, target) - 16));
    return [{
      ...anchor,
      top,
      topPercent: clamp((top / scrollRange) * 100, 2, 98),
    }];
  });
}

function groupPromptMarkers(
  measured: MeasuredPrompt[],
  railHeight: number,
): PromptMarker[] {
  if (measured.length === 0) return [];
  if (measured.length >= DENSE_PROMPT_THRESHOLD) {
    return bucketPromptMarkers(measured, railHeight);
  }

  const minGapPercent = railHeight > 0
    ? (MARKER_MIN_GAP_PX / railHeight) * 100
    : 2;
  const groups: PromptMarker[] = [];

  for (const prompt of measured) {
    const last = groups[groups.length - 1];
    if (last && prompt.topPercent - last.topPercent < minGapPercent) {
      last.count += 1;
      last.ids.push(prompt.id);
      last.label = groupedPromptLabel(last.count, prompt.label);
      last.answerPreview = prompt.answerPreview;
      last.preview = prompt.preview;
      continue;
    }
    groups.push({
      answerPreview: prompt.answerPreview,
      count: 1,
      ids: [prompt.id],
      label: prompt.label,
      preview: prompt.preview,
      topPercent: prompt.topPercent,
    });
  }

  return groups;
}

function bucketPromptMarkers(
  measured: MeasuredPrompt[],
  railHeight: number,
): PromptMarker[] {
  const bucketCount = railHeight > 0
    ? clamp(
      Math.floor(railHeight / DENSE_BUCKET_HEIGHT_PX),
      1,
      DENSE_BUCKET_MAX_COUNT,
    )
    : DENSE_BUCKET_FALLBACK_COUNT;
  const buckets = Array.from({ length: bucketCount }, () => [] as MeasuredPrompt[]);

  for (const prompt of measured) {
    const bucketIndex = clamp(
      Math.floor((prompt.topPercent / 100) * bucketCount),
      0,
      bucketCount - 1,
    );
    buckets[bucketIndex].push(prompt);
  }

  return buckets.flatMap((bucket) => {
    if (bucket.length === 0) return [];
    const latest = bucket[bucket.length - 1];
    const topPercent =
      bucket.reduce((sum, prompt) => sum + prompt.topPercent, 0) / bucket.length;
    return [{
      count: bucket.length,
      ids: bucket.map((prompt) => prompt.id),
      label: bucket.length === 1
        ? latest.label
        : groupedPromptLabel(bucket.length, latest.label),
      answerPreview: latest.answerPreview,
      preview: latest.preview,
      topPercent,
    }];
  });
}

function distributeMarkerPositions(markers: PromptMarker[], railHeight: number): PromptMarker[] {
  const height = railHeight > 0 ? railHeight : RAIL_FALLBACK_HEIGHT_PX;
  if (markers.length <= 1) {
    return markers.map((marker) => ({ ...marker, topPercent: 50 }));
  }

  const availableHeight = Math.max(0, height - MARKER_STACK_GAP_PX);
  const stepPx = Math.min(MARKER_STACK_GAP_PX, availableHeight / (markers.length - 1));
  const stackHeight = stepPx * (markers.length - 1);
  const firstMarkerPx = (height - stackHeight) / 2;

  return markers.map((marker, index) => ({
    ...marker,
    topPercent: ((firstMarkerPx + stepPx * index) / height) * 100,
  }));
}

function activePromptForScroll(
  measured: MeasuredPrompt[],
  scrollTop: number,
): string | null {
  if (measured.length === 0) return null;
  let active = measured[0];
  const cursor = scrollTop + 96;
  for (const prompt of measured) {
    if (prompt.top <= cursor) {
      active = prompt;
      continue;
    }
    break;
  }
  return active.id;
}

function groupedPromptLabel(count: number, latestLabel: string): string {
  return `${count} prompts, latest: ${latestLabel}`;
}

function markerWidth(hoverDistance: number | null): number {
  if (hoverDistance === null) return MARKER_BASE_WIDTH_PX;
  return HOVER_MARKER_WIDTHS_PX[hoverDistance] ?? MARKER_BASE_WIDTH_PX;
}

function markerHeight(hoverDistance: number | null): number {
  return hoverDistance === 0 ? 3 : 2;
}

function railMarkerTone(hoverDistance: number | null, active: boolean): string {
  if (hoverDistance === 0) {
    return "bg-[#222222] opacity-100 dark:bg-white";
  }
  if (hoverDistance !== null && hoverDistance < HOVER_MARKER_WIDTHS_PX.length) {
    return "bg-[#d0d0d0] opacity-100 dark:bg-white/35";
  }
  if (active) {
    return "bg-[#6f6f6f] opacity-100 dark:bg-white/55";
  }
  return "bg-[#d8d8d8] opacity-100 dark:bg-white/25";
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}
