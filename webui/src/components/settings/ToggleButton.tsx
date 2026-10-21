import { cn } from "@/lib/utils";

export function ToggleButton({
  checked,
  ariaLabel,
  label,
  onChange,
}: {
  checked: boolean;
  ariaLabel: string;
  label: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      aria-label={ariaLabel}
      className={cn(
        "inline-flex items-center justify-center rounded-full border border-border/70 bg-muted/35 px-2.5 py-1 text-[10px] font-medium tracking-[0.08em] uppercase transition-colors hover:bg-muted/60",
        checked && "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
      )}
    >
      <span aria-hidden="true">{label}</span>
      <span role="switch" aria-checked={checked} aria-label={ariaLabel} className="sr-only" />
    </button>
  );
}
