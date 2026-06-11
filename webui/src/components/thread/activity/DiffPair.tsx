import { useCallback, useEffect, useRef, useState } from "react";

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
        <AnimatedNumber value={safeValue} />
      </span>
      <span className="sr-only">{sign}{safeValue}</span>
    </span>
  );
}

function AnimatedNumber({ value }: { value: number }) {
  const safeValue = Number.isFinite(value) ? Math.max(0, Math.round(value)) : 0;
  const [display, setDisplay] = useState(0);
  const displayRef = useRef(0);

  const setAnimatedDisplay = useCallback((next: number) => {
    displayRef.current = next;
    setDisplay(next);
  }, []);

  useEffect(() => {
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) {
      setAnimatedDisplay(safeValue);
      return;
    }
    const start = displayRef.current;
    const delta = safeValue - start;
    if (delta === 0) {
      setAnimatedDisplay(safeValue);
      return;
    }
    const duration = 260;
    const startedAt = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const progress = Math.min(1, (now - startedAt) / duration);
      const eased = 1 - Math.pow(1 - progress, 3);
      setAnimatedDisplay(Math.round(start + delta * eased));
      if (progress < 1) {
        frame = window.requestAnimationFrame(tick);
        return;
      }
      displayRef.current = safeValue;
    };
    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [safeValue, setAnimatedDisplay]);

  return <RollingNumber value={display} />;
}

function RollingNumber({ value }: { value: number }) {
  const digits = String(value).split("");
  return (
    <span className="inline-flex items-baseline leading-none" aria-hidden>
      {digits.map((digit, index) => (
        <RollingDigit
          key={`${digits.length}-${index}`}
          digit={Number(digit)}
        />
      ))}
    </span>
  );
}

function RollingDigit({ digit }: { digit: number }) {
  const safeDigit = Number.isFinite(digit) ? Math.min(9, Math.max(0, digit)) : 0;
  return (
    <span className="relative inline-block h-[1em] w-[0.62em] overflow-hidden align-baseline leading-none">
      <span className="invisible block h-[1em] leading-none">0</span>
      <span
        className="absolute inset-x-0 top-0 flex flex-col transition-transform duration-200 ease-out will-change-transform"
        style={{ transform: `translateY(-${safeDigit}em)` }}
      >
        {Array.from({ length: 10 }, (_, n) => (
          <span key={n} className="block h-[1em] leading-none">
            {n}
          </span>
        ))}
      </span>
    </span>
  );
}
