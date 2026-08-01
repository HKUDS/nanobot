import {
  type HTMLAttributes,
  type RefObject,
  useLayoutEffect,
  useRef,
} from "react";

interface SidebarSelectionHighlightProps extends HTMLAttributes<HTMLDivElement> {
  targetRef: RefObject<HTMLElement>;
  activeId: string | null;
  scope: string;
}

export const SIDEBAR_SELECTION_ITEM_CLASS =
  "relative z-[1] transition-[color] duration-150 ease-out motion-reduce:transition-none";

export const SIDEBAR_SELECTION_ACTION_ITEM_CLASS =
  "relative z-[1] transition-[width,padding,color] [transition-duration:300ms,300ms,150ms] ease-out motion-reduce:transition-none";

export function SidebarSelectionHighlight({
  targetRef,
  activeId,
  scope,
  children,
  ...containerProps
}: SidebarSelectionHighlightProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const highlightRef = useRef<HTMLDivElement>(null);
  const positionedRef = useRef(false);

  useLayoutEffect(() => {
    const highlight = highlightRef.current;
    const container = containerRef.current;
    const target = targetRef.current;
    if (!highlight) return;
    if (!activeId || !container || !target) {
      highlight.style.opacity = "0";
      positionedRef.current = false;
      return;
    }

    let restoreTransitionFrame: number | null = null;

    const position = () => {
      const containerRect = container.getBoundingClientRect();
      const targetRect = target.getBoundingClientRect();
      if (targetRect.width === 0 || targetRect.height === 0) {
        highlight.style.opacity = "0";
        positionedRef.current = false;
        return;
      }

      const firstPosition = !positionedRef.current;
      if (firstPosition) highlight.style.transitionProperty = "none";

      highlight.style.width = `${targetRect.width}px`;
      highlight.style.height = `${targetRect.height}px`;
      highlight.style.transform = `translate3d(${targetRect.left - containerRect.left}px, ${
        targetRect.top - containerRect.top
      }px, 0)`;
      highlight.style.opacity = "1";
      positionedRef.current = true;

      if (firstPosition) {
        restoreTransitionFrame = window.requestAnimationFrame(() => {
          highlight.style.removeProperty("transition-property");
          restoreTransitionFrame = null;
        });
      }
    };

    position();
    const resizeObserver =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(position);
    resizeObserver?.observe(container);
    resizeObserver?.observe(target);
    window.addEventListener("resize", position);

    return () => {
      if (restoreTransitionFrame !== null) {
        window.cancelAnimationFrame(restoreTransitionFrame);
      }
      highlight?.style.removeProperty("transition-property");
      resizeObserver?.disconnect();
      window.removeEventListener("resize", position);
    };
  });

  return (
    <div {...containerProps} ref={containerRef}>
      {children}
      <div
        ref={highlightRef}
        data-testid={`${scope}-selection-highlight`}
        data-active-id={activeId ?? undefined}
        aria-hidden="true"
        className="pointer-events-none absolute left-0 top-0 z-0 !mt-0 rounded-xl bg-sidebar-foreground/[0.055] opacity-0 transition-[transform,width,height] duration-300 ease-out will-change-transform motion-reduce:transition-none dark:bg-white/[0.07]"
      />
    </div>
  );
}
