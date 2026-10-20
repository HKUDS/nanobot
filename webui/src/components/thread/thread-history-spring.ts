import type { ThreadCameraScheduler } from "@/components/thread/thread-camera";

export const HISTORY_PULL_LIMIT_PX = 80;
export const HISTORY_HOLD_PX = 48;
export const HISTORY_PULL_TRIGGER_PX = 56;
const RESISTANCE_LENGTH_PX = 120;
const FREQUENCY = 22;
const DAMPING_RATIO = 0.78;
const MAX_SPEED = FREQUENCY * HISTORY_PULL_LIMIT_PX;

export type HistoryRevealPhase = "hidden" | "feedback" | "held";

interface HistorySpringOptions {
  onUpdate: (distance: number) => void;
  onPhaseChange: (phase: HistoryRevealPhase) => void;
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
  private phase: HistoryRevealPhase = "hidden";
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

  /** A started request commits the reveal, independently of its completion. */
  hold(): void {
    this.setPhase("held");
    this.animate();
  }

  wheel(travel: number): boolean {
    if (this.dragging || travel === 0) return false;
    const first = !this.wheelLatched && travel > 0;
    if (travel > 0) {
      this.wheelLatched = true;
      if (this.phase !== "held") this.setPhase("feedback");
    }
    // Wheel packets add pressure to one live spring, without a position jump.
    const speed = FREQUENCY * (travel > 0
      ? HISTORY_PULL_LIMIT_PX - this.distance
      : -this.distance);
    this.velocity += (speed - this.velocity) * (1 - Math.exp(-Math.abs(travel) / RESISTANCE_LENGTH_PX));
    this.animate();
    return first;
  }

  startTouch(): void {
    this.stopFrame();
    this.dragging = true;
    if (this.phase !== "held") this.setPhase("feedback");
    this.velocity = 0;
    this.syncTouchTravel();
  }

  moveTouch(travel: number): void {
    if (!this.dragging) return;
    this.travel = Math.max(0, this.travel + travel);
    this.distance = HISTORY_PULL_LIMIT_PX * (1 - Math.exp(-this.travel / RESISTANCE_LENGTH_PX));
    this.publish();
  }

  endTouch(cancelled = false): boolean {
    if (!this.dragging) return false;
    const triggered = !cancelled && this.distance >= HISTORY_PULL_TRIGGER_PX;
    this.dragging = false;
    this.travel = 0;
    this.animate();
    return triggered;
  }

  /** Native scrolling releases this input round, not the committed reveal. */
  leaveBoundary(): void {
    this.dragging = false;
    this.wheelLatched = false;
    this.animate();
  }

  reset(): void {
    this.stopFrame();
    this.distance = 0;
    this.velocity = 0;
    this.travel = 0;
    this.dragging = false;
    this.wheelLatched = false;
    this.setPhase("hidden");
    this.publish();
  }

  private setPhase(phase: HistoryRevealPhase): void {
    if (this.phase === phase) return;
    this.phase = phase;
    this.options.onPhaseChange(phase);
  }

  private syncTouchTravel(): void {
    this.travel = -RESISTANCE_LENGTH_PX
      * Math.log(Math.max(Number.EPSILON, 1 - this.distance / HISTORY_PULL_LIMIT_PX));
  }

  private publish(): void {
    // Feedback keeps its settlement lifecycle without motion; a held slot is functional space.
    this.options.onUpdate(this.phase !== "held" && this.reducedMotion() ? 0 : this.distance);
  }

  private stopFrame(): void {
    if (this.frame !== null) this.scheduler.cancel(this.frame);
    this.frame = null;
    this.timestamp = null;
  }

  private finish(): void {
    this.velocity = 0;
    this.timestamp = null;
    if (this.phase !== "held") {
      this.wheelLatched = false;
      this.setPhase("hidden");
    }
  }

  private animate(): void {
    if (this.phase === "held" && this.reducedMotion()) {
      this.stopFrame();
      this.distance = HISTORY_HOLD_PX;
      this.velocity = 0;
      if (this.dragging) this.syncTouchTravel();
      this.publish();
      return;
    }
    if (this.dragging || this.frame !== null) return;
    const target = this.phase === "held" ? HISTORY_HOLD_PX : 0;
    if (this.distance === target && this.velocity === 0) {
      this.finish();
      return;
    }
    this.timestamp = this.scheduler.now();
    this.frame = this.scheduler.request(this.advance);
  }

  private readonly advance = (timestamp: number): void => {
    this.frame = null;
    const seconds = Math.max(0, timestamp - (this.timestamp ?? timestamp)) / 1000;
    this.timestamp = timestamp;
    const target = this.phase === "held" ? HISTORY_HOLD_PX : 0;
    // Exact damped-oscillator solution stays stable across slow or suspended frames.
    const decay = FREQUENCY * DAMPING_RATIO;
    const frequency = FREQUENCY * Math.sqrt(1 - DAMPING_RATIO ** 2);
    const displacement = this.distance - target;
    const sine = (this.velocity + decay * displacement) / frequency;
    const phase = frequency * seconds;
    const envelope = Math.exp(-decay * seconds);
    this.distance = Math.min(HISTORY_PULL_LIMIT_PX, Math.max(0,
      target + envelope * (displacement * Math.cos(phase) + sine * Math.sin(phase)),
    ));
    this.velocity = Math.min(MAX_SPEED, Math.max(-MAX_SPEED, envelope * (
      (sine * frequency - decay * displacement) * Math.cos(phase)
      - (displacement * frequency + decay * sine) * Math.sin(phase)
    )));
    // A hard boundary removes outward momentum, rather than hiding an overshooting spring.
    if (this.distance === 0) this.velocity = Math.max(0, this.velocity);
    if (this.distance === HISTORY_PULL_LIMIT_PX) this.velocity = Math.min(0, this.velocity);
    const settled = Math.abs(this.distance - target) < 0.08 && Math.abs(this.velocity) < 0.8;
    if (settled) {
      this.distance = target;
      this.finish();
    }
    this.publish();
    if (!settled) this.frame = this.scheduler.request(this.advance);
  };
}
