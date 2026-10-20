import { describe, expect, it, vi } from "vitest";
import {
  HISTORY_HOLD_PX,
  HISTORY_PULL_LIMIT_PX,
  HISTORY_PULL_TRIGGER_PX,
  ThreadHistorySpring,
  type HistoryRevealPhase,
} from "@/components/thread/thread-history-spring";

function harness(reduced = false) {
  let now = 0;
  let nextId = 0;
  let distance = 0;
  const frames = new Map<number, FrameRequestCallback>();
  const scheduler = {
    now: () => now,
    request: vi.fn((callback: FrameRequestCallback) => { frames.set(++nextId, callback); return nextId; }),
    cancel: vi.fn((id: number) => { frames.delete(id); }),
  };
  const phase = vi.fn<(phase: HistoryRevealPhase) => void>();
  const update = vi.fn((next: number) => { distance = next; });
  const spring = new ThreadHistorySpring({ scheduler, prefersReducedMotion: () => reduced,
    onPhaseChange: phase, onUpdate: update });
  const advance = (milliseconds = 16) => {
    now += milliseconds;
    const callbacks = [...frames.values()];
    frames.clear();
    callbacks.forEach((callback) => callback(now));
    return distance;
  };
  const settle = () => {
    for (let i = 0; i < 100 && frames.size; i++) advance();
    expect(frames.size).toBe(0);
  };
  const expectBounded = () => {
    for (const [next] of update.mock.calls) {
      expect(next).toBeGreaterThanOrEqual(0);
      expect(next).toBeLessThanOrEqual(HISTORY_PULL_LIMIT_PX);
    }
  };
  return { spring, scheduler, advance, settle, frames, phase, update, expectBounded, distance: () => distance };
}

