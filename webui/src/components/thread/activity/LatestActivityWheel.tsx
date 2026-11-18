import { useLayoutEffect, useRef, useState, type ReactElement } from "react";
import { motion } from "motion/react";

import { useMediaQuery } from "@/hooks/useMediaQuery";

const SLOW = 0.24;
const FAST = 0.12;
const rowClass = "flex h-6 min-w-0 items-center [&>*]:w-full";

export function LatestActivityWheel({ row, visible }: { row: ReactElement; visible: boolean }) {
  const reducedMotion = useMediaQuery("(prefers-reduced-motion: reduce)");
  const canRoll = visible && !reducedMotion;
  const last = useRef({ row, time: -Infinity });
  const [frame, setFrame] = useState<{ key: ReactElement["key"]; previous?: ReactElement; duration?: number }>({ key: row.key });

  useLayoutEffect(() => {
    const previous = last.current;
    if (!canRoll) {
      last.current = { row, time: -Infinity };
      setFrame({ key: row.key });
    } else if (previous.row.key !== row.key) {
      const time = performance.now();
      setFrame({ previous: previous.row, key: row.key, duration: time - previous.time < 280 ? FAST : SLOW });
      last.current = { row, time };
    } else {
      // A tool's status or label can change without advancing the wheel.
      last.current = { ...previous, row };
    }
  }, [canRoll, row]);

  const outgoing = canRoll && frame.key === row.key ? frame.previous : undefined;
  return (
    <div
      aria-hidden
      {...{ inert: "" }}
      data-testid="latest-activity-wheel"
      className="relative h-6 min-w-0 overflow-hidden pe-1 max-sm:ms-6 sm:flex-1 [mask-image:linear-gradient(transparent,black_10%,black_90%,transparent)] [&_[data-activity-marker]]:self-center [&_[data-activity-marker]]:items-center [&_[data-activity-marker]]:pt-0"
    >
      {canRoll ? <motion.div
        key={frame.key}
        initial={outgoing ? { y: "100%" } : false}
        animate={{ y: 0 }}
        transition={{ duration: outgoing ? frame.duration : 0, ease: [0.22, 0.7, 0.26, 1] }}
        onAnimationComplete={() => {
          if (outgoing) setFrame((current) => current === frame ? { key: frame.key } : current);
        }}
      >
        {outgoing ? <div className={`absolute inset-x-0 bottom-full ${rowClass}`}>{outgoing}</div> : null}
        <div className={rowClass}>{row}</div>
      </motion.div> : <div className={rowClass}>{row}</div>}
    </div>
  );
}
