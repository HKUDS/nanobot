import { describe, expect, it, vi } from "vitest";

import {
  ThreadCameraController,
  type ThreadCameraScheduler,
  type ThreadCameraViewport,
} from "@/components/thread/thread-camera";

function cameraHarness(prefersReducedMotion = false) {
  let now = 0;
  let nextFrameId = 1;
  const frames = new Map<number, FrameRequestCallback>();
  const viewport: ThreadCameraViewport = {
    scrollTop: 0,
  };
  const scheduler: ThreadCameraScheduler = {
    request: vi.fn((callback) => {
      const id = nextFrameId;
      nextFrameId += 1;
      frames.set(id, callback);
      return id;
    }),
    cancel: vi.fn((id) => {
      frames.delete(id);
    }),
    now: () => now,
  };
  const camera = new ThreadCameraController(() => viewport, {
    scheduler,
    prefersReducedMotion: () => prefersReducedMotion,
  });
  const advance = (deltaMs: number) => {
    now += deltaMs;
    const pending = [...frames.entries()];
    frames.clear();
    for (const [, callback] of pending) callback(now);
  };
  return { camera, viewport, scheduler, frames, advance };
}

describe("ThreadCameraController", () => {
  it("responds immediately, then eases out as a static target gets closer", () => {
    const { camera, viewport, advance } = cameraHarness();

    camera.followTo(60);
    advance(16);
    const firstStep = viewport.scrollTop;
    advance(16);
    const secondStep = viewport.scrollTop - firstStep;
    advance(16);
    const thirdStep = viewport.scrollTop - firstStep - secondStep;

    expect(firstStep).toBeGreaterThan(0);
    expect(secondStep).toBeGreaterThan(0);
    expect(thirdStep).toBeGreaterThan(0);
    expect(secondStep).toBeLessThan(firstStep);
    expect(thirdStep).toBeLessThan(secondStep);
  });

  it("retargets an active follow without adding another loop", () => {
    const { camera, viewport, frames, advance } = cameraHarness();

    expect(camera.followTo(100)).toBe("started");
    expect(frames).toHaveLength(1);
    advance(16);
    expect(frames).toHaveLength(1);

    expect(camera.followTo(180)).toBe("retargeted");
    expect(frames).toHaveLength(1);
    for (let frame = 0; frame < 120; frame += 1) advance(16);
    expect(viewport.scrollTop).toBe(180);
  });

  it("tracks repeated target growth as one monotonic camera movement", () => {
    const { camera, viewport, advance } = cameraHarness();

    camera.followTo(80);
    advance(16);
    const first = viewport.scrollTop;
    camera.followTo(140);
    advance(16);
    const second = viewport.scrollTop;
    camera.followTo(220);
    advance(16);
    const third = viewport.scrollTop;

    expect(first).toBeGreaterThan(0);
    expect(second).toBeGreaterThan(first);
    expect(third).toBeGreaterThan(second);
    expect(camera.isFollowing()).toBe(true);
  });

  it("uses a faster motion profile for explicit long-distance navigation", () => {
    const follow = cameraHarness();
    const navigation = cameraHarness();

    follow.camera.followTo(1_000);
    navigation.camera.navigateTo(1_000);
    follow.advance(16);
    navigation.advance(16);

    expect(navigation.viewport.scrollTop).toBeGreaterThan(follow.viewport.scrollTop);
    expect(navigation.viewport.scrollTop).toBeLessThan(1_000);
  });

  it("gives an immediate jump command priority over an active follow", () => {
    const { camera, viewport, scheduler, frames } = cameraHarness();

    camera.followTo(240);
    expect(frames).toHaveLength(1);
    camera.jumpTo(40);

    expect(camera.isFollowing()).toBe(false);
    expect(viewport.scrollTop).toBe(40);
    expect(scheduler.cancel).toHaveBeenCalledTimes(1);
    expect(frames).toHaveLength(0);
  });

  it("preserves spatial continuity with a shorter reduced-motion chase", () => {
    const regular = cameraHarness();
    const reduced = cameraHarness(true);

    expect(regular.camera.followTo(240)).toBe("started");
    expect(reduced.camera.followTo(240)).toBe("started");

    regular.advance(16);
    reduced.advance(16);

    expect(reduced.viewport.scrollTop).toBeGreaterThan(regular.viewport.scrollTop);
    expect(reduced.viewport.scrollTop).toBeLessThan(240);
    expect(reduced.camera.isFollowing()).toBe(true);

    for (let frame = 0; frame < 60; frame += 1) reduced.advance(16);
    expect(reduced.camera.isFollowing()).toBe(false);
    expect(reduced.viewport.scrollTop).toBe(240);
  });
});
