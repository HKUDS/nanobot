import type {
  ThreadCameraController,
  ThreadCameraFollowResult,
} from "@/components/thread/thread-camera";

type ThreadMotionMode =
  | "idle"
  | "anchor-prompt"
  | "follow-output"
  | "follow-completion"
  | "navigating-latest"
  | "navigating-history"
  | "browsing-history";

type AutomaticThreadMotionMode =
  | "idle"
  | "anchor-prompt"
  | "follow-output";

type ThreadMotionEvent =
  | "navigate-latest"
  | "navigate-history"
  | "navigation-settled"
  | "user-scroll"
  | "boundary-scroll"
  | "composer-input"
  | "turn-completed"
  | "resume-follow";

type ThreadMotionTransition = ThreadMotionMode | "current-automatic-mode";

const THREAD_MOTION_TRANSITIONS: Readonly<
  Record<
    ThreadMotionMode,
    Readonly<Partial<Record<ThreadMotionEvent, ThreadMotionTransition>>>
  >
> = {
  idle: {
    "navigate-latest": "navigating-latest",
    "navigate-history": "navigating-history",
    "user-scroll": "browsing-history",
  },
  "anchor-prompt": {
    "navigate-latest": "navigating-latest",
    "navigate-history": "navigating-history",
    "user-scroll": "browsing-history",
    "turn-completed": "follow-completion",
  },
  "follow-output": {
    "navigate-latest": "navigating-latest",
    "navigate-history": "navigating-history",
    "user-scroll": "browsing-history",
    "turn-completed": "follow-completion",
  },
  "follow-completion": {
    "navigate-latest": "navigating-latest",
    "navigate-history": "navigating-history",
    "user-scroll": "browsing-history",
    "composer-input": "idle",
  },
  "navigating-latest": {
    "navigate-latest": "navigating-latest",
    "navigate-history": "navigating-history",
    "navigation-settled": "current-automatic-mode",
    "user-scroll": "browsing-history",
    "boundary-scroll": "browsing-history",
    "resume-follow": "current-automatic-mode",
  },
  "navigating-history": {
    "navigate-latest": "navigating-latest",
    "navigate-history": "navigating-history",
    "navigation-settled": "browsing-history",
    "user-scroll": "browsing-history",
    "boundary-scroll": "browsing-history",
    "resume-follow": "current-automatic-mode",
  },
  "browsing-history": {
    "navigate-latest": "navigating-latest",
    "navigate-history": "navigating-history",
    "resume-follow": "current-automatic-mode",
  },
};

export interface ThreadMotionGeometry {
  scrollTop: number;
  scrollHeight: number;
  clientHeight: number;
  maxScrollTop: number;
  composerHeight: number;
  promptTop: number | null;
}

interface ThreadMotionTurn {
  id: string | null;
  promptId: string | null;
  hasOutput: boolean;
  entry?: "submitted" | "restored";
}

interface ThreadMotionSnapshot {
  mode: ThreadMotionMode;
  turnId: string | null;
  promptId: string | null;
  promptPositioned: boolean;
  measurementPending: boolean;
}

export interface ThreadMotionScheduler {
  request: (callback: FrameRequestCallback) => number;
  cancel: (id: number) => void;
}

type ThreadMotionCamera = Pick<
  ThreadCameraController,
  | "cancel"
  | "dispose"
  | "followTo"
  | "isFollowing"
  | "jumpTo"
  | "navigateTo"
>;

interface ThreadMotionCoordinatorOptions {
  camera: ThreadMotionCamera;
  measure: (promptId: string | null) => ThreadMotionGeometry | null;
  onGeometry?: (geometry: ThreadMotionGeometry) => void;
  onAutoFollow?: () => void;
  scheduler?: ThreadMotionScheduler;
}

const GEOMETRY_EPSILON_PX = 0.5;

type ThreadScrollOwner = "automatic" | "navigation" | "user";

function defaultScheduler(): ThreadMotionScheduler {
  return {
    request: (callback) => window.requestAnimationFrame(callback),
    cancel: (id) => window.cancelAnimationFrame(id),
  };
}

/**
 * Owns the policy that turns discrete layout events into automatic tail
 * pinning or explicit camera navigation. Callers only invalidate geometry;
 * one display frame coalesces those notifications and reads the authoritative
 * layout before applying either policy.
 */
