import { useId } from "react";
import { cn } from "@/lib/utils";
import "./ThemeToggleIcon.css";

export function ThemeToggleIcon({ theme, className }: {
  theme: "light" | "dark";
  className?: string;
}) {
  const id = useId();
  const cutoutId = `theme-cutout-${id}`;
  const discId = `theme-disc-${id}`;

  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={cn("theme-toggle-icon h-4 w-4", className)}
      data-theme={theme}
    >
      <defs>
        <mask id={cutoutId} maskUnits="userSpaceOnUse" x="-2" y="-2" width="28" height="28" className="theme-toggle-mask">
          <rect x="-2" y="-2" width="28" height="28" fill="white" stroke="none" />
          <circle className="theme-toggle-cutout" cx="24" cy="-4" r="8" fill="black" stroke="none" />
        </mask>
        <clipPath id={discId}>
          <circle className="theme-toggle-core" cx="12" cy="12" r="8" />
        </clipPath>
      </defs>
      <circle className="theme-toggle-core" cx="12" cy="12" r="8" mask={`url(#${cutoutId})`} />
      <g clipPath={`url(#${discId})`}>
        <circle className="theme-toggle-cutout" cx="24" cy="-4" r="8" />
      </g>
      <path className="theme-toggle-rays" d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42" />
    </svg>
  );
}
