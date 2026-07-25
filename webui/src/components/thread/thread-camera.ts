export interface ThreadCameraMotionProfile {
  /**
   * Time constant for the ease-out chase. Smaller values react faster; the
   * camera closes roughly 95% of an uncapped distance in three time constants.
   */
  responseTimeMs: number;
  /** Prevents a large completion batch from turning into a one-frame jump. */
  maxSpeedPxPerSecond: number;
  /** Avoids spending frames chasing sub-pixel layout noise. */
  settleDistancePx: number;
  /** Limits catch-up after a throttled or backgrounded animation frame. */
  maxFrameDeltaMs: number;
}

export const THREAD_CAMERA_FOLLOW_MOTION: Readonly<ThreadCameraMotionProfile> = {
  responseTimeMs: 90,
  maxSpeedPxPerSecond: 1_200,
  settleDistancePx: 0.5,
  maxFrameDeltaMs: 50,
};

export const THREAD_CAMERA_NAVIGATION_MOTION: Readonly<ThreadCameraMotionProfile> = {
  responseTimeMs: 110,
  maxSpeedPxPerSecond: 12_000,
  settleDistancePx: 0.5,
  maxFrameDeltaMs: 50,
};

/**
 * Reduced motion still preserves spatial continuity. Snapping a long thread
 * to its destination removes the very context that helps users understand
 * where the viewport moved; this profile shortens that motion instead.
 */
export const THREAD_CAMERA_REDUCED_MOTION: Readonly<ThreadCameraMotionProfile> = {
  responseTimeMs: 55,
  maxSpeedPxPerSecond: 2_400,
  settleDistancePx: 0.5,
  maxFrameDeltaMs: 50,
};