export class ThreadMotionCoordinator {
  private readonly camera: ThreadMotionCamera;
  private readonly measure: ThreadMotionCoordinatorOptions["measure"];
  private readonly onGeometry?: ThreadMotionCoordinatorOptions["onGeometry"];
  private readonly onAutoFollow?: ThreadMotionCoordinatorOptions["onAutoFollow"];
  private readonly scheduler: ThreadMotionScheduler;
  private turn: ThreadMotionTurn = {
    id: null,
    promptId: null,
    hasOutput: false,
  };
  private mode: ThreadMotionMode = "idle";
  private promptPositioned = false;
  private measurementFrameId: number | null = null;
  private geometryDirty = false;
  private composerInputDuringTurn = false;

  constructor(options: ThreadMotionCoordinatorOptions) {
    this.camera = options.camera;
    this.measure = options.measure;
    this.onGeometry = options.onGeometry;
    this.onAutoFollow = options.onAutoFollow;
    this.scheduler = options.scheduler ?? defaultScheduler();
  }

  snapshot(): ThreadMotionSnapshot {
    return {
      mode: this.mode,
      turnId: this.turn.id,
      promptId: this.turn.promptId,
      promptPositioned: this.promptPositioned,
      measurementPending: this.measurementFrameId !== null,
    };
  }

  updateTurn(turn: ThreadMotionTurn): void {
    if (!turn.id) {
      this.completeTurn();
      return;
    }

    const isNewTurn = this.turn.id !== turn.id;
    this.turn = turn;
    if (isNewTurn) {
      this.camera.cancel();
      this.composerInputDuringTurn = false;
      this.promptPositioned = turn.entry === "restored";
      this.mode = this.promptPositioned && turn.hasOutput
        ? "follow-output"
        : "anchor-prompt";
    } else if (!this.isHistoryMode() && this.promptPositioned) {
      this.mode = turn.hasOutput ? "follow-output" : "anchor-prompt";
    }
    this.invalidateGeometry();
  }

  completeTurn(): void {
    if (!this.turn.id) {
      this.invalidateGeometry();
      return;
    }
    // Protocol completion can share a React commit with the last large text
    // batch and begins the run-drawer exit. Keep camera ownership through
    // those final layout changes; only a new turn, explicit user navigation,
    // or input for the next prompt may end completion follow.
    this.transition("turn-completed");
    if (
      this.composerInputDuringTurn
      && this.transition("composer-input")
    ) {
      this.camera.cancel();
    }
    this.turn = { id: null, promptId: null, hasOutput: false };
    this.composerInputDuringTurn = false;
    this.promptPositioned = false;
    this.invalidateGeometry();
  }

  invalidateGeometry(): void {
    this.geometryDirty = true;
    if (this.measurementFrameId !== null) return;
    this.measurementFrameId = this.scheduler.request(this.flushGeometry);
  }

  handleComposerInput(): void {
    // Input and protocol completion can arrive in either order. Remember
    // editing that starts just before turn_end so the completion drawer
    // cannot reacquire the camera a few milliseconds later.
    if (this.turn.id) this.composerInputDuringTurn = true;
    if (!this.transition("composer-input")) return;
    this.camera.cancel();
  }

  takeUserControl(): void {
    this.handleUserScrollIntent(true);
  }

  handleUserScrollIntent(canScroll: boolean): void {
    const event = canScroll ? "user-scroll" : "boundary-scroll";
    if (!this.transition(event)) return;
    this.camera.cancel();
  }

  resumeAutoFollow(): void {
    if (!this.transition("resume-follow")) return;
    this.camera.cancel();
    this.invalidateGeometry();
  }

  jumpTo(top: number): void {
    this.camera.jumpTo(top);
  }

  /**
   * Explicitly navigate to the live tail while allowing authoritative layout
   * frames to retarget that destination as streamed output continues to grow.
   */
  navigateLatestTo(top: number): ThreadCameraFollowResult | null {
    this.camera.cancel();
    this.transition("navigate-latest");
    const result = this.camera.navigateTo(top);
    if (!result || result === "settled") {
      this.settleLatestNavigation();
    }
    return result;
  }

  navigateHistoryTo(top: number): ThreadCameraFollowResult | null {
    this.camera.cancel();
    this.transition("navigate-history");
    const result = this.camera.navigateTo(top);
    if (!result || result === "settled") {
      this.transition("navigation-settled");
    }
    return result;
  }

  isAutoFollowPaused(): boolean {
    return this.isHistoryMode();
  }

  isBrowsingHistory(): boolean {
    return this.mode === "browsing-history";
  }

