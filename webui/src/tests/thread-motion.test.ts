import { describe, expect, it, vi } from "vitest";

import { type ThreadCameraFollowResult } from "@/components/thread/thread-camera";
import {
  ThreadMotionCoordinator,
  type ThreadMotionGeometry,
  type ThreadMotionScheduler,
} from "@/components/thread/thread-motion";

function motionHarness(initial?: Partial<ThreadMotionGeometry>) {
  let nextFrameId = 1;
  let cameraFollowing = false;
  let nextNavigationResult: ThreadCameraFollowResult = "started";
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
  const scheduler = {
    request: vi.fn<ThreadMotionScheduler["request"]>((callback) => {
      const id = nextFrameId;
      nextFrameId += 1;
      frames.set(id, callback);
      return id;
    }),
    cancel: vi.fn<ThreadMotionScheduler["cancel"]>((id) => {
      frames.delete(id);
    }),
  } satisfies ThreadMotionScheduler;
  const camera = {
    cancel: vi.fn(() => {
      cameraFollowing = false;
    }),
    dispose: vi.fn(),
    observeScroll: vi.fn(() => 0),
    reset: vi.fn(() => { cameraFollowing = false; }),
    jumpTo: vi.fn(),
    isFollowing: vi.fn(() => cameraFollowing),
    navigateTo: vi.fn(() => {
      cameraFollowing = nextNavigationResult !== "settled";
      return nextNavigationResult;
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
  const settleCamera = () => {
    cameraFollowing = false;
    coordinator.cameraSettled();
  };
  const setNextNavigationResult = (result: ThreadCameraFollowResult) => {
    nextNavigationResult = result;
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
    settleCamera,
    setGeometry,
    setNextNavigationResult,
  };
}

describe("ThreadMotionCoordinator", () => {
  it("coalesces geometry changes, animates the submitted prompt, then stops following", () => {
    const { camera, coordinator, frames, measure, scheduler, advanceFrame, setGeometry, settleCamera } = motionHarness();
    coordinator.updateTurn("turn-1");
    coordinator.anchorSubmittedPrompt("prompt-1");
    coordinator.invalidateGeometry();
    expect(scheduler.request).toHaveBeenCalledTimes(1);
    expect(frames).toHaveLength(1);
    advanceFrame();
    expect(measure).toHaveBeenCalledWith("prompt-1", true);
    expect(camera.navigateTo).toHaveBeenCalledTimes(1);
    expect(camera.navigateTo).toHaveBeenCalledWith(404);
    expect(camera.jumpTo).not.toHaveBeenCalled();
    expect(coordinator.snapshot().mode).toBe("anchor-prompt");

    settleCamera();
    expect(coordinator.snapshot().mode).toBe("idle");
    camera.navigateTo.mockClear();
    setGeometry({ scrollHeight: 2_200 });
    coordinator.invalidateGeometry();
    advanceFrame();
    expect(measure).toHaveBeenLastCalledWith(null, false);
    coordinator.updateTurn(null);
    setGeometry({ scrollHeight: 2_400 });
    coordinator.reconcileObservedGeometry();
    expect(camera.navigateTo).not.toHaveBeenCalled();
    expect(camera.jumpTo).not.toHaveBeenCalled();
  });

  it("animates a prompt even if a quick turn completes before the frame", () => {
    const { camera, coordinator, advanceFrame, settleCamera } = motionHarness();
    coordinator.updateTurn("turn-1");
    coordinator.anchorSubmittedPrompt("prompt-1");
    coordinator.updateTurn(null);
    advanceFrame();
    expect(camera.navigateTo).toHaveBeenCalledWith(404);
    expect(camera.jumpTo).not.toHaveBeenCalled();
    expect(coordinator.snapshot().mode).toBe("anchor-prompt");
    settleCamera();
    expect(coordinator.snapshot().mode).toBe("idle");
  });

  it("uses a canonical prompt id if replay replaces it before positioning", () => {
    const { camera, coordinator, measure, advanceFrame, settleCamera } = motionHarness();
    coordinator.updateTurn("turn-1");
    coordinator.anchorSubmittedPrompt("optimistic");
    coordinator.updatePendingPromptId("canonical");
    advanceFrame();
    expect(measure).toHaveBeenCalledWith("canonical", true);
    expect(camera.navigateTo).toHaveBeenCalledWith(404);
    expect(camera.jumpTo).not.toHaveBeenCalled();
    settleCamera();
    camera.navigateTo.mockClear();
    coordinator.updatePendingPromptId("another-id");
    coordinator.invalidateGeometry();
    advanceFrame();
    expect(camera.navigateTo).not.toHaveBeenCalled();
    expect(camera.jumpTo).not.toHaveBeenCalled();
  });

  it("retargets an in-flight anchor to a canonical prompt and releases it on settlement", () => {
    const { camera, coordinator, measure, advanceFrame, setGeometry, setNextNavigationResult, settleCamera } = motionHarness();
    coordinator.updateTurn("turn-1");
    coordinator.anchorSubmittedPrompt("optimistic");
    advanceFrame();
    setNextNavigationResult("retargeted");
    setGeometry({ promptTop: 520 });
    coordinator.updatePendingPromptId("canonical");
    advanceFrame();
    expect(measure).toHaveBeenLastCalledWith("canonical", true);
    expect(camera.navigateTo.mock.calls).toEqual([[404], [520]]);
    expect(coordinator.snapshot().mode).toBe("anchor-prompt");
    settleCamera();
    expect(coordinator.snapshot().mode).toBe("idle");
    camera.navigateTo.mockClear();
    setGeometry({ promptTop: 600 });
    coordinator.reconcileObservedGeometry();
    expect(camera.navigateTo).not.toHaveBeenCalled();
  });

  it("settles an already aligned submitted prompt immediately", () => {
    const { camera, coordinator, advanceFrame, setNextNavigationResult } = motionHarness({ promptTop: 400 });
    setNextNavigationResult("settled");
    coordinator.anchorSubmittedPrompt("prompt-1");
    advanceFrame();
    expect(camera.navigateTo).toHaveBeenCalledWith(400);
    expect(coordinator.snapshot().mode).toBe("idle");
  });

  it.each(["before the frame", "during animation", "at the scroll boundary"])(
    "respects user takeover %s",
    (timing) => {
      const { camera, coordinator, advanceFrame, setGeometry, settleCamera } = motionHarness(
        timing === "at the scroll boundary" ? { scrollTop: 0 } : undefined,
      );
      coordinator.updateTurn("turn-1");
      coordinator.anchorSubmittedPrompt("prompt-1");
      if (timing !== "before the frame") {
        advanceFrame();
        expect(camera.navigateTo).toHaveBeenCalledWith(404);
      }
      camera.navigateTo.mockClear();
      camera.cancel.mockClear();
      if (timing === "at the scroll boundary") coordinator.handleUserScrollIntent(false);
      else coordinator.takeUserControl();
      expect(camera.cancel).toHaveBeenCalledOnce();
      setGeometry({ scrollHeight: 2_100 });
      coordinator.invalidateGeometry();
      advanceFrame();
      settleCamera();
      expect(camera.navigateTo).not.toHaveBeenCalled();
      expect(camera.jumpTo).not.toHaveBeenCalled();
      expect(coordinator.snapshot().mode).toBe("browsing-history");
    },
  );

  it("preserves history browsing through output growth and turn completion", () => {
    const { camera, coordinator, onGeometry, advanceFrame, setGeometry } = motionHarness();
    coordinator.updateTurn("turn-1");
    coordinator.anchorSubmittedPrompt("prompt-1");
    advanceFrame();
    coordinator.takeUserControl();
    camera.jumpTo.mockClear();
    camera.navigateTo.mockClear();
    onGeometry.mockClear();
    setGeometry({ scrollTop: 200, scrollHeight: 2_100 });
    coordinator.updateTurn(null);
    advanceFrame();
    expect(onGeometry).toHaveBeenCalledTimes(1);
    expect(camera.jumpTo).not.toHaveBeenCalled();
    expect(camera.navigateTo).not.toHaveBeenCalled();
    expect(coordinator.snapshot().mode).toBe("browsing-history");
  });

  it("does not resume streaming follow when the reader reaches the tail", () => {
    const { camera, coordinator, onAutoFollow, advanceFrame, setGeometry, settleCamera } = motionHarness();
    coordinator.updateTurn("turn-1");
    coordinator.anchorSubmittedPrompt("prompt-1");
    advanceFrame();
    settleCamera();
    coordinator.handleUserScrollIntent(true);
    coordinator.handleUserScrollIntent(true, true);
    expect(coordinator.observeScroll(true)).toBe("automatic");
    expect(onAutoFollow).toHaveBeenCalledTimes(1);
    expect(coordinator.snapshot().mode).toBe("idle");
    camera.jumpTo.mockClear();
    camera.navigateTo.mockClear();
    setGeometry({ scrollHeight: 2_400 });
    coordinator.invalidateGeometry();
    advanceFrame();
    expect(camera.jumpTo).not.toHaveBeenCalled();
    expect(camera.navigateTo).not.toHaveBeenCalled();
  });

  it("stops idle tail following when a running turn is restored", () => {
    const { camera, coordinator, advanceFrame, setGeometry } = motionHarness();
    coordinator.resumeAutoFollow();
    advanceFrame();
    expect(camera.jumpTo).toHaveBeenCalledWith(1_400);
    camera.jumpTo.mockClear();
    coordinator.updateTurn("restored-turn");
    setGeometry({ scrollTop: 1_400, scrollHeight: 2_000 });
    advanceFrame();
    expect(camera.jumpTo).not.toHaveBeenCalled();
    expect(coordinator.snapshot().mode).toBe("idle");
  });

  it("settles restored transcript layout at the tail until new output arrives", () => {
    const { camera, coordinator, advanceFrame, setGeometry } = motionHarness();
    coordinator.updateTurn("restored-turn");
    coordinator.followOpeningLayout();
    setGeometry({ scrollTop: 1_400, scrollHeight: 2_000 });
    advanceFrame();
    expect(camera.jumpTo).toHaveBeenCalledWith(1_500);
    coordinator.finishOpeningLayout();
    camera.jumpTo.mockClear();
    setGeometry({ scrollTop: 1_500, scrollHeight: 2_200 });
    coordinator.invalidateGeometry();
    advanceFrame();
    expect(camera.jumpTo).not.toHaveBeenCalled();
    expect(coordinator.snapshot().mode).toBe("idle");
  });

  it("lets user input take control while restored transcript layout is settling", () => {
    const { camera, coordinator, advanceFrame, setGeometry } = motionHarness();
    coordinator.updateTurn("restored-turn");
    coordinator.followOpeningLayout();
    coordinator.takeUserControl();
    coordinator.finishOpeningLayout();
    setGeometry({ scrollHeight: 2_000 });
    advanceFrame();
    expect(camera.jumpTo).not.toHaveBeenCalled();
    expect(coordinator.snapshot().mode).toBe("browsing-history");
  });

  it("keeps an explicitly resumed idle thread pinned as its layout grows", () => {
    const { camera, coordinator, scheduler, frames, advanceFrame, setGeometry } = motionHarness();
    coordinator.resumeAutoFollow();
    advanceFrame();
    expect(camera.jumpTo).toHaveBeenLastCalledWith(1_400);
    camera.jumpTo.mockClear();
    scheduler.cancel.mockClear();
    setGeometry({ scrollTop: 1_400, scrollHeight: 2_054 });
    coordinator.invalidateGeometry();
    coordinator.reconcileObservedGeometry();
    expect(camera.jumpTo).toHaveBeenCalledWith(1_554);
    expect(scheduler.cancel).toHaveBeenCalledTimes(1);
    expect(frames).toHaveLength(0);
    coordinator.takeUserControl();
    camera.jumpTo.mockClear();
    setGeometry({ scrollTop: 300, scrollHeight: 2_100 });
    coordinator.invalidateGeometry();
    advanceFrame();
    expect(camera.jumpTo).not.toHaveBeenCalled();
  });

  it("retargets explicit latest navigation while moving, then stops following", () => {
    const { camera, coordinator, advanceFrame, setCameraFollowing, setGeometry } = motionHarness();
    coordinator.updateTurn("turn-1");
    coordinator.anchorSubmittedPrompt("prompt-1");
    advanceFrame();
    coordinator.takeUserControl();
    camera.navigateTo.mockClear();
    coordinator.navigateLatestTo(1_400);
    setGeometry({ scrollTop: 900, scrollHeight: 2_100 });
    coordinator.invalidateGeometry();
    advanceFrame();
    expect(camera.navigateTo.mock.calls).toEqual([[1_400], [1_600]]);
    setCameraFollowing(false);
    expect(coordinator.observeScroll(true)).toBe("navigation");
    expect(coordinator.snapshot().mode).toBe("idle");
    camera.jumpTo.mockClear();
    setGeometry({ scrollTop: 1_600, scrollHeight: 2_300 });
    coordinator.invalidateGeometry();
    advanceFrame();
    expect(camera.jumpTo).not.toHaveBeenCalled();
  });

  it("keeps history navigation in control through turn completion", () => {
    const { camera, coordinator, advanceFrame, setGeometry } = motionHarness();
    coordinator.updateTurn("turn-1");
    coordinator.anchorSubmittedPrompt("prompt-1");
    advanceFrame();
    setGeometry({ promptTop: 900 });
    coordinator.navigateHistoryToPrompt("prompt-2");
    camera.cancel.mockClear();
    coordinator.updateTurn(null);
    expect(camera.cancel).not.toHaveBeenCalled();
    expect(coordinator.snapshot().mode).toBe("navigating-history");
  });

  it("moves from rail navigation to history browsing on user intent", () => {
    const {
      camera,
      coordinator,
      setCameraFollowing,
      setGeometry,
    } = motionHarness();

    coordinator.handleUserScrollIntent(false);
    expect(coordinator.snapshot().mode).toBe("idle");
    expect(camera.cancel).not.toHaveBeenCalled();

    setGeometry({ promptTop: 900 });
    coordinator.navigateHistoryToPrompt("prompt-1");
    expect(camera.navigateTo).toHaveBeenCalledWith(900);
    expect(coordinator.snapshot().mode).toBe("navigating-history");
    expect(coordinator.observeScroll(false)).toBe("navigation");

    camera.cancel.mockClear();
    coordinator.handleUserScrollIntent(false);
    expect(camera.cancel).toHaveBeenCalledTimes(1);
    expect(coordinator.snapshot().mode).toBe("browsing-history");
    expect(coordinator.observeScroll(false)).toBe("user");

    setGeometry({ promptTop: 700 });
    coordinator.navigateHistoryToPrompt("prompt-2");
    camera.cancel.mockClear();
    coordinator.takeUserControl();
    expect(camera.cancel).toHaveBeenCalledTimes(1);
    expect(coordinator.snapshot().mode).toBe("browsing-history");

    camera.cancel.mockClear();
    coordinator.takeUserControl();
    expect(camera.cancel).not.toHaveBeenCalled();

    setGeometry({ promptTop: 600 });
    coordinator.navigateHistoryToPrompt("prompt-3");
    setCameraFollowing(false);
    expect(coordinator.observeScroll(false)).toBe("navigation");
    expect(coordinator.snapshot().mode).toBe("browsing-history");
  });

  it("settles camera navigation without relying on a scroll event", () => {
    const { coordinator } = motionHarness({ promptTop: 200 });
    coordinator.takeUserControl();
    coordinator.navigateLatestTo(1_400);
    coordinator.cameraSettled();
    expect(coordinator.snapshot().mode).toBe("follow-latest");

    coordinator.navigateHistoryToPrompt("prompt-1");
    coordinator.cameraSettled();
    expect(coordinator.snapshot().mode).toBe("navigating-history");
  });

  it("keeps explicit latest navigation in control when already following the tail", () => {
    const { camera, coordinator, advanceFrame, setCameraFollowing } = motionHarness();
    coordinator.resumeAutoFollow();
    advanceFrame();

    expect(coordinator.snapshot().mode).toBe("follow-latest");
    expect(coordinator.navigateLatestTo(1_400)).toBe("started");
    expect(coordinator.snapshot().mode).toBe("navigating-latest");
    expect(coordinator.observeScroll(true)).toBe("navigation");
    expect(camera.isFollowing()).toBe(true);

    setCameraFollowing(false);
    coordinator.cameraSettled();
    expect(coordinator.snapshot().mode).toBe("follow-latest");
  });

  it("retargets a prompt navigation from authoritative geometry without restarting the camera", () => {
    const { camera, coordinator, measure, setGeometry } = motionHarness();
    coordinator.navigateHistoryToPrompt("prompt-46");
    expect(measure).toHaveBeenCalledWith("prompt-46");
    expect(camera.navigateTo).toHaveBeenLastCalledWith(404);
    expect(coordinator.snapshot().mode).toBe("navigating-history");

    camera.cancel.mockClear();
    setGeometry({ promptTop: 520 });
    coordinator.reconcileObservedGeometry();

    expect(measure).toHaveBeenLastCalledWith("prompt-46", false);
    expect(camera.navigateTo).toHaveBeenLastCalledWith(520);
    expect(camera.cancel).not.toHaveBeenCalled();
    expect(coordinator.snapshot().mode).toBe("navigating-history");
  });

  it("releases prompt retarget ownership on composer input and user takeover", () => {
    const { camera, coordinator, setGeometry } = motionHarness();
    coordinator.navigateHistoryToPrompt("prompt-46");
    camera.cancel.mockClear();
    coordinator.handleComposerInput();
    expect(camera.cancel).toHaveBeenCalledTimes(1);
    expect(coordinator.snapshot().mode).toBe("browsing-history");
    const callsAfterComposer = camera.navigateTo.mock.calls.length;
    setGeometry({ promptTop: 600 });
    coordinator.reconcileObservedGeometry();
    expect(camera.navigateTo).toHaveBeenCalledTimes(callsAfterComposer);

    coordinator.navigateHistoryToPrompt("prompt-47");
    camera.cancel.mockClear();
    coordinator.handleUserScrollIntent(true);
    expect(camera.cancel).toHaveBeenCalledTimes(1);
    expect(coordinator.snapshot().mode).toBe("browsing-history");
    const callsAfterTouch = camera.navigateTo.mock.calls.length;
    setGeometry({ promptTop: 700 });
    coordinator.reconcileObservedGeometry();
    expect(camera.navigateTo).toHaveBeenCalledTimes(callsAfterTouch);
  });

  it("drops prompt identity when an aligned navigation settles immediately", () => {
    const { camera, coordinator, measure, setGeometry, setNextNavigationResult } = motionHarness();
    setNextNavigationResult("settled");
    expect(coordinator.navigateHistoryToPrompt("prompt-46")).toBe("settled");
    expect(measure).toHaveBeenCalledWith("prompt-46");
    expect(coordinator.snapshot().mode).toBe("browsing-history");
    const callsAfterSettle = camera.navigateTo.mock.calls.length;
    setGeometry({ promptTop: 720 });
    coordinator.reconcileObservedGeometry();
    expect(camera.navigateTo).toHaveBeenCalledTimes(callsAfterSettle);
    expect(coordinator.snapshot().mode).toBe("browsing-history");
  });
});