export const THREAD_CAMERA_REDUCED_NAVIGATION_MOTION: Readonly<ThreadCameraMotionProfile> = {
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

export interface ThreadCameraSnapshot {
  phase: "idle" | "following";
  target: number;
  velocity: number;
}

export type ThreadCameraFollowResult =
  | { kind: "started"; from: number; target: number }
  | { kind: "retargeted"; from: number; target: number }
  | { kind: "settled"; from: number; target: number };

export interface ThreadCameraOptions {
  scheduler?: ThreadCameraScheduler;
  motion?: Partial<ThreadCameraMotionProfile>;
  navigationMotion?: Partial<ThreadCameraMotionProfile>;
  reducedMotion?: Partial<ThreadCameraMotionProfile>;
  reducedNavigationMotion?: Partial<ThreadCameraMotionProfile>;
  prefersReducedMotion?: () => boolean;
}

type ThreadCameraMotionKind = "follow" | "navigation";

/**
 * A time-based ease-out chase rather than a start/end tween. The target can
 * move on every streamed line without restarting a duration or clearing the
 * controller's velocity.
 */
export function easeOutChase(
  current: number,
  target: number,
  deltaSeconds: number,
  profile: Pick<ThreadCameraMotionProfile, "responseTimeMs" | "maxSpeedPxPerSecond"> =
    THREAD_CAMERA_FOLLOW_MOTION,
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
  private readonly motion: ThreadCameraMotionProfile;
  private readonly navigationMotion: ThreadCameraMotionProfile;
  private readonly reducedMotion: ThreadCameraMotionProfile;
  private readonly reducedNavigationMotion: ThreadCameraMotionProfile;
  private readonly prefersReducedMotion: () => boolean;
  private frameId: number | null = null;
  private phase: ThreadCameraSnapshot["phase"] = "idle";
  private target = 0;
  private velocity = 0;
  private lastTimestamp: number | null = null;
  private motionKind: ThreadCameraMotionKind = "follow";

  constructor(
    getViewport: () => ThreadCameraViewport | null,
    options: ThreadCameraOptions = {},
  ) {
    this.getViewport = getViewport;
    this.scheduler = options.scheduler ?? defaultScheduler();
    this.motion = normalizeMotionProfile(
      THREAD_CAMERA_FOLLOW_MOTION,
      options.motion,
    );
    this.navigationMotion = normalizeMotionProfile(
      THREAD_CAMERA_NAVIGATION_MOTION,
      options.navigationMotion,
    );
    this.reducedMotion = normalizeMotionProfile(
      THREAD_CAMERA_REDUCED_MOTION,
      options.reducedMotion,
    );
    this.reducedNavigationMotion = normalizeMotionProfile(
      THREAD_CAMERA_REDUCED_NAVIGATION_MOTION,
      options.reducedNavigationMotion,
    );
    this.prefersReducedMotion = options.prefersReducedMotion ?? defaultPrefersReducedMotion;
  }

  snapshot(): ThreadCameraSnapshot {
    return {
      phase: this.phase,
      target: this.target,
      velocity: this.velocity,
    };
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

  followTo(top: number): ThreadCameraFollowResult | null {
    return this.moveTo(top, "follow");
  }

  navigateTo(top: number): ThreadCameraFollowResult | null {
    return this.moveTo(top, "navigation");
  }

  private moveTo(
    top: number,
    motionKind: ThreadCameraMotionKind,
  ): ThreadCameraFollowResult | null {
    const viewport = this.getViewport();
    if (!viewport) return null;
    const from = viewport.scrollTop;
    this.target = Math.max(0, top);
    this.motionKind = motionKind;

    const motion = this.currentMotion(motionKind);
    if (this.phase === "following") {
      return { kind: "retargeted", from, target: this.target };
    }
    if (Math.abs(this.target - from) <= motion.settleDistancePx) {
      this.write(viewport, this.target);
      return { kind: "settled", from, target: this.target };
    }

    this.phase = "following";
    this.velocity = 0;
    this.lastTimestamp = this.scheduler.now();
    this.frameId = this.scheduler.request(this.advance);
    return { kind: "started", from, target: this.target };
  }

  cancel(): void {
    if (this.frameId !== null) {
      this.scheduler.cancel(this.frameId);
      this.frameId = null;
    }
    this.phase = "idle";
    this.velocity = 0;
    this.lastTimestamp = null;
    this.motionKind = "follow";
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

    const motion = this.currentMotion(this.motionKind);
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
      this.velocity = 0;
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
    this.velocity = (nextTop - current) / deltaSeconds;
    const settled = Math.abs(this.target - nextTop) <= motion.settleDistancePx;
    this.write(viewport, settled ? this.target : nextTop);

    if (settled) {
      this.phase = "idle";
      this.velocity = 0;
      this.lastTimestamp = null;
      return;
    }
    this.frameId = this.scheduler.request(this.advance);
  };

  private currentMotion(kind: ThreadCameraMotionKind): ThreadCameraMotionProfile {
    if (kind === "navigation") {
      return this.prefersReducedMotion()
        ? this.reducedNavigationMotion
        : this.navigationMotion;
    }
    return this.prefersReducedMotion() ? this.reducedMotion : this.motion;
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

function normalizeMotionProfile(
  defaults: Readonly<ThreadCameraMotionProfile>,
  overrides?: Partial<ThreadCameraMotionProfile>,
): ThreadCameraMotionProfile {
  return {
    responseTimeMs: Math.max(
      1,
      overrides?.responseTimeMs ?? defaults.responseTimeMs,
    ),
    maxSpeedPxPerSecond: Math.max(
      0,
      overrides?.maxSpeedPxPerSecond ?? defaults.maxSpeedPxPerSecond,
    ),
    settleDistancePx: Math.max(
      0,
      overrides?.settleDistancePx ?? defaults.settleDistancePx,
    ),
    maxFrameDeltaMs: Math.max(
      1,
      overrides?.maxFrameDeltaMs ?? defaults.maxFrameDeltaMs,
    ),
  };
}
