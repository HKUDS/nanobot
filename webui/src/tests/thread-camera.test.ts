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
  it("pins automatic follow in the geometry frame without camera debt", () => {
    const { camera, viewport, frames } = cameraHarness();

    expect(camera.followTo(60)).toBe("settled");

    expect(viewport.scrollTop).toBe(60);
    expect(frames).toHaveLength(0);
    expect(camera.isFollowing()).toBe(false);
  });

  it("retargets active history navigation without adding another loop", () => {
    const { camera, viewport, frames, advance } = cameraHarness();

    expect(camera.navigateTo(100)).toBe("started");
    expect(frames).toHaveLength(1);
    advance(16);
    expect(frames).toHaveLength(1);

    expect(camera.navigateTo(180)).toBe("retargeted");
    expect(frames).toHaveLength(1);
    for (let frame = 0; frame < 120; frame += 1) advance(16);
    expect(viewport.scrollTop).toBe(180);
  });

  it("pins repeated automatic targets without accumulating lag", () => {
    const { camera, viewport, frames } = cameraHarness();

    camera.followTo(80);
    expect(viewport.scrollTop).toBe(80);
    camera.followTo(140);
    expect(viewport.scrollTop).toBe(140);
    camera.followTo(220);
    expect(viewport.scrollTop).toBe(220);
    expect(frames).toHaveLength(0);
    expect(camera.isFollowing()).toBe(false);
  });

  it("eases explicit long-distance navigation across frames", () => {
    const { camera, viewport, advance } = cameraHarness();

    camera.navigateTo(1_000);
    advance(16);

    expect(viewport.scrollTop).toBeGreaterThan(0);
    expect(viewport.scrollTop).toBeLessThan(1_000);
  });

  it("settles exactly when the viewport quantizes subpixel tail movement", () => {
    const { camera, viewport, advance } = cameraHarness();
    let quantizedTop = 0;
    Object.defineProperty(viewport, "scrollTop", {
      configurable: true,
      get: () => quantizedTop,
      set: (value: number) => {
        quantizedTop = Math.floor(value);
      },
    });

    expect(camera.navigateTo(10)).toBe("started");
    for (let frame = 0; frame < 60; frame += 1) advance(16);

    expect(camera.isFollowing()).toBe(false);
    expect(viewport.scrollTop).toBe(10);
  });

  it("gives an immediate jump command priority over an active follow", () => {
    const { camera, viewport, scheduler, frames } = cameraHarness();

    camera.navigateTo(240);
    expect(frames).toHaveLength(1);
    camera.jumpTo(40);

    expect(camera.isFollowing()).toBe(false);
    expect(viewport.scrollTop).toBe(40);
    expect(scheduler.cancel).toHaveBeenCalledTimes(1);
    expect(frames).toHaveLength(0);
  });

  it("preserves spatial continuity with shorter reduced-motion navigation", () => {
    const regular = cameraHarness();
    const reduced = cameraHarness(true);

    expect(regular.camera.navigateTo(240)).toBe("started");
    expect(reduced.camera.navigateTo(240)).toBe("started");

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
