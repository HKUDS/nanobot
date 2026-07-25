import { describe, expect, it, vi } from "vitest";

import {
  ThreadMotionCoordinator,
  type ThreadMotionGeometry,
  type ThreadMotionScheduler,
} from "@/components/thread/thread-motion";

function motionHarness(initial?: Partial<ThreadMotionGeometry>) {
  let nextFrameId = 1;
  let cameraFollowing = false;
  const frames = new Map<number, FrameRequestCallback>();
  let geometry: ThreadMotionGeometry = {
    scrollTop: 400,
    scrollHeight: 1_900,
    clientHeight: 500,
    maxScrollTop: 1_400,
    composerHeight: 120,
    promptTop: 404,
    ...initial,
  };
  const scheduler: ThreadMotionScheduler = {
    request: vi.fn((callback) => {
      const id = nextFrameId;
      nextFrameId += 1;
      frames.set(id, callback);
      return id;
    }),
    cancel: vi.fn((id) => {
      frames.delete(id);
    }),
  };
  const camera = {
    cancel: vi.fn(() => {
      cameraFollowing = false;
    }),
    dispose: vi.fn(),
    jumpTo: vi.fn(),
    followTo: vi.fn(() => "started" as const),
    isFollowing: vi.fn(() => cameraFollowing),
    navigateTo: vi.fn(() => {
      cameraFollowing = true;
      return "started" as const;
    }),
  };
  const onGeometry = vi.fn();
  const onAutoFollow = vi.fn();
  const measure = vi.fn(() => geometry);
  const coordinator = new ThreadMotionCoordinator({
    camera,
    measure,
    onGeometry,
    onAutoFollow,
    scheduler,
  });
  const advanceFrame = () => {
    const pending = [...frames.entries()];
    frames.clear();
    for (const [, callback] of pending) callback(16);
  };
  const setGeometry = (next: Partial<ThreadMotionGeometry>) => {
    const updated = { ...geometry, ...next };
    geometry = {
      ...updated,
      maxScrollTop: next.maxScrollTop
        ?? Math.max(0, updated.scrollHeight - updated.clientHeight),
    };
  };
  const setCameraFollowing = (following: boolean) => {
    cameraFollowing = following;
  };

  return {
    camera,
    coordinator,
    frames,
    measure,
    onAutoFollow,
    onGeometry,
    scheduler,
    advanceFrame,
    setCameraFollowing,
    setGeometry,
  };
}

