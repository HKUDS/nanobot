import { afterEach, describe, expect, it, vi } from "vitest";
import { waitFor } from "@testing-library/react";
import {
  HISTORY_HOLD_PX,
  HISTORY_PULL_LIMIT_PX,
  HISTORY_PULL_TRIGGER_PX,
  ThreadHistorySpring,
  type HistoryRevealPhase,
} from "@/components/thread/thread-history-spring";

const springs = new Set<ThreadHistorySpring>();

function harness(reduced = false) {
  let distance = 0;
  const phase = vi.fn<(phase: HistoryRevealPhase) => void>();
  const update = vi.fn((next: number) => { distance = next; });
  const spring = new ThreadHistorySpring({ onPhaseChange: phase, onUpdate: update, prefersReducedMotion: () => reduced });
  springs.add(spring);
  const expectBounded = () => {
    for (const [next] of update.mock.calls) {
      expect(next).toBeGreaterThanOrEqual(0);
      expect(next).toBeLessThanOrEqual(HISTORY_PULL_LIMIT_PX);
    }
  };
  return { spring, phase, update, expectBounded, distance: () => distance };
}

afterEach(() => {
  for (const spring of springs) spring.reset();
  springs.clear();
  vi.useRealTimers();
});

describe("history boundary spring", () => {
  it("resists short touch, reverses continuously, and settles transient feedback at zero", async () => {
    const h = harness();
    h.spring.startTouch();
    h.spring.moveTouch(40);
    const pulled = h.distance();
    expect(pulled).toBeGreaterThan(0);
    expect(pulled).toBeLessThan(40);
    expect(h.spring.endTouch()).toBe(false);
    expect(h.distance()).toBe(pulled);
    h.spring.startTouch();
    expect(h.distance()).toBeCloseTo(pulled);
    h.spring.moveTouch(-20);
    expect(h.distance()).toBeLessThan(pulled);
    h.spring.moveTouch(2_000);
    expect(h.distance()).toBeLessThanOrEqual(HISTORY_PULL_LIMIT_PX);
    expect(h.spring.endTouch(true)).toBe(false);
    await waitFor(() => expect(h.phase).toHaveBeenLastCalledWith("hidden"));
    expect(h.distance()).toBe(0);
    expect(h.phase.mock.calls).toEqual([["feedback"], ["hidden"]]);
    h.expectBounded();
  });

  it("uses the 56px touch threshold and keeps a request's 48px slot after completion", async () => {
    const h = harness();
    h.spring.startTouch();
    h.spring.moveTouch(120);
    expect(h.distance()).toBeGreaterThan(HISTORY_HOLD_PX);
    expect(h.distance()).toBeLessThan(HISTORY_PULL_TRIGGER_PX);
    expect(h.spring.endTouch()).toBe(false);
    await waitFor(() => expect(h.distance()).toBe(0));
    h.spring.startTouch();
    h.spring.moveTouch(160);
    expect(h.spring.endTouch()).toBe(true);
    h.spring.hold();
    await waitFor(() => expect(h.distance()).toBe(HISTORY_HOLD_PX));
    expect(h.spring.wheel(20)).toBe(false);
    h.expectBounded();
  });

  it("rearms after leaving the boundary and restores held geometry after touch takeover/cancel", async () => {
    const h = harness();
    expect(h.spring.wheel(100)).toBe(true);
    h.spring.hold();
    await waitFor(() => expect(h.distance()).toBe(HISTORY_HOLD_PX));
    h.spring.leaveBoundary();
    expect(h.distance()).toBe(HISTORY_HOLD_PX);
    expect(h.spring.wheel(100)).toBe(true);
    expect(h.spring.wheel(20)).toBe(false);
    await waitFor(() => expect(h.distance()).toBeGreaterThan(HISTORY_HOLD_PX));
    await waitFor(() => expect(h.distance()).toBe(HISTORY_HOLD_PX));
    h.spring.startTouch();
    expect(h.distance()).toBeCloseTo(HISTORY_HOLD_PX);
    h.spring.moveTouch(120);
    expect(h.distance()).toBeGreaterThan(HISTORY_PULL_TRIGGER_PX);
    expect(h.spring.endTouch(true)).toBe(false);
    await waitFor(() => expect(h.distance()).toBe(HISTORY_HOLD_PX));
    expect(h.phase.mock.calls.filter(([phase]) => phase === "held")).toHaveLength(1);
    h.expectBounded();
  });

  it("decays wheel pressure without duplicate requests and is bounded under sustained reversals", async () => {
    const h = harness();
    let requests = 0;
    for (const delta of [100, 70, 48, 32, 20, 12, 6, 2]) {
      if (h.spring.wheel(delta)) requests++;
    }
    expect(requests).toBe(1);
    await waitFor(() => expect(h.phase).toHaveBeenLastCalledWith("hidden"));
    expect(h.distance()).toBe(0);
    expect(h.phase.mock.calls).toEqual([["feedback"], ["hidden"]]);
    expect(h.spring.wheel(100)).toBe(true);
    h.spring.hold();
    await waitFor(() => expect(h.distance()).toBe(HISTORY_HOLD_PX));
    for (const direction of [1, -1, 1, -1]) {
      for (let i = 0; i < 12; i++) {
        for (let packet = 0; packet < 4; packet++) expect(h.spring.wheel(direction * 2_000)).toBe(false);
        await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
        expect(h.distance()).toBeGreaterThanOrEqual(0);
        expect(h.distance()).toBeLessThanOrEqual(HISTORY_PULL_LIMIT_PX);
      }
    }
    await waitFor(() => expect(h.distance()).toBe(HISTORY_HOLD_PX));
    h.expectBounded();
  });

  it("cancels stale completion on reset and supports immediate reuse", async () => {
    const h = harness();
    h.spring.wheel(100);
    h.spring.hold();
    await waitFor(() => expect(h.distance()).toBeGreaterThan(0));
    h.spring.reset();
    expect(h.distance()).toBe(0);
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(h.distance()).toBe(0);
    expect(h.phase).toHaveBeenLastCalledWith("hidden");
    expect(h.spring.wheel(100)).toBe(true);
    h.spring.hold();
    await waitFor(() => expect(h.distance()).toBe(HISTORY_HOLD_PX));
  });

  it("keeps reduced-motion transient input functional and settles its lifecycle without travel", async () => {
    const h = harness(true);
    h.spring.startTouch();
    h.spring.moveTouch(160);
    expect(h.distance()).toBe(0);
    expect(h.spring.endTouch()).toBe(true);
    await waitFor(() => expect(h.phase).toHaveBeenLastCalledWith("hidden"));
    expect(h.phase.mock.calls).toEqual([["feedback"], ["hidden"]]);
    expect(h.spring.wheel(100)).toBe(true);
    expect(h.spring.wheel(20)).toBe(false);
    expect(h.distance()).toBe(0);
    h.spring.leaveBoundary();
    expect(h.phase).toHaveBeenLastCalledWith("hidden");
    expect(h.update.mock.calls.every(([next]) => next === 0)).toBe(true);
  });

  it("reveals and restores the reduced-motion committed slot immediately", () => {
    const h = harness(true);
    expect(h.spring.wheel(100)).toBe(true);
    h.spring.hold();
    expect(h.distance()).toBe(HISTORY_HOLD_PX);
    h.spring.startTouch();
    h.spring.moveTouch(120);
    expect(h.spring.endTouch()).toBe(true);
    expect(h.distance()).toBe(HISTORY_HOLD_PX);
    expect(h.spring.wheel(100)).toBe(false);
    h.spring.reset();
    expect(h.distance()).toBe(0);
    h.expectBounded();
  });
});
