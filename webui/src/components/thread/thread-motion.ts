import type {
  ThreadCameraController,
  ThreadCameraFollowResult,
} from "@/components/thread/thread-camera";

type ThreadMotionMode =
  | "idle"
  | "follow-latest"
  | "anchor-prompt"
  | "reading-prompt"
  | "navigating-latest"
  | "navigating-history"
  | "browsing-history";

type AutomaticThreadMotionMode = "idle" | "follow-latest";

type ThreadMotionEvent =
  | "navigate-latest"
  | "navigate-history"
  | "navigation-settled"
  | "user-scroll"
  | "boundary-scroll"
  | "composer-input"
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
    "resume-follow": "current-automatic-mode",
  },
  "follow-latest": {
    "navigate-latest": "navigating-latest",
    "navigate-history": "navigating-history",
    "user-scroll": "browsing-history",
  },
  "anchor-prompt": {
    "navigate-latest": "navigating-latest",
    "navigate-history": "navigating-history",
    "user-scroll": "browsing-history",
    "boundary-scroll": "browsing-history",
  },
  "reading-prompt": {
    "navigate-latest": "navigating-latest",
    "navigate-history": "navigating-history",
    "user-scroll": "browsing-history",
    "boundary-scroll": "browsing-history",
    "resume-follow": "current-automatic-mode",
  },
  "navigating-latest": {
    "navigate-latest": "navigating-latest",
    "navigate-history": "navigating-history",
    "navigation-settled": "current-automatic-mode",
    "user-scroll": "browsing-history",
    "boundary-scroll": "browsing-history",
    "composer-input": "idle",
    "resume-follow": "current-automatic-mode",
  },
  "navigating-history": {
    "navigate-latest": "navigating-latest",
    "navigate-history": "navigating-history",
    "navigation-settled": "browsing-history",
    "user-scroll": "browsing-history",
    "boundary-scroll": "browsing-history",
    "composer-input": "browsing-history",
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

interface ThreadMotionSnapshot {
  mode: ThreadMotionMode;
}

export interface ThreadMotionScheduler {
  request: (callback: FrameRequestCallback) => number;
  cancel: (id: number) => void;
}

type ThreadMotionCamera = Pick<
  ThreadCameraController,
  | "cancel"
  | "dispose"
  | "isFollowing"
  | "jumpTo"
  | "navigateTo"
  | "observeScroll"
  | "reset"
>;

interface ThreadMotionCoordinatorOptions {
  camera: ThreadMotionCamera;
  measure: (promptId: string | null, submitted?: boolean) => ThreadMotionGeometry | null;
  onGeometry?: (geometry: ThreadMotionGeometry) => void;
  onAutoFollow?: () => void;
  onLatestNavigationSettled?: () => void;
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
 * Owns the policy that turns layout events into automatic tail pinning or
 * explicit camera navigation. Discrete notifications are coalesced into one
 * display frame. ResizeObserver deliveries reconcile immediately because they
 * already carry the browser's authoritative layout and run before paint.
 */
export class ThreadMotionCoordinator {
  private readonly camera: ThreadMotionCamera;
  private readonly measure: ThreadMotionCoordinatorOptions["measure"];
  private readonly onGeometry?: ThreadMotionCoordinatorOptions["onGeometry"];
  private readonly onAutoFollow?: ThreadMotionCoordinatorOptions["onAutoFollow"];
  private readonly onLatestNavigationSettled?: () => void;
  private readonly scheduler: ThreadMotionScheduler;
  private turnId: string | null = null;
  private mode: ThreadMotionMode = "idle";
  private historyNavigationPromptId: string | null = null;
  private submittedPromptId: string | null = null;
  private measurementFrameId: number | null = null;
  private geometryDirty = false;
  // Only input toward latest may resume follow; layout can also return a
  // reading position to the tail without the user scrolling forward.
  private resumeFollowArmed = false;

  constructor(options: ThreadMotionCoordinatorOptions) {
    this.camera = options.camera;
    this.measure = options.measure;
    this.onGeometry = options.onGeometry;
    this.onAutoFollow = options.onAutoFollow;
    this.onLatestNavigationSettled = options.onLatestNavigationSettled;
    this.scheduler = options.scheduler ?? defaultScheduler();
  }

  snapshot(): ThreadMotionSnapshot {
    return { mode: this.mode };
  }

  updateTurn(turnId: string | null): void {
    if (this.turnId === turnId) return;
    this.turnId = turnId;
    // Opening a running conversation still positions its initial history once,
    // but subsequent output must not keep pulling the reader to the tail.
    if (turnId && this.mode === "follow-latest") {
      this.camera.cancel();
      this.mode = "idle";
    }
    this.invalidateGeometry();
  }

  followOpeningLayout(): void {
    if (this.mode !== "idle") return;
    this.mode = "follow-latest";
    this.invalidateGeometry();
  }

  finishOpeningLayout(): void {
    if (this.mode !== "follow-latest") return;
    this.camera.cancel();
    this.mode = "idle";
  }

  anchorSubmittedPrompt(promptId: string): void {
    this.camera.reset();
    this.resumeFollowArmed = false;
    this.submittedPromptId = promptId;
    this.mode = "anchor-prompt";
    this.invalidateGeometry();
  }

  updateSubmittedPromptId(promptId: string): void {
    if (!this.isPromptMode() || this.submittedPromptId === promptId) return;
    this.submittedPromptId = promptId;
    this.invalidateGeometry();
  }

  invalidateGeometry(): void {
    this.geometryDirty = true;
    if (this.measurementFrameId !== null) return;
    this.measurementFrameId = this.scheduler.request(this.flushGeometry);
  }

  reconcileObservedGeometry(): void {
    if (this.measurementFrameId !== null) {
      this.scheduler.cancel(this.measurementFrameId);
      this.measurementFrameId = null;
    }
    this.geometryDirty = true;
    this.flushGeometry();
  }

  handleComposerInput(): void {
    if (!this.transition("composer-input")) return;
    this.camera.cancel();
  }

  takeUserControl(): void {
    this.handleUserScrollIntent(true);
  }

  handleUserScrollIntent(canScroll: boolean, towardLatest = false): void {
    if (this.mode === "browsing-history" && towardLatest && !canScroll) {
      this.transitionToAutoFollow(false);
      return;
    }
    const event = canScroll ? "user-scroll" : "boundary-scroll";
    const transitioned = this.transition(event);
    if (this.mode === "browsing-history" && canScroll) {
      this.resumeFollowArmed = towardLatest;
    } else if (transitioned && this.mode === "browsing-history") {
      this.resumeFollowArmed = false;
    }
    if (!transitioned) return;
    this.camera.cancel();
  }

  resumeAutoFollow(): void {
    this.transitionToAutoFollow(true);
  }

  private transitionToAutoFollow(cancelCamera: boolean): void {
    if (!this.transition("resume-follow")) return;
    this.resumeFollowArmed = false;
    if (cancelCamera) this.camera.cancel();
    this.onAutoFollow?.();
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

  navigateHistoryToPrompt(promptId: string): ThreadCameraFollowResult | null {
    const geometry = this.measure(promptId);
    if (!geometry || geometry.promptTop === null) return null;
    return this.beginHistoryNavigation(geometry.promptTop, promptId);
  }

  private beginHistoryNavigation(top: number, promptId: string): ThreadCameraFollowResult | null {
    if (this.mode !== "navigating-history") this.camera.cancel();
    this.transition("navigate-history");
    this.historyNavigationPromptId = promptId;
    const result = this.camera.navigateTo(top);
    if (!result || result === "settled") this.transition("navigation-settled");
    return result;
  }

  cameraSettled(): void {
    if (this.mode === "anchor-prompt") {
      this.finishPromptAnchor();
    } else if (this.mode === "navigating-latest") {
      this.settleLatestNavigation();
      this.onLatestNavigationSettled?.();
    }
  }

  isAutoFollowPaused(): boolean {
    return this.isHistoryMode();
  }

  isBrowsingHistory(): boolean {
    return this.mode === "browsing-history";
  }

  private observeUserScroll(): void {
    const delta = this.camera.observeScroll();
    if (Math.abs(delta) > GEOMETRY_EPSILON_PX) this.handleUserScrollIntent(true, delta > 0);
  }

  observeScroll(nearLiveTail: boolean): ThreadScrollOwner {
    this.observeUserScroll();
    switch (this.mode) {
      case "navigating-latest":
        if (!this.camera.isFollowing()) {
          if (nearLiveTail) {
            this.settleLatestNavigation();
          } else {
            this.invalidateGeometry();
          }
        }
        return "navigation";
      case "navigating-history":
        if (!this.camera.isFollowing()) {
          this.transition("navigation-settled");
          if (nearLiveTail) {
            this.resumeAutoFollow();
          } else {
            this.resumeFollowArmed = false;
          }
        }
        return "navigation";
      case "browsing-history":
        if (!nearLiveTail) {
          this.resumeFollowArmed = false;
          return "user";
        }
        if (!this.resumeFollowArmed) return "user";
        this.resumeAutoFollow();
        return "automatic";
      default:
        if (!nearLiveTail) this.invalidateGeometry();
        return "automatic";
    }
  }

  reset(): void {
    if (this.measurementFrameId !== null) {
      this.scheduler.cancel(this.measurementFrameId);
      this.measurementFrameId = null;
    }
    this.geometryDirty = false;
    this.camera.reset();
    this.turnId = null;
    this.resumeFollowArmed = false;
    this.mode = "idle";
    this.historyNavigationPromptId = null;
    this.submittedPromptId = null;
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
    return this.turnId ? "idle" : "follow-latest";
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
    if (nextMode !== "navigating-history") this.historyNavigationPromptId = null;
    return true;
  }

  private settleLatestNavigation(): void {
    if (!this.transition("navigation-settled")) return;
    this.invalidateGeometry();
  }

  private isPromptMode(): boolean {
    return this.mode === "anchor-prompt" || this.mode === "reading-prompt";
  }

  private finishPromptAnchor(): void {
    this.mode = "reading-prompt";
  }

  private readonly flushGeometry = (): void => {
    this.measurementFrameId = null;
    if (!this.geometryDirty) return;
    this.geometryDirty = false;

    const navigationPromptId = this.mode === "navigating-history"
      ? this.historyNavigationPromptId
      : null;
    const promptId = navigationPromptId ?? (this.isPromptMode() ? this.submittedPromptId : null);
    const geometry = this.measure(promptId, this.isPromptMode());
    if (!geometry) return;
    this.observeUserScroll();
    this.onGeometry?.(geometry);

    if (this.mode === "navigating-history" && navigationPromptId !== null) {
      if (geometry.promptTop !== null) {
        const result = this.camera.navigateTo(geometry.promptTop);
        if (!result || result === "settled") this.transition("navigation-settled");
      }
      return;
    }
    if (this.mode === "navigating-latest") {
      const result = this.camera.navigateTo(geometry.maxScrollTop);
      if (!result || result === "settled") {
        this.settleLatestNavigation();
      }
      return;
    }
    if (this.mode === "follow-latest") {
      if (geometry.maxScrollTop - geometry.scrollTop > GEOMETRY_EPSILON_PX) {
        this.camera.jumpTo(geometry.maxScrollTop);
      }
      return;
    }
    if (geometry.promptTop !== null) {
      if (this.mode === "anchor-prompt") {
        const result = this.camera.navigateTo(geometry.promptTop);
        if (!result || result === "settled") this.finishPromptAnchor();
      } else if (this.mode === "reading-prompt"
        && Math.abs(geometry.promptTop - geometry.scrollTop) > GEOMETRY_EPSILON_PX) {
        // Preserve the prompt's screen position through reflow above it, not the
        // old scrollTop. Output growing below the prompt leaves this unchanged.
        this.camera.jumpTo(geometry.promptTop);
      }
    }
  };
}
