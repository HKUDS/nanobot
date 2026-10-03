import { cn } from "@/lib/utils";

export function DiffPair({ added, deleted }: { added: number; deleted: number }) {
  return (
    <span
      className="inline-flex shrink-0 items-baseline gap-1.5 leading-[inherit] tabular-nums"
      data-testid="activity-diff-pair"
    >
      <DiffValue
        sign="+"
        value={added}
        className="text-emerald-600/75 dark:text-emerald-300/75"
      />
      <DiffValue
        sign="-"
        value={deleted}
        className="text-rose-600/70 dark:text-rose-300/75"
      />
    </span>
  );
}

function DiffValue({ sign, value, className }: { sign: string; value: number; className: string }) {
  const safeValue = Number.isFinite(value) ? Math.max(0, Math.round(value)) : 0;
  return (
    <span
      className={cn("inline-flex items-baseline leading-[inherit]", className)}
      aria-label={`${sign}${safeValue}`}
    >
      <span className="inline-flex items-baseline leading-none" aria-hidden>
        {sign}
        {safeValue}
      </span>
    </span>
  );
}
