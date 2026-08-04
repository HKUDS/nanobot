export const floatingSurfaceVisualClassName =
  "rounded-[18px] border border-border/65 bg-popover/96 p-1.5 text-popover-foreground shadow-[0_18px_55px_rgba(15,23,42,0.18)] backdrop-blur-xl dark:border-white/10 dark:shadow-[0_22px_55px_rgba(0,0,0,0.45)]";

export const floatingSurfaceClassName =
  `${floatingSurfaceVisualClassName} z-50 overflow-x-hidden overflow-y-auto overscroll-contain scrollbar-thin scrollbar-track-transparent`;

export const floatingSurfaceMotionClassName =
  "data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0";

export const floatingItemClassName =
  "relative flex min-h-8 select-none items-center gap-2 rounded-[12px] px-2.5 py-2 text-[13px] outline-none transition-colors [&>svg]:h-4 [&>svg]:w-4 [&>svg]:shrink-0";

export const floatingItemFocusClassName =
  "focus:bg-foreground/[0.055] focus:text-foreground dark:focus:bg-white/[0.08]";
