import { describe, expect, it, vi } from "vitest";
import { HISTORY_PULL_LIMIT_PX, ThreadHistorySpring } from "@/components/thread/thread-history-spring";

function harness(reduced = false) {
  let now = 0;
  let nextId = 0;
  let distance = 0;
  const frames = new Map<number, FrameRequestCallback>();
  const scheduler = {
    now: () => now,
    request: vi.fn((callback: FrameRequestCallback) => { frames.set(++nextId, callback); return nextId; }),
    cancel: (id: number) => { frames.delete(id); },
  };
  const spring = new ThreadHistorySpring({ scheduler, prefersReducedMotion: () => reduced,
    onUpdate: (next) => { distance = next; } });
  const advance = (milliseconds = 16) => {
    now += milliseconds;
    const callbacks = [...frames.values()];
    frames.clear();
    callbacks.forEach((callback) => callback(now));
    return distance;
  };
  const settle = () => { for (let i = 0; i < 100 && frames.size; i++) advance(); };
  return { spring, scheduler, advance, settle, frames, distance: () => distance };
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
    expect(h.advance()).toBeGreaterThan(0);
    expect(h.distance()).toBeLessThan(pulled);
    h.settle();
    expect(h.distance()).toBe(0);
    expect(h.frames.size).toBe(0);
  });

  it("holds actual loading still, lets a new touch take over, and converges immediately after long frame gaps", () => {
    const h = harness();
    h.spring.startTouch();
    h.spring.moveTouch(120);
    expect(h.spring.endTouch()).toBe(true);
    h.spring.setLoading(true);
    h.settle();
    expect(h.distance()).toBe(20);
    expect(h.frames.size).toBe(0);
    h.spring.startTouch();
    expect(h.distance()).toBe(20);
    h.spring.moveTouch(20);
    expect(h.distance()).toBeGreaterThan(20);
    h.spring.endTouch();
    h.spring.setLoading(false);
    h.advance(30_000);
    expect(h.distance()).toBe(0);
    expect(h.frames.size).toBe(0);
  });

  it("merges decelerating wheel input into one bounded spring and one boundary request", () => {
    const h = harness();
    let requests = 0;
    for (const delta of [100, 70, 48, 32, 20, 12, 6, 2]) {
      if (h.spring.wheel(delta)) requests++;
      expect(h.frames.size).toBe(1);
      h.advance();
    }
    expect(requests).toBe(1);
    expect(h.distance()).toBeLessThan(HISTORY_PULL_LIMIT_PX);
    h.settle();
    expect(h.distance()).toBe(0);
    expect(h.spring.wheel(100)).toBe(true);
  });

  it("cancels task-owned motion on conversation changes", () => {
    const h = harness();
    h.spring.wheel(100);
    h.spring.setLoading(true);
    h.spring.reset();
    expect(h.frames.size).toBe(0);
    expect(h.distance()).toBe(0);
    expect(h.spring.wheel(100)).toBe(true);
  });

  it("keeps the touch trigger functional with reduced motion and no display travel", () => {
    const h = harness(true);
    h.spring.startTouch();
    h.spring.moveTouch(120);
    expect(h.distance()).toBe(0);
    expect(h.spring.endTouch()).toBe(true);
    h.spring.setLoading(true);
    expect(h.frames.size).toBe(0);
    expect(h.distance()).toBe(0);
  });
});
