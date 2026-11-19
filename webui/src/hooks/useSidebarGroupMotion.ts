import { useCallback, useEffect, useLayoutEffect, useRef } from "react";

/** Animates already mounted rows when a project or pane group expands or collapses. */
export function useSidebarGroupMotion(
  collapsedGroups: Readonly<Record<string, boolean>>,
  collapsedPaneGroups: ReadonlySet<string>,
) {
  const layoutRowRefs = useRef(new Map<string, HTMLElement>());
  const pendingLayoutRectsRef = useRef<Map<string, DOMRect> | null>(null);
  const layoutAnimationsRef = useRef(new Map<string, Animation>());
  const registerRow = useCallback((key: string, element: HTMLElement | null) => {
    if (element) layoutRowRefs.current.set(key, element);
    else layoutRowRefs.current.delete(key);
  }, []);

  const cancelAnimations = useCallback(() => {
    for (const animation of layoutAnimationsRef.current.values()) animation.cancel();
    layoutAnimationsRef.current.clear();
  }, []);

  const measureLayoutRows = useCallback(() => {
    const rects = new Map<string, DOMRect>();
    for (const [key, row] of layoutRowRefs.current) {
      rects.set(key, row.getBoundingClientRect());
    }
    return rects;
  }, []);

  const captureLayout = useCallback(() => {
    cancelAnimations();
    pendingLayoutRectsRef.current = measureLayoutRows();
  }, [cancelAnimations, measureLayoutRows]);

  useLayoutEffect(() => {
    const previousRects = pendingLayoutRectsRef.current;
    if (!previousRects) return;
    pendingLayoutRectsRef.current = null;
    const nextRects = measureLayoutRows();
    const reduceMotion = typeof window.matchMedia === "function"
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) return;
    for (const [key, nextRect] of nextRects) {
      const previousRect = previousRects.get(key);
      const row = layoutRowRefs.current.get(key);
      if (!previousRect || !row || typeof row.animate !== "function") continue;
      const deltaY = previousRect.top - nextRect.top;
      if (Math.abs(deltaY) < 0.5) continue;
      const animation = row.animate(
        [
          { transform: `translateY(${deltaY}px)` },
          { transform: "translateY(0)" },
        ],
        {
          duration: 180,
          easing: "cubic-bezier(0.2, 0, 0, 1)",
        },
      );
      layoutAnimationsRef.current.set(key, animation);
      animation.addEventListener("finish", () => {
        if (layoutAnimationsRef.current.get(key) === animation) {
          layoutAnimationsRef.current.delete(key);
        }
      }, { once: true });
    }
  }, [collapsedGroups, collapsedPaneGroups, measureLayoutRows]);

  useEffect(() => cancelAnimations, [cancelAnimations]);

  return { captureLayout, registerRow };
}
