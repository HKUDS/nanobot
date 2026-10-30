import type { SVGProps } from "react";

function synchronizeRing(element: SVGCircleElement | null) {
  if (!element) return;
  // Align the first frame and animations restarted by a live motion preference change.
  for (const animation of element.getAnimations()) animation.startTime = 0;
}

export function LoadingRing({ track = true, strokeDasharray = "16 46.8", ...props }: SVGProps<SVGSVGElement> & { track?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true" {...props}>
      {track ? <circle cx="12" cy="12" r="10" opacity="0.2" /> : null}
      <circle
        cx="12" cy="12" r="10" strokeDasharray={strokeDasharray} strokeLinecap="round"
        className="loading-ring-arc"
        ref={synchronizeRing}
        onAnimationStart={(event) => synchronizeRing(event.currentTarget)}
      />
    </svg>
  );
}
