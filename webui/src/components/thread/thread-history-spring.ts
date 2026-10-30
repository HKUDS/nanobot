import { animate, motionValue, type AnimationPlaybackControls, type MotionValue } from "motion";

export const HISTORY_PULL_LIMIT_PX = 80;
export const HISTORY_HOLD_PX = 48;
export const HISTORY_PULL_TRIGGER_PX = 56;
const RESISTANCE_LENGTH_PX = 120;

export type HistoryRevealPhase = "hidden" | "feedback" | "held";

interface HistorySpringOptions {
  onUpdate: (distance: number) => void;
  onPhaseChange: (phase: HistoryRevealPhase) => void;
  prefersReducedMotion?: () => boolean;
}

/** Presentation only: Motion owns spring integration; the thread camera remains the sole scroll-position owner. */
export class ThreadHistorySpring {
  private readonly options: HistorySpringOptions;
  private readonly reducedMotion: () => boolean;
  private readonly value: MotionValue<number> = motionValue(0);
  private animation: AnimationPlaybackControls | null = null;
  private destination: number | null = null;
  private animationGeneration = 0;
  private phase: HistoryRevealPhase = "hidden";
  private dragging = false;
  private travel = 0;
  private wheelLatched = false;

  constructor(options: HistorySpringOptions) {
    this.options = options;
    const preference = typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
    this.reducedMotion = options.prefersReducedMotion ?? (() => preference?.matches ?? false);
    this.value.on("change", this.publish);
  }

  hold(): void {
    this.wheelLatched = true;
    this.setPhase("held");
    this.animateTo(HISTORY_HOLD_PX);
  }

  wheel(travel: number): boolean {
    if (this.dragging || travel === 0) return false;
    const first = !this.wheelLatched && travel > 0;
    if (travel > 0) {
      this.wheelLatched = true;
      if (this.phase !== "held") this.setPhase("feedback");
    }
    const pressure = 1 - Math.exp(-Math.abs(travel) / RESISTANCE_LENGTH_PX);
    const current = this.boundedValue();
    const pressured = current + ((travel > 0 ? HISTORY_PULL_LIMIT_PX : 0) - current) * pressure;
    // Each packet retargets the same MotionValue; interruption keeps the live spring velocity.
    this.animateTo(Math.max(0, Math.min(HISTORY_PULL_LIMIT_PX, pressured)));
    return first;
  }

  startTouch(): void {
    this.stopAnimation();
    const visible = this.boundedValue();
    this.value.set(visible);
    this.dragging = true;
    if (this.phase !== "held") this.setPhase("feedback");
    this.travel = -RESISTANCE_LENGTH_PX * Math.log(Math.max(Number.EPSILON, 1 - visible / HISTORY_PULL_LIMIT_PX));
  }

  moveTouch(travel: number): void {
    if (!this.dragging) return;
    this.travel = Math.max(0, this.travel + travel);
    this.value.set(HISTORY_PULL_LIMIT_PX * (1 - Math.exp(-this.travel / RESISTANCE_LENGTH_PX)));
  }

  endTouch(cancelled = false): boolean {
    if (!this.dragging) return false;
    const triggered = !cancelled && this.boundedValue() >= HISTORY_PULL_TRIGGER_PX;
    this.dragging = false;
    this.travel = 0;
    this.animateTo(this.restPosition());
    return triggered;
  }

  /** Native scrolling releases this input round, not the committed reveal. */
  leaveBoundary(): void {
    this.dragging = false;
    this.wheelLatched = false;
    if (this.reducedMotion() && this.phase !== "held") {
      this.stopAnimation();
      this.value.set(0);
      this.setPhase("hidden");
      return;
    }
    this.animateTo(this.restPosition());
  }

  reset(): void {
    this.stopAnimation();
    this.dragging = false;
    this.travel = 0;
    this.wheelLatched = false;
    this.setPhase("hidden");
    this.value.set(0);
  }

  private readonly publish = (distance: number): void => {
    const bounded = Math.max(0, Math.min(HISTORY_PULL_LIMIT_PX, distance));
    this.options.onUpdate(this.phase !== "held" && this.reducedMotion() ? 0 : bounded);
  };

  private boundedValue(): number {
    return Math.max(0, Math.min(HISTORY_PULL_LIMIT_PX, this.value.get()));
  }

  private restPosition(): number {
    return this.phase === "held" ? HISTORY_HOLD_PX : 0;
  }

  private setPhase(phase: HistoryRevealPhase): void {
    if (this.phase === phase) return;
    this.phase = phase;
    this.options.onPhaseChange(phase);
  }

  private stopAnimation(): void {
    this.animationGeneration++;
    this.animation?.stop();
    this.animation = null;
    this.destination = null;
  }

  private animateTo(target: number): void {
    if (this.dragging) return;
    const next = Math.max(0, Math.min(HISTORY_PULL_LIMIT_PX, target));
    if (this.destination === next && this.animation) return;
    if (this.reducedMotion() && this.phase === "held") {
      this.stopAnimation();
      this.value.set(HISTORY_HOLD_PX);
      return;
    }
    if (Math.abs(this.value.get() - next) < 0.01) {
      this.stopAnimation();
      this.value.set(next);
      this.finish(next, this.animationGeneration);
      return;
    }
    const generation = ++this.animationGeneration;
    this.destination = next;
    this.animation = animate(this.value, next, {
      type: "spring",
      stiffness: 484,
      damping: 34,
      mass: 1,
      onComplete: () => this.finish(next, generation),
    });
  }

  private finish(destination: number, generation: number): void {
    if (generation !== this.animationGeneration) return;
    this.animation = null;
    this.destination = null;
    this.value.set(destination);
    if (destination !== this.restPosition()) {
      this.animateTo(this.restPosition());
      return;
    }
    if (destination === 0 && this.phase !== "held") {
      this.wheelLatched = false;
      this.setPhase("hidden");
    }
  }
}