  /**
   * A scroll event reports geometry; it does not prove user intent. Explicit
   * input handlers call takeUserControl() before the browser scrolls. Layout,
   * sticky positioning, and camera writes therefore remain automatic even
   * when the browser emits an intermediate scroll event for them.
   */
  observeScroll(nearBottom: boolean): ThreadScrollOwner {
    switch (this.mode) {
      case "navigating-latest":
        if (!this.camera.isFollowing()) {
          if (nearBottom) {
            this.settleLatestNavigation();
          } else {
            this.invalidateGeometry();
          }
        }
        return "navigation";
      case "navigating-history":
        if (!this.camera.isFollowing()) {
          this.transition("navigation-settled");
          if (nearBottom) this.resumeAutoFollow();
        }
        return "navigation";
      case "browsing-history":
        if (!nearBottom) return "user";
        this.resumeAutoFollow();
        return "automatic";
      default:
        if (!nearBottom) this.invalidateGeometry();
        return "automatic";
    }
  }

  reset(): void {
    if (this.measurementFrameId !== null) {
      this.scheduler.cancel(this.measurementFrameId);
      this.measurementFrameId = null;
    }
    this.geometryDirty = false;
    this.camera.cancel();
    this.turn = { id: null, promptId: null, hasOutput: false };
    this.composerInputDuringTurn = false;
    this.mode = "idle";
    this.promptPositioned = false;
  }

  dispose(): void {
    this.reset();
    this.camera.dispose();
  }

  private isHistoryMode(): boolean {
    return (
      this.mode === "navigating-latest"
      || this.mode === "navigating-history"
      || this.mode === "browsing-history"
    );
  }

  private automaticMode(): AutomaticThreadMotionMode {
    if (!this.turn.id) return "idle";
    return this.promptPositioned && this.turn.hasOutput
      ? "follow-output"
      : "anchor-prompt";
  }

  private transition(event: ThreadMotionEvent): boolean {
    const transition = THREAD_MOTION_TRANSITIONS[this.mode][event];
    if (!transition) return false;
    const nextMode =
      transition === "current-automatic-mode"
        ? this.automaticMode()
        : transition;
    if (nextMode === this.mode) return false;
    this.mode = nextMode;
    return true;
  }

  private followGeometry(geometry: ThreadMotionGeometry): void {
    const target = geometry.maxScrollTop;
    const result = this.camera.followTo(target);
    if (
      result
      && Math.abs(target - geometry.scrollTop) > GEOMETRY_EPSILON_PX
    ) {
      this.onAutoFollow?.();
    }
  }

  private settleLatestNavigation(): void {
    if (!this.transition("navigation-settled")) return;
    this.invalidateGeometry();
  }

  private readonly flushGeometry = (): void => {
    this.measurementFrameId = null;
    if (!this.geometryDirty) return;
    this.geometryDirty = false;

    const needsPromptGeometry =
      !this.isHistoryMode()
      && this.turn.id !== null
      && !this.promptPositioned;
    const geometry = this.measure(needsPromptGeometry ? this.turn.promptId : null);
    if (!geometry) return;
    this.onGeometry?.(geometry);

    if (this.mode === "navigating-latest") {
      const result = this.camera.navigateTo(geometry.maxScrollTop);
      if (!result || result === "settled") {
        this.settleLatestNavigation();
      }
      return;
    }
    if (this.mode === "follow-completion") {
      this.followGeometry(geometry);
      return;
    }
    if (this.isHistoryMode() || !this.turn.id) return;
    if (!this.turn.promptId && this.turn.entry !== "restored") {
      this.mode = "anchor-prompt";
      return;
    }

    if (!this.promptPositioned) {
      if (geometry.promptTop === null) {
        this.mode = "anchor-prompt";
        return;
      }
      // Before output exists, the real lower scroll boundary is the only
      // position with zero hidden downward travel. Once output exists, first
      // establish the prompt origin; automatic follow below then resolves the
      // current tail in this same authoritative geometry frame.
      this.camera.jumpTo(
        this.turn.hasOutput ? geometry.promptTop : geometry.maxScrollTop,
      );
      this.promptPositioned = true;
    } else if (
      !this.turn.hasOutput
      && Math.abs(geometry.maxScrollTop - geometry.scrollTop)
        > GEOMETRY_EPSILON_PX
    ) {
      // Hero docking, the run drawer, fonts, and responsive chrome can all
      // change document height while the model is still silent. Every
      // authoritative geometry frame reasserts the real lower boundary so no
      // stale downward scroll pocket survives a layout transition.
      this.camera.jumpTo(geometry.maxScrollTop);
    }

    if (!this.turn.hasOutput) {
      this.mode = "anchor-prompt";
      return;
    }

    this.mode = "follow-output";
    this.followGeometry(geometry);
  };
}