describe("history boundary spring", () => {
  it("resists a short touch and returns continuously without triggering a request", () => {
    const h = harness();
    h.spring.startTouch();
    h.spring.moveTouch(40);
    const pulled = h.distance();
    expect(pulled).toBeGreaterThan(0);
    expect(pulled).toBeLessThan(40);
    expect(h.spring.endTouch()).toBe(false);
    expect(h.distance()).toBe(pulled);
    expect(h.phase.mock.calls).toEqual([["feedback"]]);
    expect(h.advance()).toBeGreaterThan(0);
    expect(h.distance()).toBeLessThan(pulled);
    h.spring.leaveBoundary();
    expect(h.phase.mock.calls).toEqual([["feedback"]]);
    h.settle();
    expect(h.distance()).toBe(0);
    expect(h.phase.mock.calls).toEqual([["feedback"], ["hidden"]]);
    h.expectBounded();
  });

  it("uses a touch threshold above the held height and cancels even a full pull", () => {
    const h = harness();
    h.spring.startTouch();
    h.spring.moveTouch(120);
    expect(h.distance()).toBeGreaterThan(HISTORY_HOLD_PX);
    expect(h.distance()).toBeLessThan(HISTORY_PULL_TRIGGER_PX);
    expect(h.spring.endTouch()).toBe(false);
    h.settle();

    h.spring.startTouch();
    h.spring.moveTouch(2_000);
    expect(h.distance()).toBeGreaterThan(HISTORY_PULL_TRIGGER_PX);
    expect(h.spring.endTouch(true)).toBe(false);
    h.settle();
    expect(h.distance()).toBe(0);
    expect(h.phase.mock.calls).toEqual([["feedback"], ["hidden"], ["feedback"], ["hidden"]]);
    h.expectBounded();
  });

  it("keeps a request held even when it completes before the first animation frame", () => {
    const h = harness();
    expect(h.spring.wheel(100)).toBe(true);
    h.spring.hold();
    expect(h.frames.size).toBe(1);
    expect(h.phase.mock.calls).toEqual([["feedback"], ["held"]]);
    h.advance(30_000);
    expect(h.distance()).toBe(HISTORY_HOLD_PX);
    expect(h.frames.size).toBe(0);
    h.advance(30_000);
    expect(h.distance()).toBe(HISTORY_HOLD_PX);
    expect(h.spring.wheel(20)).toBe(false);
    h.settle();
    expect(h.distance()).toBe(HISTORY_HOLD_PX);
    expect(h.phase.mock.calls).toEqual([["feedback"], ["held"]]);
    h.expectBounded();
  });

  it("rearms wheel pagination after leaving the boundary without dismissing the held reveal", () => {
    const h = harness();
    expect(h.spring.wheel(100)).toBe(true);
    h.spring.hold();
    h.settle();
    expect(h.distance()).toBe(HISTORY_HOLD_PX);

    h.spring.leaveBoundary();
    expect(h.distance()).toBe(HISTORY_HOLD_PX);
    expect(h.frames.size).toBe(0);
    expect(h.phase.mock.calls).toEqual([["feedback"], ["held"]]);
    expect(h.spring.wheel(100)).toBe(true);
    expect(h.spring.wheel(20)).toBe(false);
    h.spring.hold();
    h.settle();
    h.advance(30_000);
    expect(h.distance()).toBe(HISTORY_HOLD_PX);
    expect(h.phase.mock.calls).toEqual([["feedback"], ["held"]]);
    h.expectBounded();
  });

  it("lets a new touch take over continuously and restores the held target on release", () => {
    const h = harness();
    h.spring.startTouch();
    h.spring.moveTouch(160);
    expect(h.spring.endTouch()).toBe(true);
    h.spring.hold();
    h.settle();
    expect(h.distance()).toBe(HISTORY_HOLD_PX);

    h.spring.startTouch();
    expect(h.distance()).toBe(HISTORY_HOLD_PX);
    expect(h.frames.size).toBe(0);
    h.spring.moveTouch(120);
    const pulled = h.distance();
    expect(pulled).toBeGreaterThan(HISTORY_PULL_TRIGGER_PX);
    expect(h.spring.endTouch()).toBe(true);
    expect(h.distance()).toBe(pulled);
    expect(h.advance()).toBeLessThan(pulled);
    h.settle();
    expect(h.distance()).toBe(HISTORY_HOLD_PX);
    expect(h.phase.mock.calls).toEqual([["feedback"], ["held"]]);
    h.expectBounded();
  });

  it("merges decelerating wheel input into one spring and one request marker until feedback settles", () => {
    const h = harness();
    let requests = 0;
    for (const delta of [100, 70, 48, 32, 20, 12, 6, 2]) {
      if (h.spring.wheel(delta)) requests++;
      expect(h.frames.size).toBe(1);
      h.advance();
    }
    expect(requests).toBe(1);
    expect(h.phase.mock.calls).toEqual([["feedback"]]);
    h.settle();
    expect(h.distance()).toBe(0);
    expect(h.phase.mock.calls).toEqual([["feedback"], ["hidden"]]);
    expect(h.spring.wheel(100)).toBe(true);
    h.expectBounded();
  });

  it("bounds sustained outward and reverse wheel packets without queuing frames or repeating a request", () => {
    const h = harness();
    expect(h.spring.wheel(2_000)).toBe(true);
    h.spring.hold();
    for (const direction of [1, -1, 1, -1]) {
      for (let i = 0; i < 80; i++) {
        for (let packet = 0; packet < 4; packet++) {
          expect(h.spring.wheel(direction * 2_000)).toBe(false);
          expect(h.frames.size).toBe(1);
        }
        h.advance(i % 2 === 0 ? 8 : 32);
      }
    }
    h.expectBounded();
    h.spring.startTouch();
    const takenOver = h.distance();
    h.spring.moveTouch(0);
    expect(h.distance()).toBeCloseTo(takenOver);
    expect(h.spring.endTouch(true)).toBe(false);
    h.settle();
    expect(h.distance()).toBe(HISTORY_HOLD_PX);
    expect(h.phase.mock.calls).toEqual([["feedback"], ["held"]]);
  });

  it("cancels owned animation and starts a new reveal round after a reset", () => {
    const h = harness();
    h.spring.wheel(100);
    h.spring.hold();
    h.advance();
    expect(h.distance()).toBeGreaterThan(0);
    expect(h.frames.size).toBe(1);
    h.spring.reset();
    expect(h.scheduler.cancel).toHaveBeenCalledTimes(1);
    expect(h.frames.size).toBe(0);
    expect(h.distance()).toBe(0);
    h.advance(30_000);
    expect(h.distance()).toBe(0);
    expect(h.phase.mock.calls).toEqual([["feedback"], ["held"], ["hidden"]]);
    expect(h.spring.wheel(100)).toBe(true);
  });

  it("keeps reduced-motion feedback alive internally while publishing no travel", () => {
    const h = harness(true);
    h.spring.startTouch();
    h.spring.moveTouch(160);
    expect(h.distance()).toBe(0);
    expect(h.spring.endTouch()).toBe(true);
    expect(h.frames.size).toBe(1);
    expect(h.phase.mock.calls).toEqual([["feedback"]]);
    h.advance();
    expect(h.frames.size).toBe(1);
    expect(h.phase.mock.calls).toEqual([["feedback"]]);
    h.settle();
    expect(h.phase.mock.calls).toEqual([["feedback"], ["hidden"]]);

    expect(h.spring.wheel(100)).toBe(true);
    expect(h.spring.wheel(20)).toBe(false);
    h.settle();
    expect(h.phase.mock.calls).toEqual([["feedback"], ["hidden"], ["feedback"], ["hidden"]]);
    expect(h.update.mock.calls.length).toBeGreaterThan(2);
    expect(h.update.mock.calls.every(([next]) => next === 0)).toBe(true);
  });

  it("reveals the reduced-motion held slot immediately and restores it without a bounce", () => {
    const h = harness(true);
    h.spring.wheel(100);
    expect(h.frames.size).toBe(1);
    h.spring.hold();
    expect(h.distance()).toBe(HISTORY_HOLD_PX);
    expect(h.frames.size).toBe(0);
    h.advance(30_000);
    expect(h.distance()).toBe(HISTORY_HOLD_PX);

    h.spring.startTouch();
    h.spring.moveTouch(120);
    expect(h.distance()).toBeGreaterThan(HISTORY_PULL_TRIGGER_PX);
    expect(h.spring.endTouch()).toBe(true);
    expect(h.distance()).toBe(HISTORY_HOLD_PX);
    expect(h.frames.size).toBe(0);
    expect(h.spring.wheel(100)).toBe(false);
    expect(h.distance()).toBe(HISTORY_HOLD_PX);
    expect(h.frames.size).toBe(0);
    expect(h.phase.mock.calls).toEqual([["feedback"], ["held"]]);
    h.spring.reset();
    expect(h.distance()).toBe(0);
    expect(h.phase).toHaveBeenLastCalledWith("hidden");
    h.expectBounded();
  });
});
