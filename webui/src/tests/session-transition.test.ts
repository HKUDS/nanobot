import { afterEach, expect, it, vi } from "vitest";

import { finishSessionTransition, transitionSession } from "@/components/thread/session-transition";

const nativeTransition = Object.getOwnPropertyDescriptor(document, "startViewTransition");

afterEach(() => {
  transitionSession(() => {}, false);
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  if (nativeTransition) Object.defineProperty(document, "startViewTransition", nativeTransition);
  else Reflect.deleteProperty(document, "startViewTransition");
  delete document.documentElement.dataset.themeSnapshot;
});

function nativeCaptures() {
  const captures: { update: () => void; finish: () => void; skipTransition: ReturnType<typeof vi.fn> }[] = [];
  const start = vi.fn((update: () => void) => {
    let finish!: () => void;
    const finished = new Promise<void>(resolve => { finish = resolve; });
    const capture = { update, finish, skipTransition: vi.fn() };
    captures.push(capture);
    return { ready: Promise.resolve(), finished, skipTransition: capture.skipTransition };
  });
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  Object.defineProperty(document, "startViewTransition", { configurable: true, value: start });
  return { captures, start };
}

it("commits only the latest navigation when native captures are interrupted", async () => {
  const { captures } = nativeCaptures();
  const old = vi.fn();
  const latest = vi.fn();
  transitionSession(old);
  transitionSession(latest);
  expect(captures[0].skipTransition).toHaveBeenCalledOnce();
  captures[0].update();
  captures[1].update();
  expect(old).not.toHaveBeenCalled();
  expect(latest).toHaveBeenCalledOnce();
  captures[0].finish();
  await Promise.resolve();
  expect(document.documentElement).toHaveAttribute("data-session-transition");
  captures[1].finish();
  await Promise.resolve();
  expect(document.documentElement).not.toHaveAttribute("data-session-transition");
});

it("leaving chat invalidates a pending session capture", () => {
  const { captures } = nativeCaptures();
  const stale = vi.fn();
  const settings = vi.fn();
  transitionSession(stale);
  transitionSession(settings, false);
  captures[0].update();
  expect(settings).toHaveBeenCalledOnce();
  expect(stale).not.toHaveBeenCalled();
});

it.each(["reduced-motion", "theme-snapshot", "no-native-capture"])("navigates immediately with %s", mode => {
  const { start } = nativeCaptures();
  if (mode === "reduced-motion") vi.stubGlobal("matchMedia", () => ({ matches: true }));
  if (mode === "theme-snapshot") document.documentElement.dataset.themeSnapshot = "";
  if (mode === "no-native-capture") Object.defineProperty(document, "startViewTransition", { configurable: true, value: undefined });
  const update = vi.fn();
  transitionSession(update);
  expect(update).toHaveBeenCalledOnce();
  expect(start).not.toHaveBeenCalled();
});

it("finishes an accepted navigation before handing snapshots to the theme toggle", () => {
  const { captures } = nativeCaptures();
  const update = vi.fn();
  transitionSession(update);
  finishSessionTransition();
  expect(update).toHaveBeenCalledOnce();
  expect(captures[0].skipTransition).toHaveBeenCalledOnce();
  expect(document.documentElement).not.toHaveAttribute("data-session-transition");
  captures[0].update();
  expect(update).toHaveBeenCalledOnce();
});
