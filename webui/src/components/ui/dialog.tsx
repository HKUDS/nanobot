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
      className,
    )}
    {...props}
  />
));
DialogOverlay.displayName = DialogPrimitive.Overlay.displayName;

interface DialogContentProps
  extends React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> {
  showCloseButton?: boolean;
}

const DialogContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  DialogContentProps
>(({ className, children, showCloseButton = true, onOpenAutoFocus, ...props }, ref) => {
  const { t } = useTranslation();
  const [container, setContainer] = React.useState<HTMLDivElement | null>(null);
  const contentNode = React.useRef<HTMLDivElement | null>(null);
  const layoutAnchor = React.useContext(DialogLayoutContext);
  const [layout, setLayout] = React.useState<React.CSSProperties>();
  React.useLayoutEffect(() => {
    if (!layoutAnchor) {
      setLayout(undefined);
      return;
    }
    const update = () => {
      const rect = layoutAnchor.getBoundingClientRect();
      const style = getComputedStyle(layoutAnchor);
      const start = parseFloat(style.paddingLeft) || 0;
      const end = parseFloat(style.paddingRight) || 0;
      if (rect.width > 0) setLayout({ left: rect.left + start, right: "auto", width: rect.width - start - end, paddingInline: 0 });
    };
    update();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    observer?.observe(layoutAnchor);
    window.addEventListener("resize", update);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", update);
    };
  }, [layoutAnchor]);
  const contentRef = React.useCallback((node: HTMLDivElement | null) => {
    contentNode.current = node;
    setContainer(node);
    if (typeof ref === "function") ref(node);
    else if (ref) ref.current = node;
  }, [ref]);
  return (
    <DialogPortal>
      <DialogOverlay />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={layout}>
        <DialogPrimitive.Content
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
            "relative grid w-full max-w-lg origin-center gap-4 rounded-modal p-6 duration-200 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95",
            className,
          )}
          {...props}
        >
          <FloatingPortalContext.Provider value={container}>
            {children}
          </FloatingPortalContext.Provider>
          {showCloseButton ? (
            <DialogPrimitive.Close className="absolute right-2.5 top-2.5 grid h-7 w-7 place-items-center rounded-full text-muted-foreground outline-none transition-colors hover:bg-muted hover:text-foreground active:bg-muted/80 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none">
              <X className="h-4 w-4" />
              <span className="sr-only">{t("common.close")}</span>
            </DialogPrimitive.Close>
          ) : null}
        </DialogPrimitive.Content>
      </div>
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
      "text-lg font-semibold leading-none tracking-tight",
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
    className={cn("text-sm text-muted-foreground", className)}
    {...props}
  />
));
DialogDescription.displayName = DialogPrimitive.Description.displayName;

export {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
};
