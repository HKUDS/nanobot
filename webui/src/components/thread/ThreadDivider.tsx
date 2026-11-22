import type { ComponentPropsWithoutRef } from "react";

export function ThreadDivider({ children, ...props }: Omit<ComponentPropsWithoutRef<"div">, "className">) {
  return (
    <div {...props} className="mx-auto flex w-full max-w-[49.5rem] items-center justify-center gap-3 py-2 text-xs text-muted-foreground">
      <span aria-hidden className="h-px min-w-4 max-w-16 flex-1 bg-border/60" />
      <p className="min-w-0 text-center leading-5">{children}</p>
      <span aria-hidden className="h-px min-w-4 max-w-16 flex-1 bg-border/60" />
    </div>
  );
}
