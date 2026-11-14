import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cva, type VariantProps } from "class-variance-authority";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import { modalOverlayClassName, sidePanelSurfaceClassName } from "./floating-surface";

const Sheet = DialogPrimitive.Root;
const SheetTrigger = DialogPrimitive.Trigger;
const SheetPortal = DialogPrimitive.Portal;

const SheetOverlay = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={cn(
      "fixed inset-0 z-50 bg-black/40",
      "data-[state=open]:animate-in data-[state=closed]:animate-out",
      "data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
      "motion-reduce:data-[state=open]:animate-none motion-reduce:data-[state=closed]:animate-none",
      className,
    )}
    {...props}
  />
));
SheetOverlay.displayName = DialogPrimitive.Overlay.displayName;

const sheetVariants = cva(
  "fixed z-50 flex flex-col gap-4 bg-background outline-none ease-out",
  {
    variants: {
      side: {
        top: cn(
          "inset-x-0 top-0",
          "data-[state=closed]:slide-out-to-top data-[state=open]:slide-in-from-top",
        ),
        bottom: cn(
          "inset-x-0 bottom-0",
          "data-[state=closed]:slide-out-to-bottom data-[state=open]:slide-in-from-bottom",
        ),
        left: cn(
          "inset-y-2 left-2 w-3/4 max-w-[calc(100vw-1rem)] sm:max-w-sm",
          sidePanelSurfaceClassName,
          "data-[state=closed]:slide-out-to-left-4 data-[state=open]:slide-in-from-left-4",
        ),
        right: cn(
          "inset-y-2 right-2 w-3/4 max-w-[calc(100vw-1rem)] sm:max-w-sm",
          sidePanelSurfaceClassName,
          "data-[state=closed]:slide-out-to-right-4 data-[state=open]:slide-in-from-right-4",
        ),
      },
    },
    defaultVariants: {
      side: "right",
    },
  },
);

interface SheetContentProps
  extends React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>,
    VariantProps<typeof sheetVariants> {
  closeButtonClassName?: string;
  showCloseButton?: boolean;
  overlayClassName?: string;
}

const SheetContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  SheetContentProps
>((
  {
    side = "right",
    className,
    children,
    closeButtonClassName,
    showCloseButton = true,
    overlayClassName,
    ...props
  },
  ref,
) => {
  const { t } = useTranslation();
  return (
    <SheetPortal>
      <SheetOverlay className={cn((side === "right" || side === "left") && modalOverlayClassName, overlayClassName)} />
      <DialogPrimitive.Content
        ref={ref}
        className={cn(
          sheetVariants({ side }),
          "data-[state=open]:animate-in data-[state=closed]:animate-out",
          "data-[state=open]:fade-in-0 data-[state=closed]:fade-out-0 duration-200 motion-reduce:transition-none",
          "motion-reduce:data-[state=open]:animate-none motion-reduce:data-[state=closed]:animate-none",
          className,
        )}
        {...props}
      >
        {children}
        {showCloseButton ? (
          <DialogPrimitive.Close
            className={cn(
              "absolute right-2 top-2 grid size-10 place-items-center rounded-full opacity-70 ring-offset-background transition-opacity",
              "hover:opacity-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
              "disabled:pointer-events-none",
              closeButtonClassName,
            )}
          >
            <X className="h-4 w-4" />
            <span className="sr-only">{t("common.close")}</span>
          </DialogPrimitive.Close>
        ) : null}
      </DialogPrimitive.Content>
    </SheetPortal>
  );
});
SheetContent.displayName = DialogPrimitive.Content.displayName;

const SheetTitle = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    className={cn("text-lg font-semibold text-foreground", className)}
    {...props}
  />
));
SheetTitle.displayName = DialogPrimitive.Title.displayName;

const SheetDescription = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    className={cn("text-sm text-muted-foreground", className)}
    {...props}
  />
));
SheetDescription.displayName = DialogPrimitive.Description.displayName;

export { Sheet, SheetTrigger, SheetContent, SheetDescription, SheetTitle };
