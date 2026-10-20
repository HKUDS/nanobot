import type { ThreadCameraScheduler } from "@/components/thread/thread-camera";

export const HISTORY_PULL_LIMIT_PX = 80;
export const HISTORY_PULL_TRIGGER_PX = 42;
const LOADING_POCKET_PX = 20;
const RESISTANCE_LENGTH_PX = 120;
const FREQUENCY = 22;
const DAMPING_RATIO = 0.78;

interface HistorySpringOptions {
  onUpdate: (distance: number) => void;
  scheduler?: ThreadCameraScheduler;
  prefersReducedMotion?: () => boolean;
}

/** Presentation only: the thread camera remains the sole scroll-position owner. */
export class ThreadHistorySpring {
  private readonly options: HistorySpringOptions;
  private readonly scheduler: ThreadCameraScheduler;
  private readonly reducedMotion: () => boolean;
  private frame: number | null = null;
  private timestamp: number | null = null;
  private distance = 0;
  private velocity = 0;
  private loading = false;
  private dragging = false;
  private travel = 0;
  private wheelLatched = false;

  constructor(options: HistorySpringOptions) {
    this.options = options;
    this.scheduler = options.scheduler ?? {
      request: (callback) => window.requestAnimationFrame(callback),
      cancel: (id) => window.cancelAnimationFrame(id),
      now: () => performance.now(),
    };
    const motionPreference = typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
    this.reducedMotion = options.prefersReducedMotion ?? (() => motionPreference?.matches ?? false);
  }

  setLoading(loading: boolean): void {
    if (this.loading === loading) return;
    this.loading = loading;
    if (!this.dragging) this.animate();
  }

  wheel(travel: number): boolean {
    if (this.dragging) return false;
    const first = !this.wheelLatched && travel > 0;
    this.wheelLatched = true;
    // Wheel packets add pressure to one live spring, without a position jump.
    const speed = FREQUENCY * (travel > 0
      ? HISTORY_PULL_LIMIT_PX - Math.max(0, this.distance)
      : -Math.max(0, this.distance));
    this.velocity += (speed - this.velocity) * (1 - Math.exp(-Math.abs(travel) / RESISTANCE_LENGTH_PX));
    this.animate();
    return first;
  }

  startTouch(): void {
    this.stopFrame();
    this.dragging = true;
    this.velocity = 0;
    this.travel = -RESISTANCE_LENGTH_PX
      * Math.log(Math.max(Number.EPSILON, 1 - Math.max(0, this.distance) / HISTORY_PULL_LIMIT_PX));
  }

  moveTouch(travel: number): void {
    this.travel = Math.max(0, this.travel + travel);
    this.distance = HISTORY_PULL_LIMIT_PX * (1 - Math.exp(-this.travel / RESISTANCE_LENGTH_PX));
    this.publish();
  }

  endTouch(cancelled = false): boolean {
    const triggered = this.dragging && !cancelled && this.distance >= HISTORY_PULL_TRIGGER_PX;
    this.dragging = false;
    this.travel = 0;
    this.publish();
    this.animate();
    return triggered;
  }

  leaveBoundary(): void {
    this.loading = false;
    this.dragging = false;
    this.wheelLatched = false;
    this.animate();
  }

  reset(): void {
    this.stopFrame();
    this.distance = 0;
    this.velocity = 0;
    this.travel = 0;
    this.loading = false;
    this.dragging = false;
    this.wheelLatched = false;
    this.publish();
  }

  private publish(): void {
    this.options.onUpdate(this.reducedMotion() ? 0 : Math.max(0, this.distance));
  }

  private stopFrame(): void {
    if (this.frame !== null) this.scheduler.cancel(this.frame);
    this.frame = null;
    this.timestamp = null;
  }

  private animate(): void {
    if (this.reducedMotion()) {
      this.distance = 0;
      this.velocity = 0;
      this.stopFrame();
      this.publish();
      return;
    }
    if (this.frame !== null) return;
    if (this.distance === (this.loading ? LOADING_POCKET_PX : 0) && this.velocity === 0) {
      if (!this.loading) this.wheelLatched = false;
      return;
    }
    this.timestamp = this.scheduler.now();
    this.frame = this.scheduler.request(this.advance);
  }

  private readonly advance = (timestamp: number): void => {
    this.frame = null;
    if (this.reducedMotion()) {
      this.distance = 0;
      this.velocity = 0;
      this.timestamp = null;
      this.publish();
      return;
    }
    const seconds = Math.max(0, timestamp - (this.timestamp ?? timestamp)) / 1000;
    this.timestamp = timestamp;
    const target = this.loading ? LOADING_POCKET_PX : 0;
    // Exact damped-oscillator solution stays stable across slow or suspended frames.
    const decay = FREQUENCY * DAMPING_RATIO;
    const frequency = FREQUENCY * Math.sqrt(1 - DAMPING_RATIO ** 2);
    const displacement = this.distance - target;
    const sine = (this.velocity + decay * displacement) / frequency;
    const phase = frequency * seconds;
    const envelope = Math.exp(-decay * seconds);
    this.distance = target + envelope * (displacement * Math.cos(phase) + sine * Math.sin(phase));
    this.velocity = envelope * (
      (sine * frequency - decay * displacement) * Math.cos(phase)
      - (displacement * frequency + decay * sine) * Math.sin(phase)
    );
    const settled = Math.abs(this.distance - target) < 0.08 && Math.abs(this.velocity) < 0.8;
    if (settled) {
      this.distance = target;
      this.velocity = 0;
      this.timestamp = null;
      if (!this.loading) this.wheelLatched = false;
    }
    this.publish();
    if (!settled) this.frame = this.scheduler.request(this.advance);
  };
}
