import { useCallback, useEffect, useRef } from "react";
import { useThreadVisibility } from "@/hooks/useThreadVisibility";

const BACKGROUND_FLUSH_INTERVAL_MS = 1_000;
// Markdown and layout work must leave room for input between visible updates.
const VISIBLE_FLUSH_INTERVAL_MS = 50;

/** Schedules batch publication; the transcript owner drains synchronously at semantic boundaries. */
export function useStreamBatch<Event>(onFlush: (events: Event[]) => void) {
  const visible = useThreadVisibility();
  const visibleRef = useRef(visible);
  visibleRef.current = visible;
  const pending = useRef<Event[]>([]);
  const frame = useRef<number | null>(null);
  const timer = useRef<number | null>(null);
  const lastFlush = useRef(0);

  const take = useCallback(() => {
    const events = pending.current;
    pending.current = [];
    return events;
  }, []);

  const cancelScheduled = useCallback(() => {
    if (frame.current !== null) window.cancelAnimationFrame(frame.current);
    if (timer.current !== null) window.clearTimeout(timer.current);
    frame.current = null;
    timer.current = null;
  }, []);

  const drain = useCallback(() => {
    cancelScheduled();
    lastFlush.current = 0;
    return take();
  }, [cancelScheduled, take]);

  const discard = useCallback((matches: (event: Event) => boolean) => {
    pending.current = pending.current.filter((event) => !matches(event));
  }, []);

  const schedule = useCallback(function schedule() {
    if (frame.current !== null || timer.current !== null) return;
    if (document.visibilityState === "hidden" || !visibleRef.current) {
      timer.current = window.setTimeout(() => {
        timer.current = null;
        const events = take();
        if (events.length > 0) onFlush(events);
      }, BACKGROUND_FLUSH_INTERVAL_MS);
      return;
    }
    const delay = VISIBLE_FLUSH_INTERVAL_MS - (performance.now() - lastFlush.current);
    if (delay > 0) {
      timer.current = window.setTimeout(() => {
        timer.current = null;
        schedule();
      }, delay);
      return;
    }
    frame.current = window.requestAnimationFrame(() => {
      frame.current = null;
      const events = take();
      if (events.length === 0) return;
      lastFlush.current = performance.now();
      onFlush(events);
    });
  }, [onFlush, take]);

  const enqueue = useCallback((event: Event) => {
    pending.current.push(event);
    schedule();
  }, [schedule]);

  const flush = useCallback(() => {
    const events = drain();
    if (events.length > 0) onFlush(events);
  }, [drain, onFlush]);

  useEffect(() => {
    if (visible) flush();
    else if (frame.current !== null || timer.current !== null) {
      cancelScheduled();
      schedule();
    }
  }, [cancelScheduled, flush, schedule, visible]);

  useEffect(() => {
    const onVisibilityChange = () => {
      if (pending.current.length === 0) return;
      if (document.visibilityState === "visible" && visibleRef.current) flush();
      else {
        cancelScheduled();
        schedule();
      }
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => document.removeEventListener("visibilitychange", onVisibilityChange);
  }, [cancelScheduled, flush, schedule]);

  // The subscription drains on detach before saving its last snapshot.
  return { enqueue, discard, drain };
}
