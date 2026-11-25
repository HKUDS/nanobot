import { flushSync } from "react-dom";

import "./session-transition.css";

export type ShellTransitionKind = "session" | "enter-settings" | "exit-settings" | "switch-view";

let active: ViewTransition | null = null;
let pending: (() => void) | null = null;

function clearTransitionMarkers(root: HTMLElement): void {
  delete root.dataset.sessionTransition;
  delete root.dataset.shellTransition;
}

export function finishSessionTransition(): void {
  const update = pending;
  pending = null;
  active?.skipTransition();
  active = null;
  clearTransitionMarkers(document.documentElement);
  if (update) flushSync(update);
}

export function transitionSession(
  update: () => void,
  animate = true,
  kind: ShellTransitionKind = "session",
): void {
  pending = update;
  active?.skipTransition();
  const root = document.documentElement;
  if (!animate || !document.startViewTransition
    || window.matchMedia("(prefers-reduced-motion: reduce)").matches
    || root.hasAttribute("data-theme-snapshot")) {
    active = null;
    pending = null;
    clearTransitionMarkers(root);
    update();
    return;
  }

  clearTransitionMarkers(root);
  if (kind === "session") {
    root.dataset.sessionTransition = "";
  } else {
    root.dataset.shellTransition = kind;
  }
  const transition = document.startViewTransition(() => {
    if (pending !== update) return;
    pending = null;
    flushSync(update);
  });
  active = transition;
  // Skipped captures still run their update; only the latest navigation may commit.
  void transition.ready.catch(() => {});
  const release = () => {
    if (active !== transition) return;
    active = null;
    clearTransitionMarkers(root);
  };
  void transition.finished.then(release, release);
}
