import type { ReactNode } from "react";
import { LazyMotion } from "motion/react";

// Render the real elements immediately; load the animation/layout engine only on these surfaces.
const loadFeatures = () => import("./motion-features").then((module) => module.default);
export function DeferredMotion({ children }: { children: ReactNode }) {
  return <LazyMotion features={loadFeatures}>{children}</LazyMotion>;
}
