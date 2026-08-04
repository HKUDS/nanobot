import * as React from "react";
import * as PopoverPrimitive from "@radix-ui/react-popover";

import {
  floatingSurfaceClassName,
  floatingSurfaceMotionClassName,
} from "@/components/ui/floating-surface";
import { cn } from "@/lib/utils";

const Popover = PopoverPrimitive.Root;
const PopoverTrigger = PopoverPrimitive.Trigger;

interface PopoverContentProps
  extends React.ComponentPropsWithoutRef<typeof PopoverPrimitive.Content> {
  portalContainer?: HTMLElement | null;
}

const PopoverContent = React.forwardRef<
  React.ElementRef<typeof PopoverPrimitive.Content>,
  PopoverContentProps
>(({ className, sideOffset = 4, portalContainer, ...props }, ref) => (
  <PopoverPrimitive.Portal container={portalContainer ?? undefined}>
    <PopoverPrimitive.Content
      ref={ref}
      sideOffset={sideOffset}
      className={cn(
        floatingSurfaceClassName,
        floatingSurfaceMotionClassName,
        "max-h-[min(var(--radix-popover-content-available-height),28rem)]",
        className,
      )}
      {...props}
    />
  </PopoverPrimitive.Portal>
));
PopoverContent.displayName = PopoverPrimitive.Content.displayName;

export {
  Popover,
  PopoverContent,
  PopoverTrigger,
};
