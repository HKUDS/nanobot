import type {
  ThreadCameraController,
  ThreadCameraFollowResult,
} from "@/components/thread/thread-camera";

export type ThreadMotionMode =
  | "idle"
  | "anchor-prompt"
  | "follow-output"
  | "user-controlled";

export interface ThreadMotionGeometry {
  scrollTop: number;
  scrollHeight: number;
  clientHeight: number;
  maxScrollTop: number;
  composerHeight: number;
  promptTop: number | null;
}

export interface ThreadMotionTurn {
  id: string | null;
  promptId: string | null;
  hasOutput: boolean;
  entry?: "submitted" | "restored";
}

export interface ThreadMotionSnapshot {
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
  | "jumpTo"
  | "navigateTo"
>;

interface ThreadMotionCoordinatorOptions {
  camera: ThreadMotionCamera;
  measure: (promptId: string | null) => ThreadMotionGeometry | null;
  onGeometry?: (geometry: ThreadMotionGeometry) => void;
  onAutoFollow?: (result: ThreadCameraFollowResult) => void;
  scheduler?: ThreadMotionScheduler;
}

const GEOMETRY_EPSILON_PX = 0.5;

export type ThreadScrollOwner = "automatic" | "user";

function defaultScheduler(): ThreadMotionScheduler {
  return {
    request: (callback) => window.requestAnimationFrame(callback),
    cancel: (id) => window.cancelAnimationFrame(id),
  };
}

/**
 * Owns the policy that turns discrete layout events into continuous camera
 * motion. Callers only invalidate geometry; one display frame coalesces those
 * notifications, reads the authoritative layout, and retargets the camera.
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
      this.clearTurn();
      this.invalidateGeometry();
      return;
    }

    const isNewTurn = this.turn.id !== turn.id;
    this.turn = turn;
    if (isNewTurn) {
      this.camera.cancel();
      this.promptPositioned = turn.entry === "restored";
      this.mode = this.promptPositioned && turn.hasOutput
        ? "follow-output"
        : "anchor-prompt";
    } else if (this.mode !== "user-controlled" && this.promptPositioned) {
      this.mode = turn.hasOutput ? "follow-output" : "anchor-prompt";
    }
    this.invalidateGeometry();
  }

  invalidateGeometry(): void {
    this.geometryDirty = true;
    if (this.measurementFrameId !== null) return;
    this.measurementFrameId = this.scheduler.request(this.flushGeometry);
  }

  takeUserControl(): void {
    this.camera.cancel();
    this.mode = "user-controlled";
  }

  resumeAutoFollow(): void {
    if (this.mode !== "user-controlled") return;
    this.mode = this.turn.id
      ? this.promptPositioned && this.turn.hasOutput
        ? "follow-output"
        : "anchor-prompt"
      : "idle";
    this.invalidateGeometry();
  }

  jumpTo(top: number): void {
    this.camera.jumpTo(top);
  }

  animateTo(top: number): ThreadCameraFollowResult | null {
    return this.camera.navigateTo(top);
  }

  isUserControlled(): boolean {
    return this.mode === "user-controlled";
  }

  /**
   * A scroll event reports geometry; it does not prove user intent. Explicit
   * input handlers call takeUserControl() before the browser scrolls. Layout,
   * sticky positioning, and camera writes therefore remain automatic even
   * when the browser emits an intermediate scroll event for them.
   */
  observeScroll(nearBottom: boolean): ThreadScrollOwner {
    if (this.mode !== "user-controlled") {
      if (!nearBottom) this.invalidateGeometry();
      return "automatic";
    }
    if (!nearBottom) return "user";
    this.resumeAutoFollow();
    return "automatic";
  }

  reset(): void {
    if (this.measurementFrameId !== null) {
      this.scheduler.cancel(this.measurementFrameId);
      this.measurementFrameId = null;
    }
    this.geometryDirty = false;
    this.camera.cancel();
    this.turn = { id: null, promptId: null, hasOutput: false };
    this.mode = "idle";
    this.promptPositioned = false;
  }

  dispose(): void {
    this.reset();
    this.camera.dispose();
  }

  private clearTurn(): void {
    const hadActiveTurn = this.turn.id !== null;
    if (hadActiveTurn) this.camera.cancel();
    this.turn = { id: null, promptId: null, hasOutput: false };
    if (this.mode !== "user-controlled") this.mode = "idle";
    this.promptPositioned = false;
  }

  private readonly flushGeometry = (): void => {
    this.measurementFrameId = null;
    if (!this.geometryDirty) return;
    this.geometryDirty = false;

    const needsPromptGeometry =
      this.mode !== "user-controlled"
      && this.turn.id !== null
      && !this.promptPositioned;
    const geometry = this.measure(needsPromptGeometry ? this.turn.promptId : null);
    if (!geometry) return;
    this.onGeometry?.(geometry);

    if (this.mode === "user-controlled" || !this.turn.id) return;
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
      // position with zero hidden downward travel. Once output exists, start
      // from the prompt origin and let the follow camera reveal its growth.
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
    const target = geometry.maxScrollTop;
    const result = this.camera.followTo(target);
    if (
      result
      && (
        Math.abs(target - geometry.scrollTop) > GEOMETRY_EPSILON_PX
        || result.kind === "retargeted"
      )
    ) {
      this.onAutoFollow?.(result);
    }
  };
}
