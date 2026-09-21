import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

export function ToggleButton({
  checked,
  disabled,
  onChange,
  ariaLabel,
  label,
  ...accessibility
}: {
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
  ariaLabel?: string;
  label: string;
} & Pick<ComponentProps<"button">, "id" | "aria-describedby" | "aria-invalid">) {
  return (
    <button
      {...accessibility}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel ?? label}
      disabled={disabled}
      onClick={() => {
        if (!disabled) onChange(!checked);
      }}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full p-0.5",
        "after:absolute after:left-1/2 after:top-1/2 after:h-11 after:w-11 after:-translate-x-1/2 after:-translate-y-1/2 after:content-['']",
        "transition-colors duration-200 ease-out motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        checked
          ? "bg-foreground"
          : "bg-muted-foreground/25 hover:bg-muted-foreground/30",
        disabled && "cursor-default opacity-60",
        disabled && !checked && "hover:bg-muted-foreground/25",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "h-4 w-4 rounded-full bg-background shadow-sm",
          "transition-transform duration-200 ease-out motion-reduce:transition-none",
          checked ? "translate-x-[16px]" : "translate-x-0",
        )}
      />
      <span className="sr-only">{label}</span>
    </button>
  );
}
