import * as React from "react";

interface Region {
  scopeRef: React.RefObject<HTMLElement>;
  surfaceRef: React.RefObject<HTMLElement>;
  editorRef: React.RefObject<HTMLElement>;
}

const RegionContext = React.createContext<Region | null>(null);

export function TooltipRegion({ children, scopeRef, surfaceRef, editorRef }: Region & { children: React.ReactNode }) {
  const region = React.useMemo(() => ({ scopeRef, surfaceRef, editorRef }), [scopeRef, surfaceRef, editorRef]);
  return <RegionContext.Provider value={region}>{children}</RegionContext.Provider>;
}

export function useHasTooltipRegion() {
  return React.useContext(RegionContext) !== null;
}

export function useTooltipRegionDismiss(triggerRef: React.RefObject<HTMLElement>, dismiss: () => void) {
  const region = React.useContext(RegionContext);
  React.useEffect(() => {
    const scope = region?.scopeRef.current;
    const trigger = triggerRef.current;
    if (!scope || !trigger || !scope.contains(trigger)) return;
    const dismissForEditor = (event: Event) => {
      if (event.target instanceof Node && region?.editorRef.current?.contains(event.target)) dismiss();
    };
    const editorEvents = ["pointermove", "focusin", "keydown", "input", "compositionstart"];
    editorEvents.forEach(event => scope.addEventListener(event, dismissForEditor, true));
    scope.addEventListener("pointerdown", dismiss, true);
    return () => {
      editorEvents.forEach(event => scope.removeEventListener(event, dismissForEditor, true));
      scope.removeEventListener("pointerdown", dismiss, true);
    };
  }, [region, triggerRef, dismiss]);
}

type Placement = {
  side?: "top" | "bottom" | "left" | "right";
  align?: "start";
  sideOffset?: number;
  alignOffset?: number;
  avoidCollisions?: false;
  style: React.CSSProperties;
};

export function useTooltipRegion(
  triggerRef: React.RefObject<HTMLElement> | undefined,
  content: HTMLDivElement | null,
  dismiss: (() => void) | undefined,
): Placement | undefined {
  const region = React.useContext(RegionContext);
  const [position, setPosition] = React.useState<{ content: HTMLDivElement; placement: Placement } | null>(null);
  const trigger = triggerRef?.current;
  const scope = region?.scopeRef.current;
  const surface = region?.surfaceRef.current;
  // Dialog/menu portals inherit React context, but are not part of the toolbar.
  const applies = Boolean(trigger && scope?.contains(trigger));

  React.useLayoutEffect(() => {
    if (!applies || !content || !trigger || !scope || !surface || !dismiss) return;
    const gap = 8;
    const measure = () => {
      const anchor = trigger.getBoundingClientRect();
      const protectedArea = surface.getBoundingClientRect();
      const column = scope.getBoundingClientRect();
      const viewport = window.visualViewport;
      const top = (viewport?.offsetTop ?? 0) + gap;
      const bottom = (viewport?.offsetTop ?? 0) + (viewport?.height ?? window.innerHeight) - gap;
      const left = Math.max(column.left, viewport?.offsetLeft ?? 0) + gap;
      const right = Math.min(column.right, (viewport?.offsetLeft ?? 0) + (viewport?.width ?? window.innerWidth)) - gap;
      const maxWidth = Math.max(0, Math.min(448, right - left));
      // Measure after wrapping, before choosing a side or revealing the content.
      content.style.maxWidth = `${maxWidth}px`;
      const width = content.offsetWidth;
      const height = content.offsetHeight;
      const x = Math.max(left, Math.min(anchor.left + (anchor.width - width) / 2, right - width));
      const y = Math.max(top, Math.min(anchor.top + (anchor.height - height) / 2, bottom - height));
      const candidates = [
        { side: "top" as const, x, y: protectedArea.top - gap - height,
          sideOffset: anchor.top - protectedArea.top + gap, alignOffset: x - anchor.left },
        { side: "right" as const, x: protectedArea.right + gap, y,
          sideOffset: protectedArea.right - anchor.right + gap, alignOffset: y - anchor.top },
        { side: "left" as const, x: protectedArea.left - gap - width, y,
          sideOffset: anchor.left - protectedArea.left + gap, alignOffset: y - anchor.top },
        { side: "bottom" as const, x, y: column.bottom + gap,
          sideOffset: column.bottom - anchor.bottom + gap, alignOffset: x - anchor.left },
      ];
      const candidate = candidates.find(candidate => candidate.x >= left && candidate.x + width <= right
        && candidate.y >= top && candidate.y + height <= bottom);
      const placement: Placement = candidate
        ? { side: candidate.side, align: "start", sideOffset: candidate.sideOffset,
          alignOffset: candidate.alignOffset, avoidCollisions: false, style: { maxWidth } }
        : { style: { maxWidth, visibility: "hidden" } };
      setPosition({ content, placement });
      if (!candidate) dismiss();
    };
    measure();
    const observer = new ResizeObserver(measure);
    [scope, surface, trigger, content].forEach(element => observer.observe(element));
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    window.visualViewport?.addEventListener("resize", measure);
    window.visualViewport?.addEventListener("scroll", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
      window.visualViewport?.removeEventListener("resize", measure);
      window.visualViewport?.removeEventListener("scroll", measure);
    };
  }, [applies, content, dismiss, scope, surface, trigger]);

  return applies ? position?.content === content ? position.placement : { style: { visibility: "hidden" } } : undefined;
}
