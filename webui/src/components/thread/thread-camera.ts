interface ThreadCameraMotionProfile {
  /**
   * Time constant for the ease-out chase. Smaller values react faster; the
   * camera closes roughly 95% of an uncapped distance in three time constants.
   */
  responseTimeMs: number;
  /** Prevents a long explicit navigation from turning into a one-frame jump. */
  maxSpeedPxPerSecond: number;
  /** Avoids spending frames chasing sub-pixel layout noise. */
  settleDistancePx: number;
  /** Limits catch-up after a throttled or backgrounded animation frame. */
  maxFrameDeltaMs: number;
}

const THREAD_CAMERA_NAVIGATION_MOTION: Readonly<ThreadCameraMotionProfile> = {
  responseTimeMs: 110,
  maxSpeedPxPerSecond: 12_000,
  settleDistancePx: 0.5,
  maxFrameDeltaMs: 50,
};

const THREAD_CAMERA_REDUCED_NAVIGATION_MOTION: Readonly<ThreadCameraMotionProfile> = {
  responseTimeMs: 45,
  maxSpeedPxPerSecond: 24_000,
  settleDistancePx: 0.5,
  maxFrameDeltaMs: 50,
};

export interface ThreadCameraViewport {
  scrollTop: number;
  scrollTo?: (options?: ScrollToOptions) => void;
}

export interface ThreadCameraScheduler {
  request: (callback: FrameRequestCallback) => number;
  cancel: (id: number) => void;
  now: () => number;
}

export type ThreadCameraFollowResult = "started" | "retargeted" | "settled";

interface ThreadCameraOptions {
  scheduler?: ThreadCameraScheduler;
  prefersReducedMotion?: () => boolean;
}

/**
 * A time-based ease-out chase rather than a start/end tween. The target can
 * move during explicit history navigation without restarting a duration or
 * adding another frame loop.
 */
function easeOutChase(
  current: number,
  target: number,
  deltaSeconds: number,
  profile: Pick<ThreadCameraMotionProfile, "responseTimeMs" | "maxSpeedPxPerSecond">,
): number {
  const distance = target - current;
  const responseSeconds = Math.max(0.001, profile.responseTimeMs / 1000);
  const timeStep = Math.max(0.001, deltaSeconds);
  const easeOutFraction = 1 - Math.exp(-timeStep / responseSeconds);
  const uncappedStep = distance * easeOutFraction;
  const maxStep = Math.max(0, profile.maxSpeedPxPerSecond) * timeStep;
  const step = Math.max(-maxStep, Math.min(maxStep, uncappedStep));
  return current + step;
}

function defaultScheduler(): ThreadCameraScheduler {
  return {
    request: (callback) => window.requestAnimationFrame(callback),
    cancel: (id) => window.cancelAnimationFrame(id),
    now: () => performance.now(),
  };
}

function defaultPrefersReducedMotion(): boolean {
  return typeof window !== "undefined"
    && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export class ThreadCameraController {
  private readonly getViewport: () => ThreadCameraViewport | null;
  private readonly scheduler: ThreadCameraScheduler;
  private readonly prefersReducedMotion: () => boolean;
  private frameId: number | null = null;
  private phase: "idle" | "following" = "idle";
  private target = 0;
  private lastTimestamp: number | null = null;

  constructor(
    getViewport: () => ThreadCameraViewport | null,
    options: ThreadCameraOptions = {},
  ) {
    this.getViewport = getViewport;
    this.scheduler = options.scheduler ?? defaultScheduler();
    this.prefersReducedMotion = options.prefersReducedMotion ?? defaultPrefersReducedMotion;
  }

  isFollowing(): boolean {
    return this.phase === "following";
  }

  jumpTo(top: number): void {
    const viewport = this.getViewport();
    if (!viewport) return;
    this.cancel();
    this.target = Math.max(0, top);
    this.write(viewport, this.target);
  }

  /**
   * Automatic follow is a layout constraint, not navigation. Resolve it in
   * the geometry frame so streamed content and viewport resizing cannot build
   * up hidden travel below the visible tail.
   */
  followTo(top: number): ThreadCameraFollowResult | null {
    const viewport = this.getViewport();
    if (!viewport) return null;
    this.cancel();
    this.target = Math.max(0, top);
    this.write(viewport, this.target);
    return "settled";
  }

  navigateTo(top: number): ThreadCameraFollowResult | null {
    return this.moveTo(top);
  }

  private moveTo(top: number): ThreadCameraFollowResult | null {
    const viewport = this.getViewport();
    if (!viewport) return null;
    const current = viewport.scrollTop;
    this.target = Math.max(0, top);

    const motion = this.currentMotion();
    if (this.phase === "following") {
      return "retargeted";
    }
    if (Math.abs(this.target - current) <= motion.settleDistancePx) {
      this.write(viewport, this.target);
      return "settled";
    }

    this.phase = "following";
    this.lastTimestamp = this.scheduler.now();
    this.frameId = this.scheduler.request(this.advance);
    return "started";
  }

  cancel(): void {
    if (this.frameId !== null) {
      this.scheduler.cancel(this.frameId);
      this.frameId = null;
    }
    this.phase = "idle";
    this.lastTimestamp = null;
  }

  dispose(): void {
    this.cancel();
  }

  private readonly advance = (timestamp: number): void => {
    this.frameId = null;
    const viewport = this.getViewport();
    if (!viewport || this.phase !== "following") {
      this.cancel();
      return;
    }

    const motion = this.currentMotion();
    const previousTimestamp = this.lastTimestamp ?? timestamp - (1000 / 60);
    const deltaMs = Math.min(
      motion.maxFrameDeltaMs,
      Math.max(1, timestamp - previousTimestamp),
    );
    this.lastTimestamp = timestamp;
    const current = viewport.scrollTop;
    const remainingDistance = this.target - current;
    if (Math.abs(remainingDistance) <= motion.settleDistancePx) {
      this.write(viewport, this.target);
      this.phase = "idle";
      this.lastTimestamp = null;
      return;
    }

    const deltaSeconds = deltaMs / 1000;
    const nextTop = easeOutChase(
      current,
      this.target,
      deltaSeconds,
      motion,
    );
    const settled = Math.abs(this.target - nextTop) <= motion.settleDistancePx;
    this.write(viewport, settled ? this.target : nextTop);

    if (settled) {
      this.phase = "idle";
      this.lastTimestamp = null;
      return;
    }
    this.frameId = this.scheduler.request(this.advance);
  };

  private currentMotion(): ThreadCameraMotionProfile {
    return this.prefersReducedMotion()
      ? THREAD_CAMERA_REDUCED_NAVIGATION_MOTION
      : THREAD_CAMERA_NAVIGATION_MOTION;
  }

  private write(viewport: ThreadCameraViewport, top: number): void {
    try {
      viewport.scrollTop = top;
    } catch {
      try {
        viewport.scrollTo?.({ top, behavior: "auto" });
      } catch {
        // Test DOMs can expose read-only scrollTop; browsers keep this writable.
      }
    }
  }
}
