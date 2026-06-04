import {
  type RefObject,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { cn } from "@/lib/utils";
import type { UIMessage } from "@/lib/types";

interface PromptRailProps {
  bottomOffset: number;
  messages: UIMessage[];
  scrollRef: RefObject<HTMLDivElement>;
}

interface PromptAnchor {
  id: string;
  label: string;
}

interface MeasuredPrompt extends PromptAnchor {
  top: number;
  topPercent: number;
}

interface PromptMarker {
  count: number;
  ids: string[];
  label: string;
  topPercent: number;
}

const MIN_PROMPTS_FOR_RAIL = 3;
const RAIL_MIN_SCROLL_RANGE_PX = 80;
const DENSE_PROMPT_THRESHOLD = 30;
const DENSE_BUCKET_HEIGHT_PX = 12;
const DENSE_BUCKET_FALLBACK_COUNT = 32;
const DENSE_BUCKET_MAX_COUNT = 42;
const MARKER_MIN_GAP_PX = 9;
const MARKER_BASE_WIDTH_PX = 16;
const MARKER_MAX_WIDTH_PX = 28;
const MEASURE_RETRY_FRAMES = 4;
const RAIL_REVEAL_MS = 1400;

export function PromptRail({
  bottomOffset,
  messages,
  scrollRef,
}: PromptRailProps) {
  const railRef = useRef<HTMLDivElement>(null);
  const promptAnchors = useMemo(() => userPromptAnchors(messages), [messages]);
  const [markers, setMarkers] = useState<PromptMarker[]>([]);
  const [activePromptId, setActivePromptId] = useState<string | null>(null);
  const [revealed, setRevealed] = useState(false);
  const revealTimeoutRef = useRef<number | null>(null);

  const revealTemporarily = useCallback(() => {
    setRevealed(true);
    if (revealTimeoutRef.current !== null) {
      window.clearTimeout(revealTimeoutRef.current);
    }
    revealTimeoutRef.current = window.setTimeout(() => {
      setRevealed(false);
      revealTimeoutRef.current = null;
    }, RAIL_REVEAL_MS);
  }, []);

  const updateMarkers = useCallback(() => {
    const scrollEl = scrollRef.current;
    if (!scrollEl || promptAnchors.length < MIN_PROMPTS_FOR_RAIL) {
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
    setMarkers(groupPromptMarkers(measured, railRef.current?.clientHeight ?? 0));
    setActivePromptId(activePromptForScroll(measured, scrollEl.scrollTop));
  }, [promptAnchors, scrollRef]);

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
      revealTemporarily();
      frame = window.requestAnimationFrame(updateMarkers);
    };

    scrollEl.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      window.cancelAnimationFrame(frame);
      scrollEl.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
    };
  }, [revealTemporarily, scrollRef, updateMarkers]);

  useEffect(() => {
    const scrollEl = scrollRef.current;
    if (!scrollEl || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(() => updateMarkers());
    observer.observe(scrollEl);
    if (scrollEl.firstElementChild) observer.observe(scrollEl.firstElementChild);
    return () => observer.disconnect();
  }, [scrollRef, updateMarkers]);

  useEffect(() => {
    return () => {
      if (revealTimeoutRef.current !== null) {
        window.clearTimeout(revealTimeoutRef.current);
      }
    };
  }, []);

  if (markers.length === 0) return null;

  const maxMarkerCount = Math.max(...markers.map((marker) => marker.count));
  const activeMarkerIndex = markers.findIndex((marker) =>
    marker.ids.includes(activePromptId ?? ""),
  );

  return (
    <div
      ref={railRef}
      aria-label="User prompt navigation"
      className={cn(
        "group pointer-events-auto absolute right-4 top-14 z-20 hidden w-8 opacity-70 md:block",
        "transition-opacity duration-200 hover:opacity-100",
        "motion-safe:animate-in motion-safe:fade-in-0 motion-safe:duration-200",
      )}
      style={{ bottom: Math.max(80, bottomOffset) }}
    >
      {markers.map((marker) => {
        const index = markers.indexOf(marker);
        const active = marker.ids.includes(activePromptId ?? "");
        const nearActive = activeMarkerIndex < 0 || Math.abs(index - activeMarkerIndex) <= 1;
        return (
          <button
            key={marker.ids.join("|")}
            type="button"
            title={marker.label}
            aria-label={`Jump to prompt: ${marker.label}`}
            onClick={() => jumpToPrompt(scrollRef.current, marker.ids[marker.ids.length - 1])}
            className={cn(
              "absolute right-0 h-[3px] -translate-y-1/2 rounded-full",
              "bg-foreground/20 transition-[background-color,opacity,transform,width] duration-200",
              "hover:bg-blue-500/70 hover:opacity-100 hover:scale-x-110",
              "focus-visible:bg-blue-500 focus-visible:opacity-100 focus-visible:scale-x-110",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/60",
              marker.count > 1 && "bg-foreground/30",
              active && "h-1 bg-foreground/65 opacity-80 shadow-sm",
              !active && nearActive && "opacity-25 group-hover:opacity-55",
              !active && !nearActive && !revealed && "opacity-0 group-hover:opacity-40",
              !active && !nearActive && revealed && "opacity-35",
            )}
            style={{
              top: `${marker.topPercent}%`,
              width: markerWidth(marker.count, maxMarkerCount, active),
            }}
          />
        );
      })}
    </div>
  );
}

function userPromptAnchors(messages: UIMessage[]): PromptAnchor[] {
  return messages
    .filter((message) => message.role === "user")
    .map((message, index) => ({
      id: message.id,
      label: promptLabel(message.content, index),
    }));
}

function promptLabel(content: string, index: number): string {
  const text = content.replace(/\s+/g, " ").trim();
  if (!text) return `Prompt ${index + 1}`;
  return text.length > 80 ? `${text.slice(0, 77)}...` : text;
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
      continue;
    }
    groups.push({
      count: 1,
      ids: [prompt.id],
      label: prompt.label,
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
      topPercent,
    }];
  });
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

function markerWidth(count: number, maxCount: number, active: boolean): number {
  if (maxCount <= 1) return active ? 34 : MARKER_BASE_WIDTH_PX;
  const density = Math.log2(count + 1) / Math.log2(maxCount + 1);
  const width = MARKER_BASE_WIDTH_PX
    + (MARKER_MAX_WIDTH_PX - MARKER_BASE_WIDTH_PX) * density;
  return Math.round(active ? width + 4 : width);
}

function jumpToPrompt(scrollEl: HTMLElement | null, promptId: string | undefined): void {
  if (!scrollEl || !promptId) return;
  const target = findPromptElement(scrollEl, promptId);
  if (!target) return;
  scrollEl.scrollTo({
    top: Math.max(0, promptTop(scrollEl, target) - 16),
    behavior: "smooth",
  });
}

function findPromptElement(scrollEl: HTMLElement, promptId: string): HTMLElement | null {
  const candidates = scrollEl.querySelectorAll<HTMLElement>("[data-user-prompt-id]");
  return Array.from(candidates).find(
    (candidate) => candidate.dataset.userPromptId === promptId,
  ) ?? null;
}

function promptTop(scrollEl: HTMLElement, target: HTMLElement): number {
  const scrollRect = scrollEl.getBoundingClientRect();
  const targetRect = target.getBoundingClientRect();
  const hasLayoutRect = scrollRect.top !== 0 || targetRect.top !== 0;
  if (hasLayoutRect) {
    return targetRect.top - scrollRect.top + scrollEl.scrollTop;
  }
  return target.offsetTop;
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}
