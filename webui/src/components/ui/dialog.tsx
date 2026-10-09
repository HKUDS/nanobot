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
    positionerStyle?: React.CSSProperties;
    placement?: "center" | "bottom";
    overlayClassName?: string;
  }
>(({ positionerStyle, placement, overlayClassName, ...props }, ref) => (
  <DialogOverlay forceMount className={overlayClassName}>
  <div className={cn("fixed inset-0 z-50 flex items-start justify-center overflow-y-auto overscroll-contain", placement !== "bottom" && "p-4")} style={{
    top: "var(--app-viewport-top, 0px)",
    height: "var(--app-viewport-height, 100%)",
    bottom: "auto",
    ...positionerStyle,
  }}>
    <DialogPrimitive.Content ref={ref} {...props} />
  </div>
  </DialogOverlay>
));
DialogPositionedContent.displayName = "DialogPositionedContent";

interface DialogContentProps
  extends React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> {
  showCloseButton?: boolean;
  overlayClassName?: string;
  layoutAnchor?: HTMLElement | null;
  centerInLayoutAnchor?: boolean;
  placement?: "center" | "bottom";
}

const DialogContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  DialogContentProps
>(({ className, children, showCloseButton = true, overlayClassName, placement = "center", layoutAnchor: explicitLayoutAnchor, centerInLayoutAnchor = false, onOpenAutoFocus, ...props }, ref) => {
  const { t } = useTranslation();
  const [container, setContainer] = React.useState<HTMLDivElement | null>(null);
  const contentNode = React.useRef<HTMLDivElement | null>(null);
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
    setContainer(node);
    if (typeof ref === "function") ref(node);
    else if (ref) ref.current = node;
  }, [ref]);
  return (
    <DialogPortal>
        <DialogPositionedContent
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
              ? "mt-auto max-h-[85dvh] overflow-y-auto overscroll-contain rounded-t-modal pb-[max(1rem,env(safe-area-inset-bottom))] data-[state=open]:slide-in-from-bottom-4 data-[state=closed]:slide-out-to-bottom-4"
              : "my-auto origin-center rounded-modal data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95",
            className,
          )}
          {...props}
        >
          <FloatingPortalContext.Provider value={container}>
            {children}
          </FloatingPortalContext.Provider>
          {showCloseButton ? (
            <DialogPrimitive.Close className={cn("absolute right-2.5 top-2.5 grid place-items-center rounded-full text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none", placement === "bottom" ? "h-11 w-11" : "h-7 w-7")}>
              <X className="h-4 w-4" />
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
    className={cn("whitespace-pre-line text-pretty text-sm text-muted-foreground", className)}
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
