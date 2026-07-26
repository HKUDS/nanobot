import { lazy, Suspense, useState } from "react";

import { useMediaQuery } from "@/hooks/useMediaQuery";

interface NanobotParticleMarkProps {
  theme: "light" | "dark";
}

const LOGO_SRC = "/brand/nanobot_icon.png";
const PARTICLES_ENABLED = import.meta.env.MODE !== "test";

const ParticleObject = lazy(async () => {
  const module = await import("@/components/canvasui/ParticleObject");
  return { default: module.ParticleObject };
});

export function NanobotParticleMark({ theme }: NanobotParticleMarkProps) {
  const [ready, setReady] = useState(false);
  const compact = useMediaQuery("(max-width: 639px)");

  return (
    <div
      aria-hidden="true"
      data-particle-profile={compact ? "compact" : "desktop"}
      data-particle-state={ready ? "ready" : "loading"}
      data-testid="nanobot-particle-mark"
      className="relative h-full w-full"
    >
      <div
        className={`pointer-events-none absolute inset-[18%] rounded-full blur-3xl ${
          theme === "dark" ? "bg-orange-500/[0.05]" : "bg-orange-400/[0.035]"
        }`}
      />

      <img
        src={LOGO_SRC}
        alt=""
        className={`pointer-events-none absolute left-1/2 top-[44%] w-52 -translate-x-1/2 -translate-y-1/2 transition-opacity duration-500 sm:w-72 ${
          ready
            ? "opacity-0"
            : theme === "dark"
              ? "opacity-[0.12]"
              : "opacity-[0.08]"
        }`}
      />

      {PARTICLES_ENABLED ? (
        <Suspense fallback={null}>
          <ParticleObject
            src={LOGO_SRC}
            count={compact ? 1_400 : 2_600}
            size={compact ? 4.75 : 4.25}
            sizeVariance={0.4}
            radius={compact ? 112 : 180}
            strength={compact ? 3.8 : 4.2}
            swirl={compact ? 1.05 : 1.35}
            spring={compact ? 0.48 : 0.38}
            damping={compact ? 0.24 : 0.18}
            drift={compact ? 0.65 : 0.9}
            scale={compact ? 2.4 : 3.4}
            yOffset={compact ? 0.2 : 0.38}
            floatIntensity={compact ? 1.1 : 1.6}
            rotationIntensity={compact ? 0.85 : 1.25}
            floatSpeed={compact ? 1.4 : 1.7}
            orbit={false}
            zoom={false}
            autoRotate={false}
            fov={58}
            cameraDistance={4.2}
            canvasTouchAction="pan-y"
            onLoad={() => setReady(true)}
            className={`h-full w-full transition-opacity duration-700 ${
              theme === "dark" ? "opacity-[0.28]" : "opacity-[0.22]"
            }`}
          />
        </Suspense>
      ) : null}
    </div>
  );
}
