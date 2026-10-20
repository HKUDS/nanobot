import * as React from "react";
import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu";
import { ChevronRight, Circle } from "lucide-react";

import {
  floatingItemClassName,
  floatingItemFocusClassName,
  floatingSurfaceClassName,
  floatingSurfaceMotionClassName,
} from "@/components/ui/floating-surface";
import { cn } from "@/lib/utils";
import { useFloatingPortal } from "@/components/ui/floating-portal";

const DropdownTriggerContext = React.createContext<React.MutableRefObject<HTMLButtonElement | null> | null>(null);

function DropdownMenu(props: React.ComponentProps<typeof DropdownMenuPrimitive.Root>) {
  const triggerRef = React.useRef<HTMLButtonElement | null>(null);
  return (
    <DropdownTriggerContext.Provider value={triggerRef}>
      <DropdownMenuPrimitive.Root {...props} />
    </DropdownTriggerContext.Provider>
  );
}

const DropdownMenuTrigger = React.forwardRef<
  React.ElementRef<typeof DropdownMenuPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Trigger>
>((props, forwardedRef) => {
  const triggerRef = React.useContext(DropdownTriggerContext);
  const setRef = React.useCallback((node: HTMLButtonElement | null) => {
    if (triggerRef) triggerRef.current = node;
    if (typeof forwardedRef === "function") forwardedRef(node);
    else if (forwardedRef) forwardedRef.current = node;
  }, [triggerRef, forwardedRef]);
  return <DropdownMenuPrimitive.Trigger {...props} ref={setRef} />;
});
DropdownMenuTrigger.displayName = DropdownMenuPrimitive.Trigger.displayName;
const DropdownMenuRadioGroup = DropdownMenuPrimitive.RadioGroup;
const DropdownMenuSub = DropdownMenuPrimitive.Sub;

const menuItemClassName =
  `${floatingItemClassName} ${floatingItemFocusClassName} cursor-default data-[disabled]:pointer-events-none data-[disabled]:opacity-50`;

interface DropdownMenuContentProps
  extends React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Content> {
  portalContainer?: HTMLElement | null;
}

const DropdownMenuContent = React.forwardRef<
  React.ElementRef<typeof DropdownMenuPrimitive.Content>,
  DropdownMenuContentProps
>(({ className, sideOffset = 4, portalContainer, onFocusOutside, ...props }, ref) => {
  const dialogContainer = useFloatingPortal();
  const triggerRef = React.useContext(DropdownTriggerContext);
  return (
  <DropdownMenuPrimitive.Portal container={portalContainer ?? dialogContainer ?? undefined}>
    <DropdownMenuPrimitive.Content
      ref={ref}
      sideOffset={sideOffset}
      className={cn(
        floatingSurfaceClassName,
        floatingSurfaceMotionClassName,
        "max-h-[min(var(--radix-dropdown-menu-content-available-height),28rem)] min-w-[10rem]",
        className,
      )}
      {...props}
      onFocusOutside={(event) => {
        onFocusOutside?.(event);
        // Mobile browsers can focus the trigger after pointerdown opens the menu.
        // Keep that focus inside this menu's boundary, without blocking real outside focus.
        if (!event.defaultPrevented && event.target === triggerRef?.current) {
          event.preventDefault();
        }
      }}
    />
  </DropdownMenuPrimitive.Portal>
  );
});
DropdownMenuContent.displayName = DropdownMenuPrimitive.Content.displayName;

const DropdownMenuItem = React.forwardRef<
  React.ElementRef<typeof DropdownMenuPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Item> & {
    inset?: boolean;
    tone?: "default" | "destructive";
  }
>(({ className, inset, tone = "default", ...props }, ref) => (
  <DropdownMenuPrimitive.Item
    ref={ref}
    className={cn(
      menuItemClassName,
      inset && "pl-8",
      tone === "destructive" && "text-destructive focus:text-destructive",
      className,
    )}
    {...props}
  />
));
DropdownMenuItem.displayName = DropdownMenuPrimitive.Item.displayName;

const DropdownMenuRadioItem = React.forwardRef<
  React.ElementRef<typeof DropdownMenuPrimitive.RadioItem>,
  React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.RadioItem>
>(({ className, children, ...props }, ref) => (
  <DropdownMenuPrimitive.RadioItem
    ref={ref}
    className={cn(
      menuItemClassName,
      "pl-8 pr-2.5",
      className,
    )}
    {...props}
  >
    <span className="absolute left-2.5 flex h-3.5 w-3.5 items-center justify-center">
      <DropdownMenuPrimitive.ItemIndicator>
        <Circle className="h-2 w-2 fill-current" />
      </DropdownMenuPrimitive.ItemIndicator>
    </span>
    {children}
  </DropdownMenuPrimitive.RadioItem>
));
DropdownMenuRadioItem.displayName = DropdownMenuPrimitive.RadioItem.displayName;

const DropdownMenuLabel = React.forwardRef<
  React.ElementRef<typeof DropdownMenuPrimitive.Label>,
  React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Label> & {
    inset?: boolean;
  }
>(({ className, inset, ...props }, ref) => (
  <DropdownMenuPrimitive.Label
    ref={ref}
    className={cn(
      "px-2.5 pb-1.5 pt-1 text-[12px] font-semibold text-muted-foreground",
      inset && "pl-8",
      className,
    )}
    {...props}
  />
));
DropdownMenuLabel.displayName = DropdownMenuPrimitive.Label.displayName;

const DropdownMenuSeparator = React.forwardRef<
  React.ElementRef<typeof DropdownMenuPrimitive.Separator>,
  React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Separator>
>(({ className, ...props }, ref) => (
  <DropdownMenuPrimitive.Separator
    ref={ref}
    className={cn("-mx-1.5 my-1.5 h-px bg-border/50", className)}
    {...props}
  />
));
DropdownMenuSeparator.displayName = DropdownMenuPrimitive.Separator.displayName;

const DropdownMenuSubTrigger = React.forwardRef<
  React.ElementRef<typeof DropdownMenuPrimitive.SubTrigger>,
  React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.SubTrigger> & {
    inset?: boolean;
  }
>(({ className, inset, children, ...props }, ref) => (
  <DropdownMenuPrimitive.SubTrigger
    ref={ref}
    className={cn(menuItemClassName, inset && "pl-8", className)}
    {...props}
  >
    {children}
    <ChevronRight className="ml-auto h-3.5 w-3.5 text-muted-foreground" aria-hidden />
  </DropdownMenuPrimitive.SubTrigger>
));
DropdownMenuSubTrigger.displayName = DropdownMenuPrimitive.SubTrigger.displayName;

const DropdownMenuSubContent = React.forwardRef<
  React.ElementRef<typeof DropdownMenuPrimitive.SubContent>,
  React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.SubContent>
>(({ className, sideOffset = 6, ...props }, ref) => (
  <DropdownMenuPrimitive.SubContent
    ref={ref}
    sideOffset={sideOffset}
    className={cn(
      floatingSurfaceClassName,
      floatingSurfaceMotionClassName,
      "max-h-[min(var(--radix-dropdown-menu-content-available-height),22rem)] min-w-[11rem] overflow-y-auto",
      className,
    )}
    {...props}
  />
));
DropdownMenuSubContent.displayName = DropdownMenuPrimitive.SubContent.displayName;

export {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
};
