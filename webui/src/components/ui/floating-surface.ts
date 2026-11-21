export const floatingSurfaceElevationClassName =
  "bg-popover text-popover-foreground shadow-[0_8px_24px_rgba(15,23,42,0.10)] dark:shadow-[0_12px_28px_rgba(0,0,0,0.32)]";

export const floatingSurfaceVisualClassName =
  `rounded-floating p-1.5 ${floatingSurfaceElevationClassName}`;

// A content-owned exit can keep the overlay mounted after its fade finishes.
// Retain the transparent final frame until the modal's presence unmounts it.
export const modalOverlayClassName =
  "fixed inset-0 z-50 bg-black/25 backdrop-blur-[8px] data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:fill-mode-forwards data-[state=open]:fade-in-0";

export const modalSurfaceClassName =
  "outline-none bg-background text-foreground shadow-[0_12px_36px_rgba(15,23,42,0.12)] dark:bg-popover dark:shadow-[0_18px_44px_rgba(0,0,0,0.32)]";

export const sidePanelSurfaceClassName =
  "side-panel-surface outline-none bg-background text-foreground dark:bg-popover overflow-hidden rounded-[24px]";

export const floatingSurfaceClassName =
  `${floatingSurfaceVisualClassName} z-50 overflow-x-hidden overflow-y-auto overscroll-contain scrollbar-thin`;

export const floatingSurfaceMotionClassName =
  "data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 " +
  "data-[state=open]:zoom-in-[0.98] data-[state=closed]:zoom-out-[0.98] " +
  "data-[side=bottom]:slide-in-from-top-1 data-[side=bottom]:slide-out-to-top-1 " +
  "data-[side=top]:slide-in-from-bottom-1 data-[side=top]:slide-out-to-bottom-1 " +
  "data-[side=right]:slide-in-from-left-1 data-[side=right]:slide-out-to-left-1 " +
  "data-[side=left]:slide-in-from-right-1 data-[side=left]:slide-out-to-right-1 " +
  "transition-none data-[state=open]:duration-150 data-[state=closed]:duration-100 ease-out " +
  "motion-reduce:data-[state=open]:animate-none motion-reduce:data-[state=closed]:animate-none";

export const floatingItemClassName =
  "relative flex min-h-8 select-none items-center gap-2 rounded-control px-2.5 py-2 text-[13px] outline-none transition-colors [&>svg]:h-4 [&>svg]:w-4 [&>svg]:shrink-0";

export const floatingItemFocusClassName =
  "focus:bg-foreground/[0.055] focus:text-foreground dark:focus:bg-white/[0.08]";
