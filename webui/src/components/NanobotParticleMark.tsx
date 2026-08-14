import { lazy, Suspense } from "react";

import { useMediaQuery } from "@/hooks/useMediaQuery";

interface NanobotParticleMarkProps {
  theme: "light" | "dark";
}

const LOGO_SRC = "/brand/nanobot_mark.svg";
const PARTICLES_ENABLED = import.meta.env.MODE !== "test";

const ParticleObject = lazy(async () => {
  const module = await import("@/components/canvasui/ParticleObject");
  return { default: module.ParticleObject };
});

export function NanobotParticleMark({ theme }: NanobotParticleMarkProps) {
  const compact = useMediaQuery("(max-width: 639px)");

  return (
    <div
      aria-hidden="true"
      data-particle-profile={compact ? "compact" : "desktop"}
      data-testid="nanobot-particle-mark"
      className="relative h-full w-full"
    >
      <div
        className={`pointer-events-none absolute inset-[18%] rounded-full blur-3xl ${
          theme === "dark" ? "bg-orange-500/[0.05]" : "bg-orange-400/[0.035]"
        }`}
      />

      {PARTICLES_ENABLED ? (
        <Suspense fallback={null}>
          <ParticleObject
            src={LOGO_SRC}
            count={compact ? 1_400 : 2_600}
            size={compact ? 4.75 : 4.25}
            sizeVariance={0.4}
            radius={compact ? 84 : 120}
            strength={compact ? 0.8 : 1.1}
            swirl={compact ? 0.2 : 0.25}
            spring={compact ? 0.9 : 0.85}
            damping={compact ? 0.55 : 0.5}
            drift={compact ? 0.18 : 0.25}
            scale={compact ? 2.4 : 3.4}
            yOffset={compact ? 0.2 : 0.38}
            floatIntensity={compact ? 0.25 : 0.35}
            rotationIntensity={compact ? 0.18 : 0.25}
            floatSpeed={compact ? 0.6 : 0.75}
            orbit={false}
            zoom={false}
            autoRotate={false}
            fov={58}
            cameraDistance={4.2}
            canvasTouchAction="pan-y"
            className={`h-full w-full ${
              theme === "dark" ? "opacity-[0.28]" : "opacity-[0.22]"
            }`}
          />
        </Suspense>
      ) : null}
    </div>
  );
}
