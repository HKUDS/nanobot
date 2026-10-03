const NAVIGATION_DURATION_MS = 220;
const REDUCED_NAVIGATION_DURATION_MS = 80;
const SETTLE_DISTANCE_PX = 0.5;

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
  private deadline = 0;

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

    if (this.phase === "following") {
      return "retargeted";
    }
    if (Math.abs(this.target - current) <= SETTLE_DISTANCE_PX) {
      this.write(viewport, this.target);
      return "settled";
    }

    this.phase = "following";
    this.lastTimestamp = this.scheduler.now();
    this.deadline = this.lastTimestamp + (this.prefersReducedMotion()
      ? REDUCED_NAVIGATION_DURATION_MS
      : NAVIGATION_DURATION_MS);
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

    const previousTimestamp = this.lastTimestamp ?? timestamp;
    const remainingMs = Math.max(0, this.deadline - timestamp);
    if (remainingMs === 0) {
      this.write(viewport, this.target);
      this.cancel();
      return;
    }

    const previousRemainingMs = Math.max(remainingMs, this.deadline - previousTimestamp);
    const remainingFraction = (remainingMs / previousRemainingMs) ** 3;
    const current = viewport.scrollTop;
    this.write(viewport, this.target + (current - this.target) * remainingFraction);
    this.lastTimestamp = timestamp;
    this.frameId = this.scheduler.request(this.advance);
  };

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
