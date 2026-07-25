import {
  ThreadCameraController,
  type ThreadCameraScheduler,
} from "@/components/thread/thread-camera";

type ThreadWheelInputMode = "idle" | "native" | "smooth";

interface ThreadWheelControllerOptions {
  getViewport: () => HTMLElement | null;
  onUserIntent: (canScroll: boolean) => void;
  scheduler?: ThreadCameraScheduler;
  prefersReducedMotion?: () => boolean;
}

type LegacyWheelEvent = WheelEvent & {
  wheelDelta?: number;
  wheelDeltaY?: number;
};

const WHEEL_DELTA_PIXEL = 0;
const WHEEL_DELTA_LINE = 1;
const WHEEL_DELTA_PAGE = 2;
const DEFAULT_LINE_HEIGHT_PX = 16;
const SCROLL_BOUNDARY_EPSILON_PX = 0.5;
const COARSE_DELTA_THRESHOLD_PX = 36;
const WHEEL_GESTURE_GAP_MS = 90;

const THREAD_WHEEL_CAMERA_MOTION = {
  responseTimeMs: 110,
  maxSpeedPxPerSecond: 3_200,
  settleDistancePx: 0.5,
  maxFrameDeltaMs: 40,
} as const;

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

function maxScrollTop(viewport: HTMLElement): number {
  return Math.max(0, viewport.scrollHeight - viewport.clientHeight);
}

function canScroll(viewport: HTMLElement, deltaY: number): boolean {
  if (deltaY < 0) return viewport.scrollTop > SCROLL_BOUNDARY_EPSILON_PX;
  if (deltaY > 0) {
    return viewport.scrollTop
      < maxScrollTop(viewport) - SCROLL_BOUNDARY_EPSILON_PX;
  }
  return false;
}

function normalizedDeltaY(event: WheelEvent, viewport: HTMLElement): number {
  switch (event.deltaMode) {
    case WHEEL_DELTA_LINE: {
      const parsedLineHeight = Number.parseFloat(
        window.getComputedStyle(viewport).lineHeight,
      );
      const lineHeight = Number.isFinite(parsedLineHeight)
        ? parsedLineHeight
        : DEFAULT_LINE_HEIGHT_PX;
      return event.deltaY * lineHeight;
    }
    case WHEEL_DELTA_PAGE:
      return event.deltaY * viewport.clientHeight;
    case WHEEL_DELTA_PIXEL:
    default:
      return event.deltaY;
  }
}

function isDiscreteWheel(event: WheelEvent, deltaY: number): boolean {
  if (event.deltaMode !== WHEEL_DELTA_PIXEL) return true;
  const legacyEvent = event as LegacyWheelEvent;
  const legacyDelta = legacyEvent.wheelDeltaY ?? legacyEvent.wheelDelta;
  if (
    legacyDelta !== undefined
    && Math.abs(legacyDelta) >= 120
    && Math.abs(legacyDelta) % 120 === 0
  ) {
    return true;
  }
  return (
    Number.isInteger(event.deltaY)
    && Math.abs(deltaY) >= COARSE_DELTA_THRESHOLD_PX
  );
}

function nestedScrollerConsumes(
  target: EventTarget | null,
  boundary: HTMLElement,
  deltaY: number,
): boolean {
  let element = target instanceof Element ? target : null;
  while (element && element !== boundary) {
    if (
      element instanceof HTMLElement
      && element.scrollHeight > element.clientHeight + 1
    ) {
      const style = window.getComputedStyle(element);
      const scrollable = /^(auto|scroll|overlay)$/.test(style.overflowY);
      if (scrollable && canScroll(element, deltaY)) return true;
      if (
        scrollable
        && /^(contain|none)$/.test(style.overscrollBehaviorY)
      ) {
        return true;
      }
    }
    element = element.parentElement;
  }
  return false;
}

/**
 * Turns detented wheel steps into one retargetable camera chase. Precision
 * touchpads remain native so their OS-level momentum is not filtered twice.
 */
export class ThreadWheelController {
  private readonly getViewport: ThreadWheelControllerOptions["getViewport"];
  private readonly onUserIntent: ThreadWheelControllerOptions["onUserIntent"];
  private readonly scheduler: ThreadCameraScheduler;
  private readonly prefersReducedMotion: () => boolean;
  private readonly camera: ThreadCameraController;
  private inputMode: ThreadWheelInputMode = "idle";
  private lastInputAt = Number.NEGATIVE_INFINITY;
  private target = 0;

  constructor(options: ThreadWheelControllerOptions) {
    this.getViewport = options.getViewport;
    this.onUserIntent = options.onUserIntent;
    this.scheduler = options.scheduler ?? defaultScheduler();
    this.prefersReducedMotion =
      options.prefersReducedMotion ?? defaultPrefersReducedMotion;
    this.camera = new ThreadCameraController(this.getViewport, {
      scheduler: this.scheduler,
      motion: THREAD_WHEEL_CAMERA_MOTION,
      reducedMotion: THREAD_WHEEL_CAMERA_MOTION,
      prefersReducedMotion: this.prefersReducedMotion,
    });
  }

  handle(event: WheelEvent): boolean {
    if (
      event.defaultPrevented
      || event.ctrlKey
      || event.shiftKey
      || Math.abs(event.deltaY) <= Math.abs(event.deltaX)
    ) {
      return false;
    }

    const viewport = this.getViewport();
    if (!viewport) return false;
    const deltaY = normalizedDeltaY(event, viewport);
    if (Math.abs(deltaY) <= SCROLL_BOUNDARY_EPSILON_PX) return false;

    const now = this.scheduler.now();
    if (nestedScrollerConsumes(event.target, viewport, deltaY)) {
      this.useNativeInput(now);
      return false;
    }

    const scrollable = canScroll(viewport, deltaY);
    this.onUserIntent(scrollable);
    if (!scrollable) {
      this.camera.cancel();
      return false;
    }

    const mode = this.resolveInputMode(event, deltaY, now);
    if (
      mode === "native"
      || !event.cancelable
      || this.prefersReducedMotion()
    ) {
      this.useNativeInput(now);
      return false;
    }

    event.preventDefault();
    const current = viewport.scrollTop;
    if (!this.camera.isFollowing()) this.target = current;
    if (
      Math.abs(this.target - current) > SCROLL_BOUNDARY_EPSILON_PX
      && Math.sign(this.target - current) !== Math.sign(deltaY)
    ) {
      this.target = current;
    }
    this.target = Math.max(
      0,
      Math.min(maxScrollTop(viewport), this.target + deltaY),
    );
    this.camera.followTo(this.target);
    return true;
  }

  cancel(): void {
    this.camera.cancel();
    this.inputMode = "idle";
    this.lastInputAt = Number.NEGATIVE_INFINITY;
  }

  dispose(): void {
    this.camera.dispose();
  }

  private resolveInputMode(
    event: WheelEvent,
    deltaY: number,
    now: number,
  ): ThreadWheelInputMode {
    const continuesGesture =
      this.inputMode !== "idle"
      && now - this.lastInputAt <= WHEEL_GESTURE_GAP_MS;
    if (!continuesGesture) {
      this.inputMode = isDiscreteWheel(event, deltaY) ? "smooth" : "native";
    }
    this.lastInputAt = now;
    return this.inputMode;
  }

  private useNativeInput(now: number): void {
    this.camera.cancel();
    this.inputMode = "native";
    this.lastInputAt = now;
  }
}