describe("ThreadMotionCoordinator", () => {
  it("coalesces discrete invalidations into one authoritative geometry frame", () => {
    const {
      camera,
      coordinator,
      frames,
      measure,
      scheduler,
      advanceFrame,
    } = motionHarness();

    coordinator.updateTurn({
      id: "turn-1",
      promptId: "prompt-1",
      hasOutput: true,
    });
    coordinator.invalidateGeometry();
    coordinator.invalidateGeometry();

    expect(scheduler.request).toHaveBeenCalledTimes(1);
    expect(frames).toHaveLength(1);
    expect(measure).not.toHaveBeenCalled();

    advanceFrame();

    expect(measure).toHaveBeenCalledTimes(1);
    expect(measure).toHaveBeenCalledWith("prompt-1");
    expect(camera.jumpTo).toHaveBeenCalledWith(404);
    expect(camera.followTo).toHaveBeenCalledWith(1_400);
    expect(coordinator.snapshot()).toMatchObject({
      mode: "follow-output",
      promptPositioned: true,
      measurementPending: false,
    });
  });

  it("retargets repeated output growth without restarting camera ownership", () => {
    const {
      camera,
      coordinator,
      advanceFrame,
      setGeometry,
    } = motionHarness();
    coordinator.updateTurn({
      id: "turn-1",
      promptId: "prompt-1",
      hasOutput: true,
    });
    advanceFrame();
    camera.cancel.mockClear();
    camera.followTo.mockClear();

    setGeometry({ scrollTop: 1_400, scrollHeight: 1_928 });
    coordinator.invalidateGeometry();
    coordinator.invalidateGeometry();
    advanceFrame();
    setGeometry({ scrollTop: 1_410, scrollHeight: 1_944 });
    coordinator.invalidateGeometry();
    advanceFrame();

    expect(camera.followTo.mock.calls).toEqual([[1_428], [1_444]]);
    expect(camera.cancel).not.toHaveBeenCalled();
  });

  it.each([
    "geometry-before-completion",
    "completion-before-geometry",
  ] as const)("keeps following final layout for %s ordering", (ordering) => {
    const {
      camera,
      coordinator,
      advanceFrame,
      setGeometry,
    } = motionHarness();
    coordinator.updateTurn({
      id: "turn-1",
      promptId: "prompt-1",
      hasOutput: true,
    });
    advanceFrame();
    camera.cancel.mockClear();
    camera.followTo.mockClear();

    const applyFinalGeometry = () => {
      setGeometry({
        scrollTop: 1_400,
        scrollHeight: 2_400,
      });
      coordinator.invalidateGeometry();
    };
    if (ordering === "geometry-before-completion") applyFinalGeometry();
    coordinator.completeTurn();
    if (ordering === "completion-before-geometry") applyFinalGeometry();

    expect(coordinator.snapshot().mode).toBe("follow-completion");
    expect(camera.cancel).not.toHaveBeenCalled();
    advanceFrame();
    expect(camera.followTo).toHaveBeenLastCalledWith(1_900);

    setGeometry({
      scrollTop: 1_900,
      scrollHeight: 2_450,
    });
    coordinator.invalidateGeometry();
    advanceFrame();
    expect(camera.followTo).toHaveBeenLastCalledWith(1_950);
  });

  it("keeps turn identity stable when canonical replay replaces DOM ids", () => {
    const {
      camera,
      coordinator,
      measure,
      advanceFrame,
      setGeometry,
    } = motionHarness();
    coordinator.updateTurn({
      id: "turn-stable",
      promptId: "optimistic-prompt",
      hasOutput: true,
    });
    advanceFrame();
    camera.jumpTo.mockClear();
    measure.mockClear();

    setGeometry({ scrollHeight: 2_020, promptTop: 120 });
    coordinator.updateTurn({
      id: "turn-stable",
      promptId: "canonical-prompt",
      hasOutput: true,
    });
    advanceFrame();

    expect(measure).toHaveBeenCalledWith(null);
    expect(camera.jumpTo).not.toHaveBeenCalled();
    expect(camera.followTo).toHaveBeenLastCalledWith(1_520);
  });

  it("continues from the bottom when a running turn is restored before prompt identity", () => {
    const {
      camera,
      coordinator,
      advanceFrame,
    } = motionHarness({
      scrollTop: 1_400,
    });

    coordinator.updateTurn({
      id: "turn-restored",
      promptId: null,
      hasOutput: true,
      entry: "restored",
    });
    advanceFrame();

    expect(camera.jumpTo).not.toHaveBeenCalled();
    expect(camera.followTo).toHaveBeenCalledWith(1_400);
    expect(coordinator.snapshot()).toMatchObject({
      mode: "follow-output",
      promptPositioned: true,
    });
  });

  it("continues measuring while browsing history but does not steal the viewport", () => {
    const {
      camera,
      coordinator,
      onGeometry,
      advanceFrame,
      setGeometry,
    } = motionHarness();
    coordinator.updateTurn({
      id: "turn-1",
      promptId: "prompt-1",
      hasOutput: true,
    });
    advanceFrame();
    camera.followTo.mockClear();
    onGeometry.mockClear();

    coordinator.takeUserControl();
    setGeometry({ scrollTop: 200, scrollHeight: 2_100 });
    coordinator.invalidateGeometry();
    advanceFrame();

    expect(onGeometry).toHaveBeenCalledTimes(1);
    expect(camera.followTo).not.toHaveBeenCalled();
    expect(coordinator.snapshot().mode).toBe("browsing-history");

    coordinator.resumeAutoFollow();
    advanceFrame();
    expect(camera.followTo).toHaveBeenCalledWith(1_600);
  });

  it("treats scroll events as observations until explicit user intent takes control", () => {
    const {
      camera,
      coordinator,
      advanceFrame,
      setGeometry,
    } = motionHarness({
      scrollTop: 700,
      scrollHeight: 1_200,
      clientHeight: 500,
      maxScrollTop: 700,
    });
    coordinator.updateTurn({
      id: "turn-1",
      promptId: "prompt-1",
      hasOutput: false,
    });
    advanceFrame();
    camera.jumpTo.mockClear();

    setGeometry({
      scrollTop: 700,
      scrollHeight: 1_280,
    });
    expect(coordinator.observeScroll(false)).toBe("automatic");
    expect(coordinator.snapshot().mode).toBe("anchor-prompt");
    advanceFrame();
    expect(camera.jumpTo).toHaveBeenCalledWith(780);

    coordinator.takeUserControl();
    expect(coordinator.observeScroll(false)).toBe("user");
    expect(coordinator.snapshot().mode).toBe("browsing-history");

    expect(coordinator.observeScroll(true)).toBe("automatic");
    expect(coordinator.snapshot().mode).toBe("anchor-prompt");
  });

  it("preserves history browsing when an active turn is cleared", () => {
    const {
      camera,
      coordinator,
      advanceFrame,
    } = motionHarness();
    coordinator.updateTurn({
      id: "turn-1",
      promptId: "prompt-1",
      hasOutput: true,
    });
    advanceFrame();
    coordinator.takeUserControl();
    camera.followTo.mockClear();

    coordinator.updateTurn({
      id: null,
      promptId: null,
      hasOutput: false,
    });
    advanceFrame();

    expect(coordinator.snapshot().mode).toBe("browsing-history");
    expect(camera.followTo).not.toHaveBeenCalled();
  });

  it("keeps history navigation independent from active turn completion", () => {
    const {
      camera,
      coordinator,
      advanceFrame,
    } = motionHarness();
    coordinator.updateTurn({
      id: "turn-1",
      promptId: "prompt-1",
      hasOutput: true,
    });
    advanceFrame();
    coordinator.navigateHistoryTo(900);
    camera.cancel.mockClear();

    coordinator.completeTurn();

    expect(camera.cancel).not.toHaveBeenCalled();
    expect(coordinator.snapshot().mode).toBe("navigating-history");
  });

  it("moves from rail navigation to history browsing on user intent", () => {
    const {
      camera,
      coordinator,
      setCameraFollowing,
    } = motionHarness();

    coordinator.handleUserScrollIntent(false);
    expect(coordinator.snapshot().mode).toBe("idle");
    expect(camera.cancel).not.toHaveBeenCalled();

    coordinator.navigateHistoryTo(900);
    expect(camera.navigateTo).toHaveBeenCalledWith(900);
    expect(coordinator.snapshot().mode).toBe("navigating-history");
    expect(coordinator.observeScroll(false)).toBe("navigation");

    camera.cancel.mockClear();
    coordinator.handleUserScrollIntent(false);
    expect(camera.cancel).toHaveBeenCalledTimes(1);
    expect(coordinator.snapshot().mode).toBe("browsing-history");
    expect(coordinator.observeScroll(false)).toBe("user");

    coordinator.navigateHistoryTo(700);
    camera.cancel.mockClear();
    coordinator.takeUserControl();
    expect(camera.cancel).toHaveBeenCalledTimes(1);
    expect(coordinator.snapshot().mode).toBe("browsing-history");

    camera.cancel.mockClear();
    coordinator.takeUserControl();
    expect(camera.cancel).not.toHaveBeenCalled();

    coordinator.navigateHistoryTo(600);
    setCameraFollowing(false);
    expect(coordinator.observeScroll(false)).toBe("navigation");
    expect(coordinator.snapshot().mode).toBe("browsing-history");
  });

  it("pins a waiting prompt to the exact lower boundary across all layout changes", () => {
    const {
      camera,
      coordinator,
      advanceFrame,
      setGeometry,
    } = motionHarness({
      scrollHeight: 930,
      clientHeight: 500,
      maxScrollTop: 430,
    });
    coordinator.updateTurn({
      id: "turn-1",
      promptId: "prompt-1",
      hasOutput: false,
    });
    advanceFrame();
    expect(camera.jumpTo).toHaveBeenLastCalledWith(430);

    setGeometry({
      composerHeight: 148,
      scrollHeight: 958,
      promptTop: 404,
    });
    coordinator.invalidateGeometry();
    advanceFrame();

    expect(camera.jumpTo.mock.calls).toEqual([[430], [458]]);
    expect(camera.followTo).not.toHaveBeenCalled();
    expect(coordinator.snapshot().mode).toBe("anchor-prompt");

    setGeometry({
      scrollTop: 458,
      scrollHeight: 990,
    });
    coordinator.invalidateGeometry();
    advanceFrame();

    expect(camera.jumpTo.mock.calls).toEqual([[430], [458], [490]]);
  });
});
