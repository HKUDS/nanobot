import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  modalOverlayClassName,
  modalSurfaceClassName,
} from "@/components/ui/floating-surface";
import { cn } from "@/lib/utils";
import { FloatingPortalContext } from "@/components/ui/floating-portal";

const Dialog = DialogPrimitive.Root;
const DialogTrigger = DialogPrimitive.Trigger;
const DialogClose = DialogPrimitive.Close;
const DialogPortal = DialogPrimitive.Portal;
export const DialogLayoutContext = React.createContext<HTMLElement | null>(null);

const DialogOverlay = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={cn(
      modalOverlayClassName,
      "duration-200 motion-reduce:animate-none",
      className,
    )}
    {...props}
  />
));
DialogOverlay.displayName = DialogPrimitive.Overlay.displayName;

// The portal's presence ref must reach the animated content, not the plain
// positioning wrapper; otherwise the wrapper unmounts before the exit finishes.
// Auto margins center/bottom-align surfaces when they fit, but collapse to zero
// when they overflow so the beginning of a tall dialog remains scrollable.
// The overlay stays mounted for the content's presence lifetime, so its own
// fade cannot remove the content before its exit cleanup/handoff completes.
const DialogPositionedContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & {
    contained?: boolean;
    positionerStyle?: React.CSSProperties;
    placement?: "center" | "bottom";
    overlayClassName?: string;
  }
>(({ contained, positionerStyle, placement, overlayClassName, ...props }, ref) => {
  const Overlay = contained ? "div" : DialogOverlay;
  return <Overlay data-dialog-backdrop {...(contained ? {} : { forceMount: true })} className={cn(contained && "absolute inset-0 z-50", overlayClassName)}>
  <div className={cn("fixed inset-0 z-50 flex items-start justify-center overscroll-contain", placement === "bottom" ? "overflow-clip" : "overflow-y-auto p-4", contained && "absolute")} style={{
    top: "var(--app-viewport-top, 0px)",
    height: "var(--app-viewport-height, 100%)",
    bottom: "auto",
    ...(contained ? { top: 0, height: "100%" } : positionerStyle),
  }}>
    <DialogPrimitive.Content ref={ref} {...props} />
  </div>
  </Overlay>;
});
DialogPositionedContent.displayName = "DialogPositionedContent";

interface DialogContentProps
  extends React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> {
  portalContainer?: HTMLElement | null;
  showCloseButton?: boolean;
  overlayClassName?: string;
  layoutAnchor?: HTMLElement | null;
  centerInLayoutAnchor?: boolean;
  placement?: "center" | "bottom";
}

const DialogContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  DialogContentProps
>(({ className, children, portalContainer, showCloseButton = true, overlayClassName, placement = "center", layoutAnchor: explicitLayoutAnchor, centerInLayoutAnchor = false, onOpenAutoFocus, ...props }, ref) => {
  const { t } = useTranslation();
  const [container, setContainer] = React.useState<HTMLDivElement | null>(null);
  const contentNode = React.useRef<HTMLDivElement | null>(null);
  const gesture = React.useRef<{ id: number; start: number; y: number; time: number; speed: number; moved: boolean } | null>(null);
  const suppressClick = React.useRef(false);
  const settleAnimation = React.useRef<Animation | null>(null);
  const backdropFrame = React.useRef<number | null>(null);
  const dragBackdrop = React.useRef<{ node: HTMLElement; color: string; blur: number } | null>(null);
  const paintBackdrop = (distance: number, height: number) => {
    const backdrop = dragBackdrop.current;
    if (!backdrop) return;
    const remaining = 1 - Math.min(1, Math.max(0, distance) / Math.max(1, height));
    backdrop.node.style.backgroundColor = `color-mix(in srgb, ${backdrop.color} ${remaining * 100}%, transparent)`;
    backdrop.node.style.backdropFilter = `blur(${backdrop.blur * remaining}px)`;
  };
  const cancelBackdropFrame = () => {
    if (backdropFrame.current !== null) cancelAnimationFrame(backdropFrame.current);
    backdropFrame.current = null;
  };
  React.useEffect(() => () => {
    settleAnimation.current?.cancel();
    if (backdropFrame.current !== null) cancelAnimationFrame(backdropFrame.current);
  }, []);
  const finishDrag = (button: HTMLButtonElement, pointerId: number, cancelled: boolean) => {
    const drag = gesture.current;
    const node = contentNode.current;
    if (!drag || drag.id !== pointerId || !node) return;
    gesture.current = null;
    suppressClick.current = drag.moved;
    if (!drag.moved) {
      if (dragBackdrop.current) {
        const style = dragBackdrop.current.node.style;
        for (const property of ["background-color", "backdrop-filter", "transition"]) style.removeProperty(property);
        dragBackdrop.current = null;
      }
      return;
    }
    const distance = Math.max(0, drag.y - drag.start);
    const dismiss = !cancelled && (distance > Math.min(120, node.offsetHeight * 0.22)
      || (distance > 24 && drag.speed > 0.65 && performance.now() - drag.time < 100));
    const destination = dismiss ? node.offsetHeight : 0;
    const animation = node.animate([{ translate: `0 ${distance}px` }, { translate: `0 ${destination}px` }], {
      duration: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : dismiss ? 180 : 260,
      easing: "cubic-bezier(0.2, 0, 0, 1)", fill: "forwards",
    });
    settleAnimation.current = animation;
    const follow = () => {
      paintBackdrop(parseFloat(getComputedStyle(node).getPropertyValue("translate").split(" ")[1]) || 0, node.offsetHeight);
      backdropFrame.current = requestAnimationFrame(follow);
    };
    backdropFrame.current = requestAnimationFrame(follow);
    animation.onfinish = () => {
      cancelBackdropFrame();
      node.style.translate = `0 ${destination}px`;
      paintBackdrop(destination, node.offsetHeight);
      if (!dismiss && dragBackdrop.current) {
        const style = dragBackdrop.current.node.style;
        for (const property of ["background-color", "backdrop-filter", "transition"]) style.removeProperty(property);
        dragBackdrop.current = null;
      }
      animation.cancel();
      settleAnimation.current = null;
      if (dismiss) { suppressClick.current = false; button.click(); }
    };
  };

  const inheritedLayoutAnchor = React.useContext(DialogLayoutContext);
  const layoutAnchor = explicitLayoutAnchor ?? inheritedLayoutAnchor;
  const [layout, setLayout] = React.useState<React.CSSProperties>();
  React.useLayoutEffect(() => {
    if (!layoutAnchor || placement === "bottom") {
      setLayout(undefined);
      return;
    }
    const update = () => {
      const rect = layoutAnchor.getBoundingClientRect();
      const style = getComputedStyle(layoutAnchor);
      const start = parseFloat(style.paddingLeft) || 0;
      const end = parseFloat(style.paddingRight) || 0;
      if (rect.width > 0) {
        const viewport = window.visualViewport;
        const top = Math.max(rect.top, viewport?.offsetTop ?? 0);
        const bottom = Math.min(rect.bottom, (viewport?.offsetTop ?? 0) + (viewport?.height ?? window.innerHeight));
        setLayout({
          left: rect.left + start, right: "auto", width: rect.width - start - end,
          paddingInline: centerInLayoutAnchor ? 16 : 0,
          ...(centerInLayoutAnchor ? { top, height: Math.max(0, bottom - top) } : {}),
        });
      }
    };
    update();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    observer?.observe(layoutAnchor);
    window.addEventListener("resize", update);
    window.visualViewport?.addEventListener("resize", update);
    window.visualViewport?.addEventListener("scroll", update);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", update);
      window.visualViewport?.removeEventListener("resize", update);
      window.visualViewport?.removeEventListener("scroll", update);
    };
  }, [layoutAnchor, placement, centerInLayoutAnchor]);
  const contentRef = React.useCallback((node: HTMLDivElement | null) => {
    contentNode.current = node;
    if (!node) {
      settleAnimation.current?.cancel();
      settleAnimation.current = null;
      if (backdropFrame.current !== null) cancelAnimationFrame(backdropFrame.current);
      backdropFrame.current = null;
      dragBackdrop.current = null;
      gesture.current = null;
    }
    setContainer(node);
    if (typeof ref === "function") ref(node);
    else if (ref) ref.current = node;
  }, [ref]);
  return (
    <DialogPortal container={portalContainer}>
        <DialogPositionedContent
          contained={!!portalContainer}
          positionerStyle={layout}
          placement={placement}
          overlayClassName={overlayClassName}
          ref={contentRef}
          onOpenAutoFocus={(event) => {
            if (onOpenAutoFocus) onOpenAutoFocus(event);
            else {
              event.preventDefault();
              contentNode.current?.focus({ preventScroll: true });
            }
          }}
          className={cn(
            modalSurfaceClassName,
            "relative grid w-full max-w-lg gap-4 p-6 duration-200 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 motion-reduce:animate-none",
            placement === "bottom"
              ? "mt-auto max-h-[85dvh] overflow-y-auto overscroll-contain rounded-t-modal pb-[max(1rem,env(safe-area-inset-bottom))] data-[state=open]:slide-in-from-bottom-full data-[state=closed]:slide-out-to-bottom-full ease-[cubic-bezier(0.2,0,0,1)] duration-300"
              : "my-auto origin-center rounded-modal data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95",
            className,
            placement === "bottom" && "pt-9 transition-none",
          )}
          {...props}
        >
          <FloatingPortalContext.Provider value={container}>
            {children}
          </FloatingPortalContext.Provider>
          {showCloseButton ? (
            <DialogPrimitive.Close
              onPointerDown={(event) => {
                if (placement !== "bottom" || !event.isPrimary || event.button !== 0) return;
                const node = contentNode.current;
                const offset = node ? parseFloat(getComputedStyle(node).getPropertyValue("translate").split(" ")[1]) || 0 : 0;
                cancelBackdropFrame();
                settleAnimation.current?.cancel();
                if (node) node.style.translate = `0 ${offset}px`;
                const backdrop = node?.closest<HTMLElement>("[data-dialog-backdrop]");
                if (backdrop && !dragBackdrop.current) {
                  const style = getComputedStyle(backdrop);
                  dragBackdrop.current = { node: backdrop, color: style.backgroundColor,
                    blur: parseFloat(style.getPropertyValue("backdrop-filter").match(/blur\(([^)]+)/)?.[1] ?? "0") || 0 };
                  backdrop.style.transition = "none";
                  backdrop.style.animation = "none";
                }
                suppressClick.current = false;
                gesture.current = { id: event.pointerId, start: event.clientY - offset, y: event.clientY, time: performance.now(), speed: 0, moved: offset > 5 };
                event.currentTarget.setPointerCapture(event.pointerId);
              }}
              onPointerMove={(event) => {
                const drag = gesture.current;
                if (!drag || drag.id !== event.pointerId) return;
                const now = performance.now();
                drag.speed = (event.clientY - drag.y) / Math.max(1, now - drag.time);
                drag.y = event.clientY; drag.time = now;
                drag.moved ||= Math.abs(drag.y - drag.start) > 5;
                if (contentNode.current) {
                  const distance = Math.max(0, drag.y - drag.start);
                  contentNode.current.style.translate = `0 ${distance}px`;
                  paintBackdrop(distance, contentNode.current.offsetHeight);
                }
              }}
              onPointerUp={(event) => finishDrag(event.currentTarget, event.pointerId, false)}
              onPointerCancel={(event) => finishDrag(event.currentTarget, event.pointerId, true)}
              onLostPointerCapture={(event) => finishDrag(event.currentTarget, event.pointerId, true)}
              onClick={(event) => { if (suppressClick.current) { event.preventDefault(); suppressClick.current = false; } }}
              className={cn("absolute grid place-items-center rounded-full text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none", placement === "bottom" ? "left-1/2 top-0 h-8 w-16 -translate-x-1/2 touch-none cursor-grab active:cursor-grabbing" : "right-2.5 top-2.5 h-7 w-7")}>
              {placement === "bottom" ? <span aria-hidden="true" className="h-1 w-9 rounded-full bg-current opacity-40" /> : <X className="h-4 w-4" />}
              <span className="sr-only">{t("common.close")}</span>
            </DialogPrimitive.Close>
          ) : null}
        </DialogPositionedContent>
    </DialogPortal>
  );
});
DialogContent.displayName = DialogPrimitive.Content.displayName;

const DialogHeader = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "flex flex-col space-y-1.5 text-center sm:text-left",
      className,
    )}
    {...props}
  />
);
DialogHeader.displayName = "DialogHeader";

const DialogFooter = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "flex flex-col-reverse gap-2 sm:flex-row sm:justify-end",
      className,
    )}
    {...props}
  />
);
DialogFooter.displayName = "DialogFooter";

const DialogTitle = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    className={cn(
      "text-balance text-lg font-semibold leading-none tracking-tight",
      className,
    )}
    {...props}
  />
));
DialogTitle.displayName = DialogPrimitive.Title.displayName;

const DialogDescription = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    className={cn("text-pretty text-sm text-muted-foreground", className)}
    {...props}
  />
));
DialogDescription.displayName = DialogPrimitive.Description.displayName;

export {
  Dialog,
  DialogTrigger,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
};
